# -*- coding: utf-8 -*-
"""「查看源码」弹窗：只读代码视图 + 语法着色 + 复制 / 另存为 / 外部编辑器打开。

设计取舍
--------
* **源码不常驻界面**：主窗口只在算法档案卡上挂一个「📄 查看源码」按钮
  （Ctrl+U、算法树右键菜单也能进）。点开才由 :mod:`core.algo_source` 从磁盘
  按需读取并解析，关掉弹窗即释放 —— 这样 160 份实现不会拖慢启动，也不会在
  界面上「顺手把答案摊开」。
* **复用工作室的编辑器**：代码视图直接用
  :class:`ui.custom_algo_dialog.CodeEditor`（行号槽 + 等宽字体 + 当前行高亮），
  和「⌨ 自定义算法」里的编辑器长得一模一样，本模块只额外挂了一层语法着色。
* **着色分两套**：Python 用 :mod:`tokenize` 精确切词（字符串、注释、关键字、
  内置名、装饰器全部按官方词法来，多行三引号字符串也不会串色）；其它语言用
  一个单遍状态机扫注释与字符串（双斜杠、可跨行的块注释、单双引号与反引号），
  再用正则补数字与关键字。
  着色失败一律静默退回纯文本，绝不因为高亮把源码本身弄丢。
"""

from __future__ import annotations

import builtins
import io
import keyword
import re
import tokenize
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QTextCharFormat,
                           QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from core.algo_source import SourceBundle, lang_label
from ui.custom_algo_dialog import CodeEditor, mono_font

__all__ = ["SourceViewerDialog", "highlight_python", "highlight_generic"]


# ==========================================================================
# 1. 配色与语法着色
# ==========================================================================
_FORMATS: Dict[str, QTextCharFormat] = {}


def _formats() -> Dict[str, QTextCharFormat]:
    """把配色表缓存成 :class:`QTextCharFormat`（只建一次）。"""
    global _FORMATS
    if _FORMATS:
        return _FORMATS

    def mk(rgb: Tuple[int, int, int], italic: bool = False,
           bold: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(*rgb))
        f.setFontItalic(italic)
        f.setFontWeight(QFont.Bold if bold else QFont.Normal)
        return f

    _FORMATS = {
        "keyword":   mk((0xC7, 0x92, 0xEA)),          # 紫：if / for / def …
        "builtin":   mk((0x82, 0xAA, 0xFF)),          # 蓝：len / range / int …
        "string":    mk((0x9C, 0xDC, 0xFE)),          # 青：字符串
        "number":    mk((0xF7, 0x8C, 0x6C)),          # 橙：数字
        "comment":   mk((0x5E, 0x6B, 0x80), italic=True),
        "decorator": mk((0xFF, 0x9E, 0x2C)),          # 珊瑚橙：@register_algo
    }
    return _FORMATS


#: ``tokenize`` 在 3.12+ 把 f-string 拆成三个 token，这里统一当字符串处理
_FSTRING_TYPES = {getattr(tokenize, n) for n in
                  ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                  if hasattr(tokenize, n)}

#: Python 内置名（只用来上色，不影响任何逻辑）
_BUILTINS = set(dir(builtins))


class _PosMap:
    """``(行, 列)`` → QTextDocument 绝对位置。

    ``tokenize`` 的坐标是「第几行第几列」（1 基 / 0 基），而
    :meth:`QTextCharFormat` 需要文档绝对偏移。这里先把每行的 block 缓存下来，
    一次换算 O(1)；行号越界时夹到文档首尾，避免个别脏 token 抛异常。
    """

    __slots__ = ("_doc", "_blocks")

    def __init__(self, doc: QTextDocument) -> None:
        self._doc = doc
        self._blocks = [doc.findBlockByNumber(i) for i in range(doc.blockCount())]

    def at(self, row: int, col: int) -> int:
        idx = row - 1
        if idx < 0:
            return 0
        if idx >= len(self._blocks):
            return max(0, self._doc.characterCount() - 1)
        blk = self._blocks[idx]
        return min(blk.position() + col, blk.position() + blk.length() - 1)


def highlight_python(doc: QTextDocument) -> None:
    """用官方词法器给 Python 源码上色（失败静默跳过）。"""
    text = doc.toPlainText()
    if not text:
        return
    try:
        toks: List[tokenize.TokenInfo] = list(
            tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:                                 # 源码本身不完整不代表要崩
        return

    fmts = _formats()
    pmap = _PosMap(doc)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    after_at = False                                  # 上一个 token 是装饰器的 @
    for tok in toks:
        ttype, tstr = tok.type, tok.string
        fmt = None

        if ttype == tokenize.COMMENT:
            fmt = fmts["comment"]
        elif ttype == tokenize.STRING or ttype in _FSTRING_TYPES:
            fmt = fmts["string"]
        elif ttype == tokenize.NUMBER:
            fmt = fmts["number"]
        elif ttype == tokenize.NAME:
            if after_at:
                fmt = fmts["decorator"]
            elif keyword.iskeyword(tstr):
                fmt = fmts["keyword"]
            elif tstr in _BUILTINS:
                fmt = fmts["builtin"]

        after_at = (ttype == tokenize.OP and tstr == "@")
        if fmt is None:
            continue

        start = pmap.at(tok.start[0], tok.start[1])
        end = pmap.at(tok.end[0], tok.end[1])
        if end > start:
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.KeepAnchor)
            cur.setCharFormat(fmt)
    cur.endEditBlock()


#: 非 Python 语言里只需要补「数字 / 关键字」两类；注释和字符串交给扫描器
_CLIKE_KEYWORDS = """
    abstract as async await auto bool break byte case catch char class const
    continue crate def default defer del delete do double dyn else enum except
    explicit export extern false final finally float fn for from func function
    go goto if impl implements import in inline int interface internal is lambda
    let long loop match mod mut namespace new nil none null nullptr or override
    package pass private protected public raise readonly ref return self short
    signed sizeof static struct super switch template this throw throws trait
    true try type typedef typename typeof union unsafe unsigned use using var
    virtual void volatile when where while with yield
""".split()

_CLIKE_RULES: List[Tuple[str, re.Pattern]] = [
    ("number", re.compile(r"\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b")),
    ("keyword", re.compile(r"\b(?:" + "|".join(_CLIKE_KEYWORDS) + r")\b")),
]

#: 可以起止字符串的引号（反引号允许跨行，普通引号到行尾即截止）
_QUOTES = {'"', "'", "`"}


def _scan_clike(text: str) -> List[Tuple[int, int, str]]:
    """单遍扫描 C 系语法的注释与字符串。

    为什么不用纯正则：``/* ... */`` 经常跨十几行（C++ / Java 的文件头注释都是
    这样），逐行正则根本吃不到；而先把块注释交给正则又会把字符串里的 ``"/*"``
    误当成注释开头。手写状态机把两种引号、转义、``//``、``/* */`` 一次扫清，
    代价只有一次线性遍历。
    """
    spans: List[Tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in _QUOTES:
            j = i + 1
            while j < n:
                c = text[j]
                if c == "\\":
                    j += 2
                    continue
                if c == ch:
                    j += 1
                    break
                if c == "\n" and ch != "`":      # 普通引号不跨行，未闭合就到行尾
                    break
                j += 1
            end = min(j, n)
            spans.append((i, end, "string"))
            i = max(end, i + 1)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j, "comment"))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j, "comment"))
            i = j
        else:
            i += 1
    return spans


def highlight_generic(doc: QTextDocument) -> None:
    """C / C++ / Java / Rust / Go / JS / C# 的轻量着色。"""
    text = doc.toPlainText()
    if not text:
        return
    fmts = _formats()
    cur = QTextCursor(doc)
    cur.beginEditBlock()

    spans = _scan_clike(text)
    claimed: List[Tuple[int, int]] = [(s, e) for s, e, _k in spans]
    for start, end, kind in spans:
        if end <= start:
            continue
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.KeepAnchor)
        cur.setCharFormat(fmts[kind])

    for key, rx in _CLIKE_RULES:
        fmt = fmts[key]
        for m in rx.finditer(text):
            s, e = m.span()
            if e <= s or any(s < ce and e > cs for cs, ce in claimed):
                continue
            claimed.append((s, e))
            cur.setPosition(s)
            cur.setPosition(e, QTextCursor.KeepAnchor)
            cur.setCharFormat(fmt)
    cur.endEditBlock()


# ==========================================================================
# 2. 弹窗
# ==========================================================================
class SourceViewerDialog(QDialog):
    """展示一条算法的源码。

    典型用法::

        from core.algo_source import resolve_source
        SourceViewerDialog(resolve_source(meta), self).exec()
    """

    def __init__(self, bundle: SourceBundle, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bundle = bundle
        self._showing_whole = False
        self.setWindowTitle(f"源码 · {bundle.name_zh}")
        self.setMinimumSize(720, 520)
        self.resize(1040, 760)
        self._build()
        self._show_code(bundle.code)

    # ---- 界面 ------------------------------------------------------------
    def _build(self) -> None:
        b = self.bundle
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(f"#{b.index:03d}  {b.name_zh}")
        title.setObjectName("AlgoTitle")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sub = QLabel(f"{b.name_en}  ·  {lang_label(b.lang)}")
        sub.setObjectName("AlgoSub")
        sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(title)
        col.addWidget(sub)
        if b.summary:
            meta = QLabel(b.summary)
            meta.setObjectName("AlgoSub")
            meta.setFont(mono_font(9))
            meta.setWordWrap(True)
            col.addWidget(meta)
        head.addLayout(col, 1)

        self.btn_whole = QToolButton()
        self.btn_whole.setText("整文件")
        self.btn_whole.setCheckable(True)
        self.btn_whole.setCursor(Qt.PointingHandCursor)
        self.btn_whole.setToolTip(
            "默认只显示该算法本体（含它调用的辅助函数）。\n"
            "点一下可切换成整个源文件 —— 看看同文件的兄弟算法怎么写。")
        self.btn_whole.toggled.connect(self._on_whole_toggled)
        head.addWidget(self.btn_whole, 0, Qt.AlignTop)
        root.addLayout(head)

        # 来源行（可选中复制，方便顺着路径自己去翻文件）
        self.lbl_origin = QLabel(b.origin)
        self.lbl_origin.setObjectName("AlgoSub")
        self.lbl_origin.setFont(mono_font(9))
        self.lbl_origin.setToolTip(b.origin)
        self.lbl_origin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_origin)

        self.editor = CodeEditor(self)
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("（这段源码为空）")
        root.addWidget(self.editor, 1)

        self.lbl_foot = QLabel("")
        self.lbl_foot.setObjectName("AlgoSub")
        self.lbl_foot.setFont(mono_font(9))
        root.addWidget(self.lbl_foot)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_copy = QPushButton("⧉ 复制全部")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setToolTip("把当前视图里的代码整段复制到剪贴板")
        self.btn_copy.clicked.connect(self._on_copy)

        self.btn_save = QPushButton("💾 另存为…")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setToolTip("把这段源码存成独立文件（方便自己跑 / 加注释）")
        self.btn_save.clicked.connect(self._on_save)

        self.btn_open = QPushButton("↗ 用编辑器打开")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.setToolTip("调用系统默认程序打开源文件（可继续编辑）")
        self.btn_open.setEnabled(b.path is not None and Path(b.path).is_file())
        self.btn_open.clicked.connect(self._on_open_external)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("Accent")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)

        for w in (self.btn_copy, self.btn_save, self.btn_open):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        root.addLayout(row)

    # ---- 代码渲染 --------------------------------------------------------
    def _show_code(self, text: str) -> None:
        self.editor.setPlainText(text)
        doc = self.editor.document()
        if (self.bundle.lang or "").lower() in ("python", "py"):
            highlight_python(doc)
        else:
            highlight_generic(doc)
        self.editor.moveCursor(QTextCursor.Start)
        lines = text.count("\n") + 1 if text else 0
        self.lbl_foot.setText(
            f"共 {lines:,} 行 · {len(text):,} 字符 · 只读视图，不会改动磁盘上的文件")

    def _on_whole_toggled(self, on: bool) -> None:
        self._showing_whole = on
        self.btn_whole.setText("只看算法" if on else "整文件")
        self._show_code(self.bundle.whole or self.bundle.code)

    # ---- 按钮 ------------------------------------------------------------
    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.btn_copy.setText("✓ 已复制")
        QTimer.singleShot(1400, lambda: self.btn_copy.setText("⧉ 复制全部"))

    def _on_save(self) -> None:
        name = self.bundle.filename
        start = str(self.bundle.path) if self.bundle.path else str(Path.home() / name)
        suffix = Path(name).suffix.lstrip(".") or "txt"
        path, _flt = QFileDialog.getSaveFileName(
            self, "另存为源码", start,
            f"源码 (*.{suffix});;文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        if not Path(path).suffix:
            path += f".{suffix}"
        try:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.lbl_foot.setText(f"✓ 已保存到 {path}")

    def _on_open_external(self) -> None:
        path = self.bundle.path
        if path is None or not Path(path).is_file():
            QMessageBox.information(self, "文件不在了", "源文件已经被移动或删除。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))
