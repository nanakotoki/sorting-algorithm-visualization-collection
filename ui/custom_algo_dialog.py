# -*- coding: utf-8 -*-
"""多语言自定义算法工作室（代码编辑器 + 一键编译运行 + 实时预览）。

这个弹窗把 Batch 5 的能力串成一条顺手的工作流：

1. **选语言** —— 下拉框里每一项都带工具链状态（● 就绪 / ○ 未安装），
   未安装的语言会直接给出安装提示，并把「编译 / 运行 / 加入算法库」置灰。
2. **写代码** —— 带行号、Tab=4 空格、自动缩进、当前行高亮的等宽编辑器；
   切语言时自动装载 ``sdk_templates/`` 里对应的 VisualArray 模板。
3. **编译并运行** —— 后台线程里编译 + 在预览数据上真跑一遍，回来就能拖滑块
   逐帧看效果，与主窗口用的是**同一套**渲染内核与指令流管线。
4. **加入算法库** —— 注册进 ``core.registry``，立刻出现在左侧算法树、
   可参与四宫格赛马、可导出视频，与内置 160 种完全平权。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeySequence, QPainter,
                           QShortcut, QTextCursor, QTextFormat)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSlider, QSpinBox, QSplitter,
                               QTabWidget, QTextBrowser, QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

from core.data_generator import generate
from core.polyglot_runner import (DEFAULT_RUN_TIMEOUT, BuildResult,
                                  PolyglotError, PolyglotProgram, RunOutcome,
                                  Toolchain, ToolchainMissing,
                                  cached_toolchains, default_export_dir,
                                  detect_toolchains, export_all_templates,
                                  language_list, language_spec,
                                  main_class_name, register_custom, run_source,
                                  template_source, unregister_custom)
from ui.canvas_widget import CanvasWidget, VizFrame

#: 未安装工具链时给用户的安装提示
INSTALL_HINTS: Dict[str, str] = {
    "cpp": "安装 MinGW-w64（或 Visual Studio 的 MSVC），确保 g++ / clang++ 在 PATH 中",
    "c": "安装 MinGW-w64（或 MSVC），确保 gcc / clang 在 PATH 中",
    "python": "Python 解释器随本程序一起运行，正常不会缺失",
    "java": "安装 JDK 21+（如 Temurin / Oracle JDK），确保 javac 在 PATH 中",
    "rust": "访问 https://rustup.rs 安装 rustup，装完 rustc 即可用",
    "go": "安装 Go 工具链（https://go.dev/dl），确保 go 在 PATH 中",
    "js": "安装 Node.js（https://nodejs.org），确保 node 在 PATH 中",
    "cs": "安装 .NET SDK 8.0+（https://dotnet.microsoft.com/download）",
}

#: 协议速查表（显示在「协议说明」页）
PROTOCOL_HELP = """<h3>跨语言指令协议（stdin / stdout）</h3>
<p>主程序向子进程 <b>stdin</b> 写入两行：第 1 行是整数 N，第 2 行是 N 个空格分隔的整数。<br>
你的程序在执行排序逻辑时，向 <b>stdout</b> 逐行打印下列指令（<b>每行必须以换行结束并刷新缓冲</b>），
主程序会实时解析并驱动画面、计数器与音效。</p>
<table cellpadding="4">
<tr><td><code>CMP i j</code></td><td>比较 <code>arr[i] &lt; arr[j]</code>（黄色高亮，比较 +1，读取 +2）</td></tr>
<tr><td><code>CMP_VAL i val</code></td><td>比较 <code>arr[i] &lt; val</code>（val 为寄存器/临时变量，读取 +1）</td></tr>
<tr><td><code>READ i</code></td><td>读取 arr[i] 到寄存器（读取 +1，访问 +1）</td></tr>
<tr><td><code>SWAP i j</code></td><td>交换两个元素（珊瑚红高亮，交换 +1，主存写 +2，访问 +4）</td></tr>
<tr><td><code>SET i val</code></td><td>覆写 <code>arr[i] = val</code>（主存写 +1）</td></tr>
<tr><td><code>FLIP l r</code></td><td>原地翻转区间 [l, r]（煎饼排序 / 块旋转专用）</td></tr>
<tr><td><code>AUX_INIT size</code></td><td>初始化辅助数组（画布自动切成上下分屏）</td></tr>
<tr><td><code>AUX_SET i val</code></td><td>写辅助数组（青色高亮，辅助写 +1）</td></tr>
<tr><td><code>AUX_GET i</code></td><td>读辅助数组（辅助读 +1）</td></tr>
<tr><td><code>AUX_SWAP i j</code></td><td>交换辅助数组两个位置</td></tr>
<tr><td><code>AUX_CMP i j</code></td><td>比较辅助数组两个位置（比较 +1）</td></tr>
<tr><td><code>AUX_CLEAR</code></td><td>销毁辅助数组并收起分屏</td></tr>
<tr><td><code>MARK i ROLE</code></td><td>标记索引，ROLE ∈ PIVOT / BOUNDARY / HEAP_ROOT / SORTED / CURSOR / MIN / MAX</td></tr>
<tr><td><code>CLEAR_MARKS</code></td><td>清除全部临时标记</td></tr>
<tr><td><code>MSG text...</code></td><td>更新看板上的实时解说词（可含空格）</td></tr>
</table>
<p><b>容错</b>：以 <code>#</code>、<code>;</code>、<code>//</code> 开头的行会被忽略；未知指令与越界索引会被
记入「无法识别」计数并跳过，不会写坏数据。指令总量受主程序的 max_ops 上限保护，
超时也会被强制结束——所以放开手写，不会把程序卡死。</p>
<p><b>辅助工具</b>：<code>DONE</code> / <code>END</code> 可提前结束指令流；
别名 <code>GT i j</code>（严格大于）、<code>SWP</code>、<code>ASSIGN</code>、<code>REV</code> 等也可用。</p>
"""


def mono_font(size: int = 10, bold: bool = False) -> QFont:
    """等宽字体（与主窗口保持同一套回退策略）。"""
    family = "Consolas"
    app = QApplication.instance()
    if app is not None:
        family = app.property("monoFamily") or family
    f = QFont(family, size)
    f.setStyleHint(QFont.Monospace)
    f.setBold(bold)
    return f


# ==========================================================================
# 1. 带行号的代码编辑器
# ==========================================================================
class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:                     # noqa: N802
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:             # noqa: N802
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """等宽代码编辑器：行号 + Tab 转 4 空格 + 自动缩进 + 当前行高亮。"""

    TAB_WIDTH = 4

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFont(mono_font(10))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabChangesFocus(False)
        self.setUndoRedoEnabled(True)

        self._gutter = LineNumberArea(self)
        self.blockCountChanged.connect(lambda _: self._refresh_gutter())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.setTabStopDistance(
            QFontMetricsF(self.font()).horizontalAdvance(" ") * self.TAB_WIDTH)
        self._refresh_gutter()
        self._highlight_current_line()

    # ---- 行号槽 ----------------------------------------------------------
    def line_number_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 12 + QFontMetricsF(self.font()).horizontalAdvance("9") * digits

    def _refresh_gutter(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._refresh_gutter()

    def resizeEvent(self, event) -> None:            # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(0x14, 0x16, 0x1C))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setFont(mono_font(9))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                current = (block.blockNumber() == self.textCursor().blockNumber())
                painter.setPen(QColor(0x6C, 0xD6, 0xFF) if current
                               else QColor(0x4A, 0x51, 0x60))
                painter.drawText(0, top, self._gutter.width() - 6,
                                 self.fontMetrics().height(),
                                 Qt.AlignRight | Qt.AlignVCenter, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ---- 当前行高亮 ------------------------------------------------------
    def _highlight_current_line(self) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(0x1B, 0x1F, 0x28))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    # ---- 键盘 ------------------------------------------------------------
    def keyPressEvent(self, event) -> None:          # noqa: N802
        key = event.key()
        if key == Qt.Key_Tab:
            self._indent_selection(1)
            return
        if key == Qt.Key_Backtab:
            self._indent_selection(-1)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._newline_with_indent()
            return
        super().keyPressEvent(event)

    def _indent_selection(self, direction: int) -> None:
        cursor = self.textCursor()
        pad = " " * self.TAB_WIDTH
        if not cursor.hasSelection():
            if direction > 0:
                cursor.insertText(pad)
            else:
                # 退格对齐到最近的制表位
                cur = cursor.positionInBlock()
                if cur == 0:
                    return
                back = min(self.TAB_WIDTH, cur % self.TAB_WIDTH or self.TAB_WIDTH)
                for _ in range(back):
                    cursor.deletePreviousChar()
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        first = cursor.blockNumber()
        cursor.setPosition(end)
        last = cursor.blockNumber()
        for line in range(first, last + 1):
            block = self.document().findBlockByNumber(line)
            if not block.isValid():
                continue
            c = QTextCursor(block)
            if direction > 0:
                c.insertText(pad)
            else:
                text = block.text()
                strip = len(text) - len(text.lstrip(" "))
                for _ in range(min(self.TAB_WIDTH, strip)):
                    c.deleteChar()
        cursor.endEditBlock()

    def _newline_with_indent(self) -> None:
        """回车继承当前缩进；上一行以 ``{`` / ``:`` 结尾时再多缩进一级。"""
        cursor = self.textCursor()
        text = cursor.block().text()
        indent = len(text) - len(text.lstrip(" "))
        stripped = text.rstrip()
        if stripped.endswith(("{", "(", "[")) or stripped.endswith(":"):
            indent += self.TAB_WIDTH
        cursor.insertText("\n" + " " * indent)
        self.ensureCursorVisible()

    # ---- 便捷操作 --------------------------------------------------------
    def set_text_smart(self, text: str) -> None:
        """写入模板并复位撤销栈与光标。"""
        self.setPlainText(text)
        self.document().setModified(False)
        self.moveCursor(QTextCursor.Start)

    def goto_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            cur = QTextCursor(block)
            self.setTextCursor(cur)
            self.centerCursor()

    @property
    def line_count(self) -> int:
        return self.blockCount()


# ==========================================================================
# 2. 后台编译 / 运行线程
# ==========================================================================
class EngineWorker(QThread):
    """把编译与运行放到后台，避免弹窗卡死。"""

    stage = Signal(str)              # 阶段提示
    done = Signal(object)            # RunOutcome
    failed = Signal(str)

    def __init__(self, lang: str, source: str, values: List[int],
                 mode: str = "run", timeout: float = DEFAULT_RUN_TIMEOUT,
                 max_ops: int = 4_000_000, parent=None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._source = source
        self._values = list(values)
        self._mode = mode            # "run" | "build"
        self._timeout = timeout
        self._max_ops = max_ops

    def run(self) -> None:                            # pragma: no cover
        try:
            if self._mode == "build":
                self.stage.emit("正在编译…")
                program = PolyglotProgram(self._lang, inline_source=self._source,
                                          display_name="custom")
                t0 = time.perf_counter()
                br: BuildResult = program.build()
                out = RunOutcome(lang=self._lang, program=program, build=br,
                                 elapsed=time.perf_counter() - t0)
                if not br.ok:
                    out.error = "编译未通过，请查看编译日志"
                self.done.emit(out)
                return
            self.stage.emit("正在编译…")
            outcome = run_source(self._lang, self._source, self._values,
                                 timeout=self._timeout, max_ops=self._max_ops)
            self.done.emit(outcome)
        except ToolchainMissing as exc:
            self.failed.emit(str(exc))
        except PolyglotError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # 兜底：绝不让线程崩掉进程
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ==========================================================================
# 2.5 工具链后台探测（守护线程 + 信号中继）
# ==========================================================================
# 8 种语言各要起一个 ``--version`` 子进程，串行加起来一两秒起步，冻结版叠上
# 杀毒扫描可以到十几秒。这段探测以前是在 GUI 线程里跑的，于是「打开自定义
# 算法工作室」等于把事件循环按住不动 —— 主窗口变灰、标题栏「未响应」、
# 屏幕上还会挨个闪出控制台黑框（每个子进程一个）。
#
# 现在：**缓存优先 + 守护线程探测 + 后台静默子进程**。
# 刻意不用 QThread：QThread 只要在 ``run()`` 还没返回时被销毁，Qt 就会
# ``qFatal("QThread: Destroyed while thread is still running")`` 直接带走
# 整个进程，而「打开工作室后 400 ms 内就关窗口 / 退程序」完全可能发生。
# 守护线程没有这个包袱 —— 进程退出时它随进程一起消失。
class _ProbeRelay(QObject):
    """探测结果的中继：守护线程 emit，Qt 自动排队投递到 GUI 线程执行。"""

    probed = Signal(dict)


_probe_guard = threading.Lock()
_probe_running = False
_probe_subs: List[Callable[[Dict[str, Toolchain]], None]] = []
_probe_relay: Optional[_ProbeRelay] = None


def _dispatch_probe(tc: dict) -> None:
    """在 GUI 线程里把探测结果派发给所有订阅者。"""
    with _probe_guard:
        subs = list(_probe_subs)
        _probe_subs.clear()
    for fn in subs:
        try:
            fn(tc)
        except Exception:
            # 对话框已经销毁 / 某个回调自己出错：绝不能连累别的窗口
            pass


def start_probe(callback: Optional[Callable[[Dict[str, Toolchain]], None]] = None) -> None:
    """在后台守护线程里探测工具链；结束时把结果交给 ``callback``。

    * 已经有一次探测在跑时，只登记回调、不重复起线程（主窗口预热与工作
      室打开很可能撞在一起，这样两者共用同一次探测）；
    * 回调在 GUI 线程执行，可以安全地改控件。
    """
    global _probe_running, _probe_relay
    with _probe_guard:
        if callback is not None:
            _probe_subs.append(callback)
        if _probe_running:
            return
        _probe_running = True
        if _probe_relay is None:
            _probe_relay = _ProbeRelay()
            _probe_relay.probed.connect(_dispatch_probe)

    def work() -> None:
        global _probe_running
        tc: Optional[Dict[str, Toolchain]] = None
        try:
            tc = detect_toolchains(force=True)
        except Exception:
            tc = None
        finally:
            with _probe_guard:
                _probe_running = False
        if tc is None:                       # 探测炸了 → 退回缓存，别让界面永远转圈
            tc = cached_toolchains() or {}
        relay = _probe_relay
        if relay is not None:
            relay.probed.emit(tc)

    threading.Thread(target=work, name="toolchain-probe", daemon=True).start()


def warm_toolchains() -> None:
    """在后台预热工具链缓存（主窗口启动后调用，界面完全无感）。

    不做这一步也能用 —— 只是「装好程序后第一次打开工作室」还得等一次探测。
    预热把结果落盘，之后再打开工作室就直接读缓存，瞬时显示。
    """
    start_probe()


# ==========================================================================
# 3. 自定义算法工作室
# ==========================================================================
class CustomAlgoDialog(QDialog):
    """多语言代码编辑器 + SDK 导出 + 一键编译运行的独立弹窗。"""

    algo_registered = Signal(str)      # 参数：注册成功的 algo_id

    PREVIEW_MAX_N = 512

    def __init__(self, parent: Optional[QWidget] = None,
                 start_lang: str = "python") -> None:
        super().__init__(parent)
        self.setWindowTitle("多语言自定义算法工作室 — Polyglot Custom Algorithm Studio")
        self.resize(1280, 840)
        self.setSizeGripEnabled(True)

        # 打开瞬间只读缓存（内存 → 磁盘，1 ms 级），绝不在这里起子进程。
        # 真正的探测交给 _kick_probe() 的后台线程，界面先画出来再慢慢变绿。
        self._toolchains: Dict[str, Toolchain] = cached_toolchains() or {}
        self._toolchain_pending = not self._toolchains
        self._outcome: Optional[RunOutcome] = None
        self._player = None
        self._worker: Optional[EngineWorker] = None
        self._current_path: Optional[Path] = None
        self._export_dir = default_export_dir()
        self._loading = False
        self._last_lang = "python"
        self._preview_values: List[int] = []

        self._build_ui()
        self._apply_toolchains(self._toolchains, pending=self._toolchain_pending)
        self._select_language(start_lang, ask=False)
        self._install_shortcuts()
        self._kick_probe()

    # ------------------------------------------------------------------
    # 3.1 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([760, 480])
        root.addWidget(split, 1)
        root.addWidget(self._build_buttons())

    # ---- 顶部：语言 / 档案 ---------------------------------------------
    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        lay.addWidget(QLabel("语言"))
        self.combo_lang = QComboBox()
        for spec in language_list():
            self.combo_lang.addItem(spec.name, spec.key)
        self.combo_lang.setFixedWidth(190)
        self.combo_lang.currentIndexChanged.connect(self._on_lang_changed)
        lay.addWidget(self.combo_lang)

        self.lbl_toolchain = QLabel("—")
        self.lbl_toolchain.setObjectName("AlgoSub")
        self.lbl_toolchain.setMinimumWidth(240)
        lay.addWidget(self.lbl_toolchain, 1)

        # 手动重新检测（后台线程，点了也不卡界面）
        self.btn_recheck = QToolButton()
        self.btn_recheck.setText("⟳")
        self.btn_recheck.setToolTip("重新检测本机工具链（后台进行，不会卡住界面）")
        self.btn_recheck.setCursor(Qt.PointingHandCursor)
        self.btn_recheck.clicked.connect(self._refresh_toolchains)
        lay.addWidget(self.btn_recheck)

        lay.addWidget(QLabel("中文名"))
        self.edit_name_zh = QLineEdit()
        self.edit_name_zh.setPlaceholderText("我的自定义排序")
        self.edit_name_zh.setFixedWidth(180)
        lay.addWidget(self.edit_name_zh)

        lay.addWidget(QLabel("英文名"))
        self.edit_name_en = QLineEdit()
        self.edit_name_en.setPlaceholderText("My Custom Sort")
        self.edit_name_en.setFixedWidth(180)
        lay.addWidget(self.edit_name_en)

        lay.addWidget(QLabel("预览 N"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(2, 10000)
        self.spin_n.setValue(64)
        self.spin_n.setFixedWidth(80)
        lay.addWidget(self.spin_n)

        lay.addWidget(QLabel("超时"))
        self.spin_timeout = QDoubleSpinBox()
        self.spin_timeout.setRange(1.0, 600.0)
        self.spin_timeout.setValue(DEFAULT_RUN_TIMEOUT)
        self.spin_timeout.setSuffix(" s")
        self.spin_timeout.setFixedWidth(86)
        lay.addWidget(self.spin_timeout)
        return bar

    # ---- 左：编辑器 + 日志 ---------------------------------------------
    def _build_left(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.editor = CodeEditor()
        self.editor.setPlaceholderText("在此编写你的排序算法…")
        self.editor.textChanged.connect(self._on_text_changed)

        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(200)
        self.log_build = QPlainTextEdit()
        self.log_build.setReadOnly(True)
        self.log_build.setFont(mono_font(9))
        self.log_build.setPlaceholderText("编译日志会显示在这里…")
        self.tabs.addTab(self.log_build, "编译日志")

        self.log_stats = QPlainTextEdit()
        self.log_stats.setReadOnly(True)
        self.log_stats.setFont(mono_font(9))
        self.log_stats.setPlaceholderText("运行统计会显示在这里…")
        self.tabs.addTab(self.log_stats, "运行统计")

        self.txt_help = QTextBrowser()
        self.txt_help.setHtml(PROTOCOL_HELP)
        self.txt_help.setFont(mono_font(9))
        self.tabs.addTab(self.txt_help, "协议说明")

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(self.editor)
        vsplit.addWidget(self.tabs)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([460, 260])
        lay.addWidget(vsplit, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.lbl_file = QLabel("未保存")
        self.lbl_file.setObjectName("AlgoSub")
        row.addWidget(self.lbl_file, 1)
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("AlgoSub")
        row.addWidget(self.lbl_status)
        lay.addLayout(row)
        return box

    # ---- 右：预览 -------------------------------------------------------
    def _build_right(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QLabel("实时预览（与主窗口同一套渲染内核）")
        head.setObjectName("Section")
        lay.addWidget(head)

        holder = QFrame()
        holder.setObjectName("Panel")
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(8, 8, 8, 8)
        hl.setSpacing(6)
        self.preview = CanvasWidget(style="bars")
        self.preview.set_placeholder("点击「编译并运行」后在此预览")
        hl.addWidget(self.preview, 1)

        self.bar_steps = QSlider(Qt.Horizontal)
        self.bar_steps.setRange(0, 0)
        self.bar_steps.setCursor(Qt.PointingHandCursor)
        self.bar_steps.valueChanged.connect(self._render_preview)
        hl.addWidget(self.bar_steps)

        row = QHBoxLayout()
        self.btn_preview_play = QToolButton()
        self.btn_preview_play.setText("▶ 自动回放")
        self.btn_preview_play.setCursor(Qt.PointingHandCursor)
        self.btn_preview_play.clicked.connect(self._toggle_autoplay)
        row.addWidget(self.btn_preview_play)
        self.lbl_progress = QLabel("步 0 / 0")
        self.lbl_progress.setFont(mono_font(9))
        row.addWidget(self.lbl_progress, 1)
        self.chk_show_aux = QCheckBox("辅助分屏")
        self.chk_show_aux.setChecked(True)
        self.chk_show_aux.toggled.connect(
            lambda _: self._render_preview(self.bar_steps.value()))
        row.addWidget(self.chk_show_aux)
        hl.addLayout(row)

        lay.addWidget(holder, 1)

        # 预览自动回放计时器
        from PySide6.QtCore import QTimer
        self._auto = QTimer(self)
        self._auto.setInterval(16)
        self._auto.timeout.connect(self._autoplay_tick)

        info = QFrame()
        info.setObjectName("Panel")
        il = QVBoxLayout(info)
        il.setContentsMargins(10, 8, 10, 8)
        il.setSpacing(4)
        self.lbl_cmd = QLabel("—")
        self.lbl_cmd.setFont(mono_font(8))
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        il.addWidget(self.lbl_cmd)
        lay.addWidget(info)
        return box

    # ---- 底部按钮 -------------------------------------------------------
    def _build_buttons(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        self.btn_export = QPushButton("⤓ 导出 7 语言模板")
        self.btn_export.setToolTip("把 sdk_templates/ 里的全部语言模板复制到 "
                                   "custom_algorithms/，改完即可编译")
        self.btn_export.clicked.connect(self._export_templates)

        self.btn_open = QPushButton("打开文件…")
        self.btn_open.clicked.connect(self._open_file)
        self.btn_save = QPushButton("另存为…")
        self.btn_save.clicked.connect(self._save_as)
        self.btn_reload = QPushButton("↺ 重载模板")
        self.btn_reload.clicked.connect(lambda: self._load_template(force=True))

        self.btn_build = QPushButton("仅编译")
        self.btn_build.setToolTip("只跑编译器，不执行程序（Ctrl+B）")
        self.btn_build.clicked.connect(lambda: self._start(mode="build"))

        self.btn_run = QPushButton("▶ 编译并运行")
        self.btn_run.setObjectName("Accent")
        self.btn_run.setToolTip("编译并在预览数据上跑一遍（Ctrl+R）")
        self.btn_run.clicked.connect(lambda: self._start(mode="run"))

        self.btn_register = QPushButton("＋ 加入算法库")
        self.btn_register.setObjectName("Accent")
        self.btn_register.setToolTip("注册后可在主窗口算法树里直接可视化与赛马")
        self.btn_register.clicked.connect(self._register)

        self.btn_unregister = QPushButton("移出算法库")
        self.btn_unregister.clicked.connect(self._unregister)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)

        for b in (self.btn_export, self.btn_open, self.btn_save, self.btn_reload):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        lay.addStretch(1)
        for b in (self.btn_build, self.btn_run, self.btn_register,
                  self.btn_unregister, self.btn_close):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        return bar

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self._start("build"))
        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._start("run"))
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_as)

    # ------------------------------------------------------------------
    # 3.2 工具链与语言
    # ------------------------------------------------------------------
    def _kick_probe(self) -> None:
        """起一个后台守护线程重探工具链，探测期间界面照常可用。"""
        start_probe(self._on_probed)

    def _on_probed(self, tc: dict) -> None:
        """后台探测完成：刷新下拉框标记 + 当前语言的按钮状态 + 命令预览。"""
        self._toolchain_pending = False
        self._apply_toolchains(tc)
        self._sync_lang_state()
        self._update_cmd_line()

    def _apply_toolchains(self, tc: Dict[str, Toolchain],
                          pending: bool = False) -> None:
        """把探测结果写成下拉框前缀（● 就绪 / ○ 未装 / … 检测中）。"""
        self._toolchains = dict(tc)
        self._toolchain_pending = pending
        for i in range(self.combo_lang.count()):
            key = self.combo_lang.itemData(i)
            spec = language_spec(key)
            row = self._toolchains.get(key)
            mark = "…" if (row is None and pending) else (
                "●" if (row and row.available) else "○")
            self.combo_lang.setItemText(i, f"{mark} {spec.name}")

    def _refresh_toolchains(self) -> None:
        """手动重新检测（非阻塞）。"""
        self._apply_toolchains(self._toolchains, pending=True)
        self._sync_lang_state()
        self._kick_probe()

    def _cur_lang(self) -> str:
        return self.combo_lang.currentData() or "python"

    def _on_lang_changed(self, idx: int) -> None:
        """切换语言：代码有未保存改动时先问一句，用户拒绝就回滚下拉框。"""
        key = self.combo_lang.itemData(idx) or "python"
        if self.editor.document().isModified() and key != self._last_lang:
            r = QMessageBox.question(
                self, "切换语言",
                "当前代码尚未保存，切换语言会载入新的模板，确定继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                prev = next((i for i in range(self.combo_lang.count())
                             if self.combo_lang.itemData(i) == self._last_lang), 0)
                self.combo_lang.blockSignals(True)
                self.combo_lang.setCurrentIndex(prev)
                self.combo_lang.blockSignals(False)
                return
        self._select_language(key, ask=False)

    def _select_language(self, lang: str, ask: bool = True) -> None:
        key = (lang or "python").lower()
        idx = next((i for i in range(self.combo_lang.count())
                    if self.combo_lang.itemData(i) == key), 0)
        if self.combo_lang.currentIndex() != idx:
            self.combo_lang.blockSignals(True)
            self.combo_lang.setCurrentIndex(idx)
            self.combo_lang.blockSignals(False)
        key = self.combo_lang.itemData(idx)
        self._last_lang = key
        self._sync_lang_state()
        self._load_template(force=True)
        self._update_cmd_line()

    def _sync_lang_state(self) -> None:
        """按当前语言的工具链状态刷新提示文字与三个按钮（不动编辑器内容）。

        和 :meth:`_select_language` 拆开，是因为后台探测回来时要单独调它 ——
        那时绝对不能再走一遍 ``_load_template(force=True)``，否则会把用户已经
        写了一半的代码冲掉。
        """
        key = self._cur_lang()
        row = self._toolchains.get(key)
        if row is None and self._toolchain_pending:
            self.lbl_toolchain.setText("… 正在后台检测工具链（不影响先写代码）")
        elif row is None:
            self.lbl_toolchain.setText("○ 尚未检测到工具链 —— 请稍候或重新打开本窗口")
        elif row.available:
            self.lbl_toolchain.setText(f"● 工具链就绪：{row.describe()}")
        else:
            hint = INSTALL_HINTS.get(key, "请安装对应工具链并加入 PATH")
            self.lbl_toolchain.setText(f"○ 未检测到工具链 —— {hint}")

        ready = bool(row and row.available)
        for b in (self.btn_build, self.btn_run, self.btn_register):
            b.setEnabled(ready)
        self.btn_unregister.setEnabled(_has_custom())

    def _load_template(self, force: bool = False) -> None:
        key = self._cur_lang()
        if not force and self.editor.toPlainText().strip():
            return
        try:
            src = template_source(key)
        except PolyglotError as exc:
            self.log_build.setPlainText(str(exc))
            return
        self._loading = True
        self.editor.set_text_smart(src)
        self._loading = False
        self._current_path = None
        self.lbl_file.setText(f"未保存 · 模板 {language_spec(key).template}")
        self.log_build.setPlainText(
            f"已载入 {language_spec(key).name} 模板（{self.editor.line_count} 行）。\n"
            "模板里内置了一个可跑通的插入排序示例，改掉 my_custom_sort / "
            "myCustomSort / MyCustomSort 的函数体即可。")
        self._update_cmd_line()

    def _update_cmd_line(self) -> None:
        if self._toolchain_pending:
            self.lbl_cmd.setText("（正在后台检测工具链，检测完成后自动填充命令…）")
            return
        try:
            program = PolyglotProgram(self._cur_lang(),
                                     inline_source=self.editor.toPlainText(),
                                     display_name="preview")
            comp, run = program.command_lines()
            self.lbl_cmd.setText(f"编译：{comp}\n运行：{run}")
            self.lbl_cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        except Exception as exc:
            self.lbl_cmd.setText(f"（命令预览不可用：{exc}）")

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        n = self.editor.line_count
        name = self._current_path.name if self._current_path else "未保存"
        self.lbl_file.setText(f"{name}    {n} 行    ● 已修改")

    # ------------------------------------------------------------------
    # 3.3 文件操作
    # ------------------------------------------------------------------
    def _export_templates(self) -> None:
        try:
            paths = export_all_templates(self._export_dir)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        lines = [f"已导出 {len(paths)} 个语言模板到：", str(self._export_dir), ""]
        lines += [f"  {p.name}" for p in paths]
        lines += ["", "提示：把模板复制到工作目录改完，用「打开文件…」载入",
                  "再点「编译并运行」，最后「加入算法库」即可长期使用。"]
        self.log_build.setPlainText("\n".join(lines))
        self.tabs.setCurrentWidget(self.log_build)
        self.lbl_status.setText(f"已导出 {len(paths)} 个模板")

    def _open_file(self) -> None:
        key = self._cur_lang()
        spec = language_spec(key)
        filt = f"{spec.name} (*{spec.suffix});;所有文件 (*.*)"
        start = str(self._export_dir if self._export_dir.is_dir() else Path.cwd())
        path, _ = QFileDialog.getOpenFileName(self, "打开自定义算法源码", start, filt)
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self._loading = True
        self.editor.set_text_smart(text)
        self._loading = False
        self._current_path = Path(path)
        self.lbl_file.setText(f"{self._current_path.name}    {self.editor.line_count} 行")
        self.lbl_status.setText("已载入源文件")
        self.log_build.setPlainText(f"已载入 {path}")
        self._update_cmd_line()

    def _save_as(self) -> bool:
        key = self._cur_lang()
        spec = language_spec(key)
        default_name = (self._current_path.name if self._current_path
                        else Path(_default_stem(self.edit_name_en.text(),
                                                self.edit_name_zh.text())
                                  + spec.suffix).name)
        start = str(self._export_dir / default_name)
        self._export_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "保存自定义算法源码",
                                             start, f"{spec.name} (*{spec.suffix})")
        if not path:
            return False
        try:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self._current_path = Path(path)
        self.editor.document().setModified(False)
        self.lbl_file.setText(f"{self._current_path.name}    {self.editor.line_count} 行")
        self.lbl_status.setText(f"已保存到 {path}")
        self._warn_class_name_mismatch(key)
        self._update_cmd_line()
        return True

    def _warn_class_name_mismatch(self, key: str) -> None:
        """Java 的 public 类名必须与文件名一致——不一致时提醒一句。

        程序编译时会自动在缓存里投一份「类名.java」对齐，所以不影响在本软件里
        使用；但用户若自己去命令行跑 javac，就会撞上这条晦涩的规则。
        """
        if key != "java" or self._current_path is None:
            return
        cls = main_class_name(self.editor.toPlainText(), "java",
                              self._current_path.stem)
        if cls != self._current_path.stem:
            self.log_build.setPlainText(
                f"提示：文件名是 {self._current_path.name}，而源码里声明的是 "
                f"public class {cls}。\n"
                f"javac 要求两者同名——本软件编译时会自动对齐，"
                f"但手工执行 javac 时请把文件改名为 {cls}.java。")

    # ------------------------------------------------------------------
    # 3.4 编译 / 运行
    # ------------------------------------------------------------------
    def _start(self, mode: str = "run") -> None:
        key = self._cur_lang()
        tc = self._toolchains.get(key)
        if not (tc and tc.available):
            QMessageBox.information(
                self, "工具链不可用",
                f"{language_spec(key).name} 的编译器/解释器没有找到。\n\n"
                f"{INSTALL_HINTS.get(key, '请安装对应工具链并加入 PATH')}")
            return
        if self._worker is not None and self._worker.isRunning():
            self.lbl_status.setText("上一次编译/运行还没结束…")
            return

        source = self.editor.toPlainText()
        if not source.strip():
            QMessageBox.information(self, "源码为空", "请先编写或载入一段代码。")
            return
        n = min(int(self.spin_n.value()), self.PREVIEW_MAX_N)
        # 预览数据只生成一次，运行与预览必须用同一份，否则画面与统计对不上
        self._preview_values = generate("random", max(2, n), seed=20261016)
        values = self._preview_values
        self._auto.stop()
        self._outcome = None
        self._player = None
        self.lbl_status.setText("编译中…")
        self.btn_build.setEnabled(False)
        self.btn_run.setEnabled(False)

        self._worker = EngineWorker(key, source, values, mode=mode,
                                   timeout=float(self.spin_timeout.value()),
                                   parent=self)
        self._worker.stage.connect(self.lbl_status.setText)
        self._worker.done.connect(self._on_engine_done)
        self._worker.failed.connect(self._on_engine_failed)
        self._worker.start()

    def _on_engine_done(self, outcome: RunOutcome) -> None:
        self._outcome = outcome
        self._sync_lang_state()          # 别硬置 True：工具链不可用时要保持置灰
        self.log_build.setPlainText(outcome.build.log(_safe_run_argv(outcome))
                                   if outcome.build else "（无编译信息）")
        if outcome.stats.ops or outcome.stats.lines or outcome.stats.stderr.strip():
            self.log_stats.setPlainText(outcome.stats.detail())
        if outcome.error:
            self.lbl_status.setText("✗ " + outcome.error)
            self.tabs.setCurrentWidget(self.log_build)
        else:
            self.lbl_status.setText(
                f"✓ {outcome.ops:,} 条指令，"
                f"{'已排好序' if outcome.stats.sorted_ok else '尚未排好序'}"
                f"，耗时 {outcome.stats.elapsed * 1000:.0f} ms")
        self._bind_preview(outcome)

    def _on_engine_failed(self, msg: str) -> None:
        self._sync_lang_state()
        self.lbl_status.setText("✗ " + msg)
        self.log_build.setPlainText(msg)
        self.tabs.setCurrentWidget(self.log_build)

    # ------------------------------------------------------------------
    # 3.5 预览
    # ------------------------------------------------------------------
    def _bind_preview(self, outcome: RunOutcome) -> None:
        from core.protocol import TracePlayer        # 局部导入，避免顶部膨胀

        trace = outcome.trace
        if trace is None or trace.n_ops == 0:
            self.preview.set_placeholder("没有产生任何指令，检查程序是否读取了 stdin")
            self.bar_steps.setRange(0, 0)
            self.lbl_progress.setText("步 0 / 0")
            return
        values = self._preview_values or generate(
            "random", max(2, min(int(self.spin_n.value()), self.PREVIEW_MAX_N)),
            seed=20261016)
        self._player = TracePlayer(trace, values)
        self.bar_steps.setRange(0, trace.n_ops)
        self.bar_steps.setValue(trace.n_ops)
        if outcome.stats.ops:
            self.bar_steps.setValue(min(trace.n_ops, outcome.stats.ops))
        self.bar_steps.setValue(0)
        self._render_preview(0)
        self.preview.set_show_labels(True)

    def _render_preview(self, step: int) -> None:
        if self._player is None or self._outcome is None:
            return
        trace = self._outcome.trace
        self._player.seek(int(step))
        p = self._player
        hot, hot_aux = _hot_of(trace, p.step)
        aux = p.aux if self.chk_show_aux.isChecked() else []
        frame = VizFrame(values=p.data, aux=aux,
                         aux_active=bool(aux) and p.aux_active,
                         marks=p.marks if self.chk_show_aux.isChecked() else {},
                         hot=hot, hot_aux=hot_aux,
                         n_max=max(1, max(p.data) if p.data else 1),
                         palette="white",
                         sweep=1.0 if p.at_end() else 0.0)
        self.preview.set_frame(frame)
        self.lbl_progress.setText(f"步 {p.step:,} / {p.total:,}　"
                                  f"CMP {p.cmp:,}　SWP {p.swaps:,}　"
                                  f"访问 {p.accesses:,}")

    def _toggle_autoplay(self) -> None:
        if self._auto.isActive():
            self._auto.stop()
            self.btn_preview_play.setText("▶ 自动回放")
            return
        if self._player is None or self._player.total <= 0:
            return
        if self._player.at_end():
            self.bar_steps.setValue(0)
        self._auto.start()
        self.btn_preview_play.setText("⏸ 暂停回放")

    def _autoplay_tick(self) -> None:
        if self._player is None:
            self._auto.stop()
            return
        total = self._player.total
        step = min(total, self.bar_steps.value() + max(1, total // 300))
        self.bar_steps.setValue(step)
        if step >= total:
            self._auto.stop()
            self.btn_preview_play.setText("▶ 自动回放")

    # ------------------------------------------------------------------
    # 3.6 加入 / 移出算法库
    # ------------------------------------------------------------------
    def _register(self) -> None:
        key = self._cur_lang()
        tc = self._toolchains.get(key)
        if not (tc and tc.available):
            QMessageBox.information(self, "工具链不可用",
                                    INSTALL_HINTS.get(key, "请先安装工具链"))
            return
        name_zh = self.edit_name_zh.text().strip()
        name_en = self.edit_name_en.text().strip()
        if not name_zh and not name_en:
            QMessageBox.information(
                self, "需要名称",
                "请至少填写中文名或英文名，它会显示在左侧算法树里。")
            return

        # 注册需要一份稳定落盘的源码，避免清单里记着一个临时文件
        if self._current_path is None or not Path(self._current_path).is_file():
            if not self._save_as():
                return
        else:
            try:
                Path(self._current_path).write_text(self.editor.toPlainText(),
                                                    encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(self, "写回源码失败", str(exc))
                return

        try:
            meta = register_custom(
                key, source_path=self._current_path,
                name_zh=name_zh or f"自定义 {language_spec(key).name}",
                name_en=name_en or f"Custom {language_spec(key).name}",
                desc=f"外部 {language_spec(key).name} 实现，源码：{self._current_path.name}",
                timeout=float(self.spin_timeout.value()))
        except ToolchainMissing as exc:
            QMessageBox.warning(self, "工具链不可用", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "注册失败", f"{type(exc).__name__}: {exc}")
            return

        self.lbl_status.setText(f"✓ 已加入算法库：{meta.algo_id}")
        self.log_stats.appendPlainText(
            f"\n已注册为 {meta.algo_id}（类别 {meta.category}）\n"
            f"源码：{self._current_path}")
        self.algo_registered.emit(meta.algo_id)
        self.btn_unregister.setEnabled(True)
        QMessageBox.information(
            self, "已加入算法库",
            f"{meta.name_zh}（序号 #{meta.index}）已注册。\n\n"
            "回到主窗口即可在左侧算法树「99. 外部自定义算法」下找到它，\n"
            "支持播放、单步、音效、四宫格赛马与视频导出。")

    def _unregister(self) -> None:
        from core.registry import REGISTRY
        customs = [(a, m) for a, m in REGISTRY.items() if m.external]
        if not customs:
            QMessageBox.information(self, "没有可移除的算法",
                                    "当前算法库里还没有外部自定义算法。")
            return
        items = "\n".join(f"  #{m.index:03d}  {m.name_zh}" for _, m in customs)
        r = QMessageBox.question(
            self, "移出算法库",
            f"将从算法库与清单里移除以下 {len(customs)} 个自定义算法：\n\n{items}\n\n"
            "（源码文件不会被删除）确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        for aid, _ in customs:
            unregister_custom(aid)
        self.btn_unregister.setEnabled(False)
        self.lbl_status.setText(f"已移出 {len(customs)} 个自定义算法")
        self.algo_registered.emit("")

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:              # noqa: N802
        try:
            self._auto.stop()
            if self._worker is not None and self._worker.isRunning():
                self._worker.wait(3000)
        finally:
            event.accept()


# ==========================================================================
# 4. 小工具
# ==========================================================================
def _default_stem(name_en: str, name_zh: str) -> str:
    base = (name_en or name_zh or "my_custom_sort").strip()
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in base)
    out = out.strip("_").lower() or "my_custom_sort"
    return out[:48]


def _has_custom() -> bool:
    from core.registry import REGISTRY
    return any(m.external for m in REGISTRY.values())


def _safe_run_argv(outcome: RunOutcome) -> Optional[List[str]]:
    if outcome.program is None:
        return None
    try:
        return outcome.program.run_argv()
    except Exception:
        return None


def _hot_of(trace, step: int) -> Tuple[Dict[int, str], Dict[int, str]]:
    """复用主窗口的高亮提取逻辑（局部导入以避开循环依赖）。"""
    from ui.main_window import extract_hot
    return extract_hot(trace, step)
