# -*- coding: utf-8 -*-
"""按需读取算法源码（「查看源码」按钮背后的唯一数据入口）。

为什么单独一个模块
------------------
* **源码不常驻界面**：主窗口只挂一个按钮，用户点下去才触发磁盘读取 + AST
  解析；既不把 160 份实现塞进界面，也不拖慢启动。
* **开发态 / 冻结态统一**：开发态直接读 ``algorithms/catXX.py``；PyInstaller
  打包后 ``.py`` 已被编译进包体，``inspect.getsource`` 失效，于是
  ``build_exe.py`` 把 ``algorithms/`` 当作**纯数据**再带一份到
  ``_internal/algorithms_src/``，本模块按「inspect → 冻结目录 → 项目目录」
  的顺序回退，两条路径拿到的是同一份文本。
* **只展示算法本体**：用 ``ast`` 精确定位函数（连 ``@register_algo`` 装饰器
  一起），再把同文件 / ``_util.py`` 里**被它调用**的辅助函数附在末尾 ——
  读者不会看到 ``insertion_sort_range(...)`` 却不知道它做了什么。

对外只有 :func:`resolve_source` 与 :func:`source_ready`：

>>> from core.algo_source import resolve_source
>>> resolve_source(REGISTRY["001_bubble_sort"]).code.splitlines()[0]
'@register_algo('

这个模块**不 import Qt**，可以脱离界面单测。
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = [
    "SourceBundle", "SourceUnavailable", "resolve_source", "source_ready",
    "lang_label", "FROZEN_SOURCE_DIR",
]

#: 冻结包内的算法源码数据目录名，必须与 ``build_exe.py`` 的 ``--add-data`` 一致
FROZEN_SOURCE_DIR = "algorithms_src"

#: 单个算法最多附带几个辅助函数（够用即可，避免整份文件倒出来）
_MAX_HELPERS = 3

#: 语言 key → 展示名
_LANG_LABELS = {
    "python": "Python", "py": "Python",
    "cpp": "C++", "cxx": "C++",
    "c": "C",
    "java": "Java",
    "rust": "Rust", "rs": "Rust",
    "go": "Go",
    "js": "JavaScript", "javascript": "JavaScript",
    "cs": "C#", "csharp": "C#",
}


def lang_label(lang: str) -> str:
    """``python`` → ``Python``；未知语言原样返回。"""
    key = (lang or "").strip().lower()
    return _LANG_LABELS.get(key, lang or "未知")


class SourceUnavailable(RuntimeError):
    """源码取不到（文件被删 / 冻结包里缺数据 / 模块里找不到该函数）。"""


@dataclass(frozen=True)
class SourceBundle:
    """一份可直接丢给代码视图的源码快照。"""

    algo_id: str
    index: int
    name_zh: str
    name_en: str
    lang: str
    code: str                     # 算法本体（含装饰器 + 附带的辅助函数）
    origin: str                   # 人类可读的来源说明
    whole: str = ""               # 整个模块的原文（「整文件视图」用）
    summary: str = ""             # 类别 / 复杂度 / 稳定性 一行摘要
    path: Optional[Path] = None
    lineno: int = 0               # 算法在文件中的起始行（1 基）

    @property
    def line_count(self) -> int:
        return self.code.count("\n") + 1

    @property
    def char_count(self) -> int:
        return len(self.code)

    @property
    def filename(self) -> str:
        """另存为时的默认文件名。"""
        if self.path is not None:
            return self.path.name
        ext = {"python": "py", "c": "c", "cpp": "cpp", "java": "java",
               "rust": "rs", "go": "go", "js": "js", "cs": "cs"}.get(self.lang, "txt")
        return f"{self.algo_id}.{ext}"


# --------------------------------------------------------------------------
# 路径解析
# --------------------------------------------------------------------------
def _project_root() -> Optional[Path]:
    """开发态的项目根（``core/`` 的上一级，且必须有 ``algorithms/``）。"""
    cand = Path(__file__).resolve().parent.parent
    return cand if (cand / "algorithms").is_dir() else None


def _frozen_root() -> Optional[Path]:
    """PyInstaller 的解包目录（onedir 下是 ``_internal/``）。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if isinstance(base, (str, bytes)) and base else None


def _module_leaf(func) -> str:
    """``algorithms.cat01_exchange`` → ``cat01_exchange``。"""
    return (getattr(func, "__module__", "") or "").rsplit(".", 1)[-1]


def _source_candidates(leaf: str) -> List[Path]:
    """算法的源文件可能所在的位置，按优先级排列。"""
    out: List[Path] = []
    frozen = _frozen_root()
    if frozen is not None:
        out.append(frozen / FROZEN_SOURCE_DIR / f"{leaf}.py")
    root = _project_root()
    if root is not None:
        out.append(root / "algorithms" / f"{leaf}.py")
    return out


#: 模块缓存：``路径 → (mtime_ns, 原文, AST)``。
#: 用 mtime 做键的一部分，开发者边改 ``algorithms/*.py`` 边看源码时不会读到旧快照。
_MODULE_CACHE: Dict[str, Tuple[int, str, ast.Module]] = {}


def _load_module(path_str: str) -> Tuple[str, ast.Module]:
    """读 + 解析一个模块（按 mtime 缓存：160 个算法只摊到 13 个文件）。"""
    path = Path(path_str)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    hit = _MODULE_CACHE.get(path_str)
    if hit is not None and hit[0] == mtime:
        return hit[1], hit[2]
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    _MODULE_CACHE[path_str] = (mtime, text, tree)
    return text, tree


# --------------------------------------------------------------------------
# AST 切块
# --------------------------------------------------------------------------
def _span(node: ast.AST) -> Tuple[int, int]:
    """节点覆盖的行区间（含装饰器），1 基、闭区间。"""
    starts = [int(getattr(node, "lineno", 1))]
    starts += [int(d.lineno) for d in getattr(node, "decorator_list", [])]
    return min(starts), int(getattr(node, "end_lineno", starts[0]) or starts[0])


def _block(text: str, node: ast.AST) -> str:
    """从模块原文里切出节点对应的代码块。"""
    lines = text.splitlines()
    start, end = _span(node)
    return "\n".join(lines[start - 1:end]).rstrip()


def _find_func(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _module_defs(tree: ast.Module) -> Dict[str, ast.AST]:
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_names(node: ast.AST) -> List[str]:
    """按出现顺序收集 ``f(...)`` 形式调用的函数名（``arr.swap(...)`` 不算）。"""
    out: List[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            if sub.func.id not in out:
                out.append(sub.func.id)
    return out


def _util_pair(src_path: Path) -> Optional[Tuple[str, ast.Module]]:
    """同目录的 ``algorithms/_util.py``（公共辅助函数都在这儿）。"""
    if src_path.parent.name != "algorithms":
        return None
    util = src_path.parent / "_util.py"
    if not util.is_file():
        return None
    try:
        return _load_module(str(util))
    except (OSError, SyntaxError):
        return None


def _helper_sources(func_name: str, node: ast.AST, text: str, tree: ast.Module,
                    util: Optional[Tuple[str, ast.Module]]) -> List[Tuple[str, str]]:
    """广度优先找出被调用的辅助函数，最多 :data:`_MAX_HELPERS` 个。"""
    pools: List[Tuple[str, Dict[str, ast.AST]]] = [(text, _module_defs(tree))]
    if util is not None:
        pools.append((util[0], _module_defs(util[1])))

    picked: List[Tuple[str, str]] = []
    seen = {func_name}
    queue = _called_names(node)
    while queue and len(picked) < _MAX_HELPERS:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        for pool_text, defs in pools:
            found = defs.get(cur)
            if found is not None:
                picked.append((cur, _block(pool_text, found)))
                queue.extend(_called_names(found))
                break
    return picked


# --------------------------------------------------------------------------
# 外部（多语言）算法
# --------------------------------------------------------------------------
def _external_path(meta) -> Optional[Path]:
    """外部算法的源码文件：先看注册时存进 ``extra`` 的路径，再回退到清单。"""
    raw = (getattr(meta, "extra", None) or {}).get("source_path")
    if raw:
        p = Path(str(raw))
        if p.is_file():
            return p
    try:
        from core.polyglot_runner import load_manifest
        for rec in load_manifest():
            if str(rec.get("algo_id", "")) == getattr(meta, "algo_id", ""):
                q = str(rec.get("path", ""))
                if q and Path(q).is_file():
                    return Path(q)
    except Exception:                                 # 清单损坏不影响查看其它算法
        pass
    return None


def _summary(meta) -> str:
    bits = [meta.category]
    if meta.time_avg and meta.time_avg != "?":
        bits.append(f"{meta.time_best} → {meta.time_avg} → {meta.time_worst}")
    if meta.space and meta.space != "?":
        bits.append(f"空间 {meta.space}")
    bits.append("Stable" if meta.stable else "Unstable")
    return " · ".join(bits)


def _resolve_external(meta) -> SourceBundle:
    path = _external_path(meta)
    if path is None:
        raise SourceUnavailable(
            f"#{meta.index:03d} 是外部 {lang_label(meta.source_lang)} 算法，"
            "但它的源码文件已经不在注册时记录的路径上了。\n\n"
            "常见原因：源码被移动或删除、算法库清单是从别的机器拷过来的。\n"
            "重新在「⌨ 自定义算法」里导入一次即可恢复。")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SourceUnavailable(f"读取源码失败：{exc}") from exc
    return SourceBundle(
        algo_id=meta.algo_id, index=meta.index,
        name_zh=meta.name_zh, name_en=meta.name_en,
        lang=meta.source_lang, code=text,
        origin=f"外部 · {path}",
        whole=text, summary=_summary(meta), path=path, lineno=1)


# --------------------------------------------------------------------------
# 内置算法
# --------------------------------------------------------------------------
def _builtin_source_file(meta) -> Optional[Path]:
    fn = meta.func
    try:
        f = inspect.getsourcefile(fn)
    except (TypeError, OSError):
        f = None
    if f and Path(f).is_file():
        return Path(f)
    for cand in _source_candidates(_module_leaf(fn)):
        if cand.is_file():
            return cand
    return None


def _resolve_builtin(meta) -> SourceBundle:
    path = _builtin_source_file(meta)
    leaf = _module_leaf(meta.func) or "?"
    if path is None:
        raise SourceUnavailable(
            f"找不到 #{meta.index:03d} 的源文件（模块 algorithms.{leaf}）。\n\n"
            "如果这是打包版，说明构建时漏了 algorithms_src 数据目录；\n"
            "请重新运行 build_exe.py 打包。")
    try:
        text, tree = _load_module(str(path))
    except (OSError, SyntaxError) as exc:
        raise SourceUnavailable(f"解析源码失败（{path.name}）：{exc}") from exc

    name = getattr(meta.func, "__name__", "")
    node = _find_func(tree, name)
    if node is None:
        raise SourceUnavailable(
            f"{path.name} 里找不到函数 {name}()，源码可能已经改过。")

    code = _block(text, node)
    helpers = _helper_sources(name, node, text, tree, _util_pair(path))
    if helpers:
        code += ("\n\n\n# " + "─" * 66 +
                 "\n# 下面这些辅助函数被上面的算法调用"
                 "（同文件 / algorithms/_util.py）\n# " + "─" * 66)
        for hname, hsrc in helpers:
            code += f"\n\n# --- {hname} " + "-" * max(0, 56 - len(hname)) + "\n" + hsrc

    rel = path
    root = _project_root()
    if root is not None:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
    start, _end = _span(node)
    return SourceBundle(
        algo_id=meta.algo_id, index=meta.index,
        name_zh=meta.name_zh, name_en=meta.name_en,
        lang="python", code=code,
        origin=f"内置 · {rel} 第 {start} 行",
        whole=text, summary=_summary(meta), path=path, lineno=start)


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def resolve_source(meta) -> SourceBundle:
    """取出一条算法的源码快照；取不到抛 :class:`SourceUnavailable`。"""
    if meta is None:
        raise SourceUnavailable("没有选中算法。")
    if getattr(meta, "external", False):
        return _resolve_external(meta)
    return _resolve_builtin(meta)


def source_ready(meta) -> bool:
    """轻量探测：这条算法现在点「查看源码」能不能拿到东西。"""
    if meta is None:
        return False
    try:
        if getattr(meta, "external", False):
            return _external_path(meta) is not None
        return _builtin_source_file(meta) is not None
    except Exception:                                 # noqa: BLE001 - 探测永不抛
        return False
