# -*- coding: utf-8 -*-
"""外部多语言自定义算法引擎（Polyglot Custom Algorithm Engine）。

设计要点
--------
1. **零侵入的指令协议**：主程序只做两件事——把 ``N`` 与初始数组写进子进程 stdin；
   然后逐行读回 stdout 的文本指令（``CMP 0 1``、``SWAP 2 5``、``SET 3 45``、
   ``MSG 正在分区`` …）。子进程不需要链接任何库，也不需要知道可视化的存在。
2. **翻译而非模拟**：读回的每一行都会被翻译成 :class:`~core.protocol.VisualArray`
   上的**真实原子操作**（``va.cmp`` / ``va.swap`` / …），因此计数器、颜色高亮、
   音效、单步回退与内置的 160 种算法走的是**同一条**指令流管线，指标完全可比。
3. **安全边界**：单行长度、指令总数（复用 ``max_ops``）、墙上时钟超时、坏行数量
   四重护栏；任何一条触发都会强杀子进程并留下可读的错误说明，绝不会卡死界面。
4. **不会死锁**：读 stdout / stderr 的线程先起来，写 stdin 的线程后起来，
   因此无论子进程「先猛写 stdout」还是「必须先读完 stdin」，都不会互相卡住。
5. **编译缓存**：按「源码内容 + 语言」做 SHA-1 摘要，产物落在临时缓存目录，
   同一份源码原封不动地重跑不会触发第二次编译（C# 首次 restore 也能省下来）。

对外主要接口
------------
* :data:`LANGUAGES` / :func:`language_list` / :func:`language_spec` —— 语言规格表
* :func:`detect_toolchains` / :func:`toolchain` —— 自动探测 g++/clang++/gcc/rustc/
  javac/go/node/python/dotnet
* :func:`template_source` / :func:`export_template` / :func:`export_all_templates`
  —— SDK 模板读取与一键导出
* :class:`PolyglotProgram` —— 一份外部源码的编译与运行句柄
* :func:`run_source` / :func:`run_program` —— 跑一次，拿回 ``Trace`` + 统计
* :func:`make_runner` —— 生成可直接喂给 ``register_external`` 的算法函数
* :func:`register_custom` / :func:`autoload_custom` —— 接入算法库并持久化
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from core.protocol import (AlgorithmTimeout, DEFAULT_MAX_OPS, ROLE_BOUNDARY,
                           ROLE_CURSOR, ROLE_HEAP_ROOT, ROLE_MAX, ROLE_MIN,
                           ROLE_PIVOT, ROLE_SORTED, Trace, VisualArray,
                           is_sorted_values)

__all__ = [
    "LANGUAGES", "CUSTOM_CATEGORY", "DEFAULT_RUN_TIMEOUT", "DEFAULT_COMPILE_TIMEOUT",
    "PolyglotError", "ToolchainMissing", "PolyglotProgram", "BuildResult",
    "RunStats", "RunOutcome", "Toolchain", "OpInterpreter",
    "cached_toolchains", "no_window_kwargs",
    "language_list", "language_spec", "detect_toolchains", "toolchain",
    "sdk_dir", "template_path", "template_source", "export_template",
    "export_all_templates", "default_export_dir", "cache_dir",
    "run_program", "run_source", "make_runner", "register_custom",
    "manifest_path", "load_manifest", "save_manifest", "autoload_custom",
    "unregister_custom", "next_custom_id", "main_class_name",
]

# ==========================================================================
# 0. 常量
# ==========================================================================
#: 外部自定义算法统一归入这个类别，序号从 901 起，永远排在内置 160 种之后
CUSTOM_CATEGORY = "99. 外部自定义算法 (Custom Polyglot)"

DEFAULT_RUN_TIMEOUT = 30.0        #: 单次运行的墙上时钟上限（秒）
DEFAULT_COMPILE_TIMEOUT = 180.0   #: 单次编译上限（C# 首次 restore 会比较慢）
MAX_LINE_CHARS = 1 << 16          #: 单行最长字符数，防止失控/恶意输出
MAX_BAD_LINES = 200               #: 坏行硬上限，超过即判定程序有 bug 并强杀
BAD_SAMPLES = 6                   #: 回显给用户的坏行样本数
MAX_STDERR_CHARS = 8000           #: 保留的 stderr 尾部长度

#: 合法的 MARK 角色（与 protocol.py 中的 ROLE_* 对齐）
KNOWN_ROLES = frozenset({
    ROLE_PIVOT, ROLE_BOUNDARY, ROLE_HEAP_ROOT, ROLE_SORTED,
    ROLE_CURSOR, ROLE_MAX, ROLE_MIN,
})

#: 无条件补进子进程环境的变量（减少「编码炸掉」「工具链找不到」这类环境问题）
_ROOT_ENV: Dict[str, str] = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
}

_WIN = platform.system() == "Windows"


class PolyglotError(RuntimeError):
    """外部算法引擎的通用错误。"""


class ToolchainMissing(PolyglotError):
    """所需编译器 / 解释器在系统里找不到。"""


# ==========================================================================
# 1. 语言规格表
# ==========================================================================
@dataclass(frozen=True)
class LanguageSpec:
    """一种外部语言的可执行规格。

    ``compile_argv`` / ``run_argv`` 是**参数模板**，构建时用下列占位符格式化：

    ============  ============================================
    占位符         含义
    ============  ============================================
    ``{tool}``    探测到的编译工具链绝对路径
    ``{java}``    Java 运行时启动器（javac 的同级 java）
    ``{src}``     参与编译 / 执行的源文件绝对路径
    ``{dir}``     源文件所在目录
    ``{stem}``    源文件主名（不含扩展名）
    ``{cls}``     主类名（Java / C# 用）
    ``{outdir}``  构建输出目录（缓存目录内的独立子目录）
    ``{exe}``     编译产物路径（可执行文件 / .dll）
    ============  ============================================
    """

    key: str
    name: str
    suffix: str
    template: str
    candidates: Tuple[str, ...] = ()          # 工具链候选可执行名，按优先级
    compile_argv: Tuple[str, ...] = ()        # 空 = 脚本语言，无需编译
    run_argv: Tuple[str, ...] = ()
    version_argv: Tuple[str, ...] = ("--version",)
    compile_timeout: float = DEFAULT_COMPILE_TIMEOUT
    needs_project: bool = False               # C# 需要生成 csproj
    env: Tuple[Tuple[str, str], ...] = ()     # 追加给子进程的环境变量
    note: str = ""

    @property
    def is_script(self) -> bool:
        return not self.compile_argv


def _spec(key: str, name: str, suffix: str, template: str,
          candidates: Sequence[str], compile_argv: Sequence[str] = (),
          run_argv: Sequence[str] = (), version_argv: Sequence[str] = ("--version",),
          **kw) -> LanguageSpec:
    return LanguageSpec(
        key=key, name=name, suffix=suffix, template=template,
        candidates=tuple(candidates), compile_argv=tuple(compile_argv),
        run_argv=tuple(run_argv), version_argv=tuple(version_argv), **kw)


def _is_stub_exe(path: str) -> bool:
    """判断是否为「Windows 应用执行别名」空壳程序。

    Windows 10/11 会在 ``%LOCALAPPDATA%\\Microsoft\\WindowsApps`` 下放一批
    0 字节的重解析点（``python.exe`` / ``python3.exe`` / ``node.exe`` …）。
    它们**能被找到、也能被启动**，但执行结果是弹出微软商店而不是运行我们的
    脚本。工具链探测若把它们当成真解释器，用户就会撞见「模板跑不通」这种
    完全摸不着头脑的故障，所以这里显式把它们判为不可用。

    注意只做字符串层面的目录名匹配（不 ``resolve()``）—— 那些别名本身就是
    重解析点，``resolve()`` 可能跳到商店应用的真实路径上，反而失去线索。
    """
    if os.name != "nt":
        return False
    norm = os.path.normcase(os.path.normpath(path))
    return f"{os.sep}windowsapps{os.sep}" in norm


def _python_candidates() -> Tuple[str, ...]:
    """Python 解释器的候选列表（**冻结环境下刻意排除 ``sys.executable``**）。

    PyInstaller 打包后 ``sys.executable`` 指向**本程序自己的 exe**，而它确实
    存在，于是探测阶段会把它当成 Python 解释器判为「可用」；真拿它去执行
    ``template.py`` 时，argparse 只会把它当作非法位置参数、以退出码 2 结束，
    而且 stderr 一片空白 —— 用户看到的现象是「Python 模板跑不通」，极难定位。

    所以冻结后只认环境变量 ``SVU_PYTHON`` 与 PATH 里的真解释器（源环境仍
    优先用「正在跑本项目的解释器」，版本与依赖天然一致）。
    """
    out: List[str] = []
    env = (os.environ.get("SVU_PYTHON") or "").strip().strip('"')
    if env:
        out.append(env)
    if not getattr(sys, "frozen", False) and sys.executable:
        out.append(sys.executable)
    out += ["python3", "python"]
    return tuple(dict.fromkeys(out))


#: 全部支持的语言（顺序即 UI 下拉框顺序）
#: 规范书要求的 7 种（C / C++ / Python / Java / Rust / Go / JS）之外，
#: 额外附带 C#（.NET）模板，对应需求里「支持 C# 编写自定义算法」一条。
LANGUAGES: Tuple[LanguageSpec, ...] = (
    _spec("cpp", "C++", ".cpp", "template.cpp", ("g++", "clang++", "c++"),
          ("{tool}", "-O2", "-std=c++17", "-o", "{exe}", "{src}"),
          ("{exe}",)),
    _spec("c", "C", ".c", "template.c", ("gcc", "clang", "cc"),
          ("{tool}", "-O2", "-std=c11", "-o", "{exe}", "{src}"),
          ("{exe}",)),
    # 源环境下直接用「正在跑本项目的解释器」（版本与依赖天然一致）；
    # 打包成 exe 后 sys.executable 是本程序自己，必须换用法，见 _python_candidates()
    _spec("python", "Python", ".py", "template.py",
          _python_candidates(),
          (), ("{tool}", "-X", "utf8", "-u", "{src}"), ("-V",),
          env=(("PYTHONIOENCODING", "utf-8"), ("PYTHONUTF8", "1"))),
    _spec("java", "Java", ".java", "Template.java", ("javac",),
          ("{tool}", "-encoding", "UTF-8", "-d", "{outdir}", "{src}"),
          # -Dstdout.encoding 是 JDK 18+ 的参数；老 JDK 忽略未知属性，无副作用
          ("{java}", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
           "-Dfile.encoding=UTF-8", "-cp", "{outdir}", "{cls}"),
          ("-version",)),
    _spec("rust", "Rust", ".rs", "template.rs", ("rustc",),
          ("{tool}", "-O", "-o", "{exe}", "{src}"), ("{exe}",)),
    _spec("go", "Go", ".go", "template.go", ("go",),
          ("{tool}", "build", "-o", "{exe}", "{src}"), ("{exe}",),
          ("version",), env=(("GO111MODULE", "off"),)),
    _spec("js", "JavaScript (Node.js)", ".js", "template.js", ("node", "nodejs"),
          (), ("{tool}", "{src}")),
    _spec("cs", "C# (.NET)", ".cs", "Template.cs", ("dotnet",),
          ("{tool}", "build", "-c", "Release", "--nologo", "-v", "quiet",
           "-o", "{outdir}", "{dir}"),
          # 实际运行命令由 PolyglotProgram.run_argv() 动态决定：优先用 apphost，
          # 因为它和 custom.dll 同时存在时 `dotnet xxx.dll` 会报 dependencies
          # manifest 冲突（同目录同名的 .exe 被误认成「扩展名不同」的同名程序集）。
          ("{exe}",), ("--version",), needs_project=True,
          note="需要 .NET SDK；首次编译要还原依赖，会比较慢"),
)

_BY_KEY: Dict[str, LanguageSpec] = {s.key: s for s in LANGUAGES}


def language_list() -> List[LanguageSpec]:
    return list(LANGUAGES)


def language_spec(key: str) -> LanguageSpec:
    spec = _BY_KEY.get((key or "").lower())
    if spec is None:
        raise PolyglotError(f"不支持的语言: {key!r}（可选 {sorted(_BY_KEY)}）")
    return spec


# ==========================================================================
# 2. 工具链自动探测
# ==========================================================================
@dataclass
class Toolchain:
    """一种语言的工具链探测结果。"""

    key: str
    name: str
    available: bool
    tool: str = ""            # 解析到的可执行文件绝对路径
    tool_name: str = ""       # 可执行文件名（g++ / clang++ / …）
    version: str = ""
    error: str = ""

    def badge(self) -> str:
        return "●" if self.available else "○"

    def describe(self) -> str:
        if not self.available:
            return self.error or "未安装"
        return f"{self.tool_name}  {self.version}".strip()


_tc_cache: Dict[str, Toolchain] = {}
_tc_lock = threading.Lock()
_probe_lock = threading.Lock()          # 串行化「真正的探测」，多窗口同时打开只探一次
_last_probe = 0.0                       # 上次真探测的时刻（monotonic）

#: 磁盘缓存结构版本：字段一变就自增，旧缓存自动作废
_TC_SCHEMA = 2

#: 距上次真探测不足这个秒数时，``force=True`` 也直接复用结果
_PROBE_FRESH = 15.0

#: 版本号探测超时。版本只用来在界面上显示，探不到不影响「可用」判定，
#: 所以宁短勿长 —— 万一某个工具卡住，也不能把整个探测拖到十秒以上。
_VERSION_TIMEOUT = 6.0


def no_window_kwargs() -> Dict[str, object]:
    """Windows 下静默启动子进程。

    ``subprocess`` 默认会给**控制台程序**分配一个新控制台，于是每探测一种
    语言就在屏幕上闪一个黑框。加 ``CREATE_NO_WINDOW``（0x08000000）后子进程
    照常有 stdout/stderr 管道，但不再出现任何窗口。
    """
    if _WIN:
        return {"creationflags": 0x08000000}
    return {}


def _tc_cache_path() -> Path:
    """工具链缓存的落盘位置（``%LOCALAPPDATA%\\SortingVisualizerUltimate``）。"""
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
            or str(Path.home() / ".cache"))
    return Path(base) / "SortingVisualizerUltimate" / "toolchains.json"


def _load_tc_cache() -> Optional[Dict[str, Toolchain]]:
    """读磁盘缓存；文件缺失 / 损坏 / 版本不符 / 记录不全一律返回 ``None``。

    还会顺手校验 ``available=True`` 的工具路径是否仍然存在 —— 用户卸载编译器
    之后，缓存不能继续骗界面说「就绪」。
    """
    try:
        raw = json.loads(_tc_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or raw.get("schema") != _TC_SCHEMA:
        return None
    items = raw.get("items")
    if not isinstance(items, dict):
        return None
    out: Dict[str, Toolchain] = {}
    for spec in LANGUAGES:
        rec = items.get(spec.key)
        if not isinstance(rec, dict):
            return None                    # 缺任何一种 → 当作没有缓存，老老实实重探
        tool = str(rec.get("tool") or "")
        avail = bool(rec.get("available")) and bool(tool)
        if avail and not Path(tool).is_file():
            avail, tool = False, ""
        out[spec.key] = Toolchain(
            key=spec.key, name=spec.name, available=avail, tool=tool,
            tool_name=str(rec.get("tool_name") or ""),
            version=str(rec.get("version") or "") if avail else "",
            error=str(rec.get("error") or "") if not avail else "")
    return out


def _save_tc_cache(items: Dict[str, Toolchain]) -> None:
    payload = {
        "schema": _TC_SCHEMA, "saved": time.time(),
        "items": {k: {"available": v.available, "tool": v.tool,
                      "tool_name": v.tool_name, "version": v.version,
                      "error": v.error} for k, v in items.items()},
    }
    p = _tc_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(p)                     # 原子替换，避免写一半断电留下坏文件
    except Exception:
        pass                               # 缓存写不进去不影响功能，只是下次慢一点


def _try_version(tool: str, argv: Sequence[str],
                 timeout: float = _VERSION_TIMEOUT) -> str:
    try:
        p = subprocess.run([tool, *argv], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           **no_window_kwargs())
    except Exception:
        return ""
    for line in ((p.stdout or "") + (p.stderr or "")).splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


def _resolve(cand: str) -> str:
    """把候选名解析成可执行文件的绝对路径，解析不到（或只解析到空壳别名）返回空串。

    ``shutil.which`` 只给 PATH 里**第一个**命中项，而 Windows 上的第一个命中项
    很可能是微软商店的应用执行别名（见 :func:`_is_stub_exe`）。所以这里做成
    「命中是空壳就把该目录从 PATH 摘掉、在余下部分里继续找」的循环，这样
    ``%LOCALAPPDATA%\\Microsoft\\WindowsApps`` 前置也不会压住真正的解释器。
    """
    if not cand:
        return ""
    if os.path.isabs(cand):
        return cand if os.path.isfile(cand) and not _is_stub_exe(cand) else ""
    raw = os.environ.get("PATH", "")
    path = raw
    while True:
        found = shutil.which(cand, path=path) or ""
        if not found or not _is_stub_exe(found):
            return found
        drop = os.path.dirname(found)
        parts = [p for p in path.split(os.pathsep)
                 if os.path.normcase(p) != os.path.normcase(drop)]
        if len(parts) == len(path.split(os.pathsep)):
            return ""                      # 摘不掉任何目录，避免死循环
        path = os.pathsep.join(parts)


def _first_available(candidates: Sequence[str]) -> str:
    """按优先级返回第一个能解析到的可执行文件。

    以前写成 ``next((_resolve(c) for c in ... if _resolve(c)), "")`` —— 生成器
    表达式会对每个候选**解析两次**（``shutil.which`` 要遍历整条 PATH），
    8 种语言 × 平均 2 个候选就是 30 多次全 PATH 扫描，白白多花几百毫秒。
    """
    for cand in candidates:
        found = _resolve(cand)
        if found:
            return found
    return ""


def _probe_one(spec: LanguageSpec) -> Toolchain:
    """探测单一语言。会被线程池并发调用，因此**不碰任何共享状态**。"""
    tool = _first_available(spec.candidates)
    if not tool:
        return Toolchain(
            key=spec.key, name=spec.name, available=False,
            error=f"未找到 {' / '.join(spec.candidates)}，请先安装并加入 PATH")
    return Toolchain(key=spec.key, name=spec.name, available=True, tool=tool,
                     tool_name=Path(tool).name,
                     version=_try_version(tool, spec.version_argv))


def cached_toolchains() -> Optional[Dict[str, Toolchain]]:
    """只读缓存（内存 → 磁盘），**绝不启动任何子进程**；无缓存返回 ``None``。

    这是 GUI 快速打开对话框的关键：先用它把界面画出来（毫秒级），真正的
    探测交给后台线程 :class:`ui.custom_algo_dialog.ToolchainWorker`。
    """
    with _tc_lock:
        if _tc_cache:
            return dict(_tc_cache)
    disk = _load_tc_cache()
    if not disk:
        return None
    with _tc_lock:
        if not _tc_cache:
            _tc_cache.update(disk)
            # 刻意不更新 _last_probe：缓存只用于「先显示」，后台仍会重探一次
    return dict(disk)


def detect_toolchains(force: bool = False) -> Dict[str, Toolchain]:
    """探测全部语言的工具链。

    * 不带 ``force``：命中内存 / 磁盘缓存立即返回，不启动任何子进程；
    * ``force=True``：真正重探。**会启动子进程，别在 GUI 线程里直接调用**，
      请走 ``ToolchainWorker``；距上次探测不足 15 秒时仍然直接复用结果；
    * 8 种语言并发探测（版本号各自一个子进程），总耗时 ≈ 最慢的那个，
      而不是逐个相加；
    * 结果同时写入磁盘缓存，下次启动可以秒开。
    """
    global _last_probe
    with _tc_lock:
        if _tc_cache and (not force
                          or (time.monotonic() - _last_probe) < _PROBE_FRESH):
            return dict(_tc_cache)

    with _probe_lock:                       # 多窗口同时打开时只探一次
        with _tc_lock:
            if _tc_cache and (time.monotonic() - _last_probe) < _PROBE_FRESH:
                return dict(_tc_cache)
        workers = max(1, min(len(LANGUAGES), 8))
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="toolchain") as pool:
            out = {tc.key: tc for tc in pool.map(_probe_one, LANGUAGES)}
        with _tc_lock:
            _tc_cache.clear()
            _tc_cache.update(out)
            _last_probe = time.monotonic()
        _save_tc_cache(out)
        return dict(out)



def toolchain(key: str, probe: bool = True) -> Toolchain:
    """取某一语言的工具链信息。

    ``probe=False`` 时**绝不启动探测**，只读内存 / 磁盘缓存 —— 供 UI 里那些
    「顺手拼一条给人看的命令行」的地方使用。否则缓存还没建好时，一次普通的
    界面重绘就可能把 8 个 ``--version`` 子进程拖进 GUI 线程（这正是「打开
    自定义算法工作室要等十几秒」的元凶之一）。
    """
    table = detect_toolchains() if probe else (cached_toolchains() or {})
    return table.get(key) or Toolchain(
        key=key, name=key, available=False,
        error="尚未检测到工具链" if not probe else "未知语言")


def available_languages() -> List[LanguageSpec]:
    tc = detect_toolchains()
    return [s for s in LANGUAGES if tc.get(s.key) and tc[s.key].available]


# ==========================================================================
# 3. SDK 模板读写与导出
# ==========================================================================
def sdk_dir() -> Path:
    """``sdk_templates/`` 目录（打包成 exe 后自动指向解包目录）。"""
    if getattr(sys, "frozen", False):                      # PyInstaller
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        cand = base / "sdk_templates"
        if cand.is_dir():
            return cand
    return Path(__file__).resolve().parent.parent / "sdk_templates"


def default_export_dir() -> Path:
    """模板默认导出位置：程序工作目录下的 ``custom_algorithms/``。"""
    return Path.cwd() / "custom_algorithms"


def template_path(key: str) -> Path:
    return sdk_dir() / language_spec(key).template


def template_source(key: str) -> str:
    """读取内置模板源码。"""
    p = template_path(key)
    if not p.is_file():
        raise PolyglotError(f"模板文件缺失：{p}")
    return p.read_text(encoding="utf-8")


def export_template(key: str, dest_dir: Optional[str | Path] = None,
                    overwrite: bool = False) -> Path:
    """把一种语言的模板导出到目标目录，返回落盘路径（默认不覆盖同名文件）。"""
    spec = language_spec(key)
    src = template_path(key)
    if not src.is_file():
        raise PolyglotError(f"模板文件缺失：{src}")
    target_dir = Path(dest_dir) if dest_dir else default_export_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / spec.template
    if dst.exists() and not overwrite:
        stem, suffix = dst.stem, dst.suffix
        n = 2
        while (target_dir / f"{stem}_{n}{suffix}").exists():
            n += 1
        dst = target_dir / f"{stem}_{n}{suffix}"
    shutil.copyfile(src, dst)
    return dst


def export_all_templates(dest_dir: Optional[str | Path] = None,
                         overwrite: bool = False) -> List[Path]:
    """一键导出全部 7+1 种语言模板。"""
    return [export_template(s.key, dest_dir, overwrite) for s in LANGUAGES]


# ==========================================================================
# 4. 编译缓存
# ==========================================================================
def cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "svu_polyglot_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_digest(lang: str, text: str, extra: str = "") -> str:
    h = hashlib.sha1()
    h.update(lang.encode("utf-8"))
    h.update(b"\0")
    h.update(extra.encode("utf-8"))
    h.update(b"\0")
    h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()[:12]


_JAVA_CLASS_RE = re.compile(r"(?:public\s+)?(?:final\s+|abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
_CS_CLASS_RE = re.compile(r"(?:public\s+|internal\s+)?(?:static\s+|sealed\s+|partial\s+)?class\s+([A-Za-z_$][\w$]*)")


def main_class_name(text: str, lang: str, fallback: str) -> str:
    """从源码里猜主类名（Java 要求 public 类名 == 文件名；C# 用来命名程序集）。"""
    rx = _JAVA_CLASS_RE if lang == "java" else _CS_CLASS_RE
    m = rx.search(text or "")
    return m.group(1) if m else fallback


@dataclass
class BuildContext:
    """格式化 argv 模板用的占位符集合。"""

    tool: str = ""
    java: str = "java"
    src: str = ""
    dir: str = ""
    stem: str = ""
    cls: str = ""
    outdir: str = ""
    exe: str = ""


def _fmt(argv: Sequence[str], ctx: BuildContext) -> List[str]:
    vals = {"tool": ctx.tool, "java": ctx.java, "src": ctx.src, "dir": ctx.dir,
            "stem": ctx.stem, "cls": ctx.cls, "outdir": ctx.outdir, "exe": ctx.exe}
    return [part.format(**vals) for part in argv]


def _pretty_argv(argv: Sequence[str]) -> str:
    return " ".join(f'"{a}"' if (" " in a or "\t" in a) else a for a in argv)


@dataclass
class BuildResult:
    """一次编译的结果。"""

    ok: bool
    argv: List[str] = field(default_factory=list)
    cwd: str = ""
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0
    error: str = ""
    cached: bool = False
    skipped: bool = False          # 脚本语言：无需编译

    def log(self, run_argv: Optional[Sequence[str]] = None) -> str:
        if self.skipped:
            head = "该语言为脚本执行，无需编译。"
        elif self.cached:
            head = "✓ 编译成功（命中缓存，跳过重复编译）"
        elif self.ok:
            head = f"✓ 编译成功   耗时 {self.elapsed * 1000:.0f} ms"
        else:
            head = f"✗ 编译失败   耗时 {self.elapsed * 1000:.0f} ms"
        lines = [head]
        if self.argv:
            lines.append("$ " + _pretty_argv(self.argv))
        if self.cwd:
            lines.append(f"  工作目录 {self.cwd}")
        if run_argv:
            lines.append("$ " + _pretty_argv(run_argv) + "   （运行）")
        if self.stdout.strip():
            lines.append("--- 编译器输出 ---")
            lines.append(self.stdout.strip())
        if self.stderr.strip():
            lines.append("--- 编译器错误 ---")
            lines.append(self.stderr.strip())
        if self.error:
            lines.append("✗ " + self.error)
        return "\n".join(lines)


# ==========================================================================
# 5. 指令流解析
# ==========================================================================
@dataclass
class RunStats:
    """一次外部程序运行的完整统计。"""

    lines: int = 0                     # 收到的 stdout 行数
    ops: int = 0                       # 成功翻译成原子操作的行数
    bad_lines: int = 0                 # 解析失败 / 越界 / 未知指令的行数
    unknown_ops: int = 0
    bad_samples: List[str] = field(default_factory=list)
    timed_out: bool = False
    killed: bool = False
    returncode: int = 0
    stderr: str = ""
    elapsed: float = 0.0
    op_counts: Dict[str, int] = field(default_factory=dict)
    truncated: bool = False            # 命中 max_ops 上限被安全截断
    sorted_ok: bool = False            # 跑完之后数组是否真的有序

    def note(self, op: str) -> None:
        self.op_counts[op] = self.op_counts.get(op, 0) + 1

    def summary(self) -> str:
        bits = [f"{self.ops} 条指令 / {self.lines} 行输出",
                f"耗时 {self.elapsed * 1000:.0f} ms"]
        if self.truncated:
            bits.append("⚠已达步数上限被截断")
        if self.timed_out:
            bits.append("⚠执行超时已强杀")
        if self.killed:
            bits.append("⚠进程被强杀")
        if self.bad_lines:
            bits.append(f"⚠{self.bad_lines} 行无法识别")
        if self.returncode not in (0, None):
            bits.append(f"进程退出码 {self.returncode}")
        return "，".join(bits)

    def detail(self) -> str:
        rows = [f"指令总数    {self.ops:,}",
                f"输出行数    {self.lines:,}",
                f"运行耗时    {self.elapsed * 1000:.1f} ms",
                f"进程退出码  {self.returncode}",
                f"排序结果    {'已有序 ✓' if self.sorted_ok else '尚未有序 ✗'}"]
        if self.bad_lines:
            rows.append(f"无法识别    {self.bad_lines} 行")
            for s in self.bad_samples[:BAD_SAMPLES]:
                rows.append(f"            {s}")
        if self.truncated:
            rows.append("提示        已达 max_ops 上限，指令流被安全截断")
        if self.timed_out:
            rows.append("提示        执行超时，子进程已被强制结束")
        if self.stderr.strip():
            rows.append("--- stderr ---")
            rows.extend(self.stderr.strip().splitlines()[-12:])
        if self.op_counts:
            rows.append("--- 指令构成 ---")
            for k, v in sorted(self.op_counts.items(), key=lambda kv: -kv[1]):
                rows.append(f"  {k:<12} {v:,}")
        return "\n".join(rows)


class OpInterpreter:
    """把子进程 stdout 的一行文本翻译成 :class:`VisualArray` 上的原子操作。

    每翻译成功一条就立即作用到真实数据上，因此后续指令看到的状态与子进程
    内部完全一致——这也让「越界索引」能被当场拦住，而不是悄悄写坏数据。
    """

    __slots__ = ("va", "n", "stats", "_done", "_bad_seen")

    def __init__(self, va: VisualArray) -> None:
        self.va = va
        self.n = va.n
        self.stats = RunStats()
        self._done = False
        self._bad_seen = False             # 同一行只计一次坏行

    # ---- 内部工具 --------------------------------------------------------
    def note_bad(self, raw: str, why: str) -> None:
        """记录一条坏行；同一输入行内的多次报错只算一次。"""
        if self._bad_seen:
            return
        self._bad_seen = True
        self.stats.bad_lines += 1
        if len(self.stats.bad_samples) < BAD_SAMPLES:
            self.stats.bad_samples.append(f"{why} → {raw[:80]}")

    def note_bad_fresh(self, raw: str, why: str) -> None:
        """供读循环报告「行级」错误：独立计一次，不受上一行影响。"""
        self._bad_seen = False
        self.note_bad(raw, why)

    @staticmethod
    def _int(tok: str) -> Optional[int]:
        try:
            return int(tok, 10)
        except (TypeError, ValueError):
            return None

    def _idx(self, tok: str, raw: str, aux: bool = False) -> Optional[int]:
        v = self._int(tok)
        if v is None:
            self.note_bad(raw, "索引不是整数")
            return None
        if v < 0:
            self.note_bad(raw, "索引为负")
            return None
        limit = self.va.aux_size if aux else self.n
        if v >= limit:
            self.note_bad(raw, f"索引越界（{v} ≥ {limit}）")
            return None
        return v

    # ---- 逐行翻译 --------------------------------------------------------
    def feed(self, raw: str) -> None:
        """翻译一行；无法识别时只记账，不抛异常（只有步数上限会抛）。"""
        if self._done:
            return
        self.stats.lines += 1
        line = raw.strip()
        if not line or line[0] in "#;" or line.startswith("//"):
            return
        self._bad_seen = False
        parts = line.split()
        handler = self._HANDLERS.get(parts[0].upper())
        if handler is None:
            self.stats.unknown_ops += 1
            self.note_bad(line, "未知指令")
            return
        try:
            name = handler(self, parts[1:], line)
        except AlgorithmTimeout:
            raise                                   # 步数上限：交给上层处理
        except Exception as exc:                    # 兜底：绝不因一行坏数据崩掉
            self.note_bad(line, type(exc).__name__)
            return
        if name:
            self.stats.ops += 1
            self.stats.note(name)

    # ---- 各类指令（返回计入统计的指令名，None 表示忽略） -----------------
    def _op_cmp(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "CMP 缺参数"); return None
        i = self._idx(a[0], raw); j = self._idx(a[1], raw)
        if i is None or j is None:
            return None
        self.va.cmp(i, j)
        return "CMP"

    def _op_cmp_val(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "CMP_VAL 缺参数"); return None
        i = self._idx(a[0], raw); v = self._int(a[1])
        if i is None:
            return None
        if v is None:
            self.note_bad(raw, "比较值不是整数"); return None
        self.va.cmp_val(i, v)
        return "CMP_VAL"

    def _op_gt(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "GT 缺参数"); return None
        i = self._idx(a[0], raw); j = self._idx(a[1], raw)
        if i is None or j is None:
            return None
        self.va.gt(i, j)
        return "CMP"

    def _op_gt_val(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "GT_VAL 缺参数"); return None
        i = self._idx(a[0], raw); v = self._int(a[1])
        if i is None or v is None:
            if v is None:
                self.note_bad(raw, "比较值不是整数")
            return None
        self.va.gt_val(i, v)
        return "CMP_VAL"

    def _op_read(self, a, raw):
        if not a:
            self.note_bad(raw, "READ 缺参数"); return None
        i = self._idx(a[0], raw)
        if i is None:
            return None
        self.va.get(i)
        return "READ"

    def _op_swap(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "SWAP 缺参数"); return None
        i = self._idx(a[0], raw); j = self._idx(a[1], raw)
        if i is None or j is None or i == j:
            return None                      # 自我交换不产生指令，与 protocol 一致
        self.va.swap(i, j)
        return "SWAP"

    def _op_set(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "SET 缺参数"); return None
        i = self._idx(a[0], raw); v = self._int(a[1])
        if i is None or v is None:
            if v is None:
                self.note_bad(raw, "写入值不是整数")
            return None
        self.va.set(i, v)
        return "SET"

    def _op_flip(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "FLIP 缺参数"); return None
        l = self._idx(a[0], raw); r = self._idx(a[1], raw)
        if l is None or r is None or l >= r:
            return None
        self.va.flip(l, r)
        return "FLIP"

    def _op_aux_init(self, a, raw):
        if not a:
            self.note_bad(raw, "AUX_INIT 缺参数"); return None
        size = self._int(a[0])
        if size is None or size < 0:
            self.note_bad(raw, "辅助数组长度非法"); return None
        self.va.aux_init(size)
        return "AUX_INIT"

    def _op_aux_set(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "AUX_SET 缺参数"); return None
        i = self._idx(a[0], raw, aux=True); v = self._int(a[1])
        if i is None or v is None:
            if v is None:
                self.note_bad(raw, "辅助写入值不是整数")
            return None
        self.va.aux_set(i, v)
        return "AUX_SET"

    def _op_aux_get(self, a, raw):
        if not a:
            self.note_bad(raw, "AUX_GET 缺参数"); return None
        i = self._idx(a[0], raw, aux=True)
        if i is None:
            return None
        self.va.aux_get(i)
        return "AUX_READ"

    def _op_aux_swap(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "AUX_SWAP 缺参数"); return None
        i = self._idx(a[0], raw, aux=True); j = self._idx(a[1], raw, aux=True)
        if i is None or j is None or i == j:
            return None
        self.va.aux_swap(i, j)
        return "AUX_SWAP"

    def _op_aux_cmp(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "AUX_CMP 缺参数"); return None
        i = self._idx(a[0], raw, aux=True); j = self._idx(a[1], raw, aux=True)
        if i is None or j is None:
            return None
        self.va.aux_cmp(i, j)
        return "AUX_CMP"

    def _op_aux_clear(self, a, raw):
        self.va.aux_clear()
        return "AUX_CLEAR"

    def _op_mark(self, a, raw):
        if len(a) < 2:
            self.note_bad(raw, "MARK 缺参数"); return None
        i = self._idx(a[0], raw)
        if i is None:
            return None
        role = a[1].upper()
        if role not in KNOWN_ROLES and len(self.stats.bad_samples) < BAD_SAMPLES:
            self.stats.bad_samples.append(f"未知标记角色 {role}（已按原样放行）")
        self.va.mark(i, role)
        return "MARK"

    def _op_clear_marks(self, a, raw):
        self.va.clear_marks()
        return "CLEAR_MARKS"

    def _op_msg(self, a, raw):
        head = raw.split(None, 1)
        self.va.msg((head[1] if len(head) > 1 else "")[:400])
        return "MSG"

    def _op_done(self, a, raw):
        self._done = True
        return None

    _HANDLERS: Dict[str, Callable] = {
        "CMP": _op_cmp, "COMPARE": _op_cmp, "LT": _op_cmp,
        "CMP_VAL": _op_cmp_val, "CMPVAL": _op_cmp_val, "CMPV": _op_cmp_val,
        "CMP_VALUE": _op_cmp_val,
        "GT": _op_gt, "GREATER": _op_gt,
        "GT_VAL": _op_gt_val, "GTVAL": _op_gt_val, "GT_VALUE": _op_gt_val,
        "READ": _op_read, "GET": _op_read,
        "SWAP": _op_swap, "SWP": _op_swap, "EXCHANGE": _op_swap,
        "SET": _op_set, "ASSIGN": _op_set, "WRITE": _op_set,
        "FLIP": _op_flip, "REVERSE": _op_flip, "REV": _op_flip,
        "AUX_INIT": _op_aux_init, "AUXINIT": _op_aux_init, "AINIT": _op_aux_init,
        "AUX_SET": _op_aux_set, "AUXSET": _op_aux_set, "ASET": _op_aux_set,
        "AUX_GET": _op_aux_get, "AUX_READ": _op_aux_get, "AUXGET": _op_aux_get,
        "AUX_SWAP": _op_aux_swap, "AUXSWAP": _op_aux_swap, "ASWAP": _op_aux_swap,
        "AUX_CMP": _op_aux_cmp, "AUXCMP": _op_aux_cmp, "ACMP": _op_aux_cmp,
        "AUX_CLEAR": _op_aux_clear, "AUXCLEAR": _op_aux_clear,
        "MARK": _op_mark, "LABEL": _op_mark,
        "CLEAR_MARKS": _op_clear_marks, "CLEARMARKS": _op_clear_marks,
        "UNMARK": _op_clear_marks,
        "MSG": _op_msg, "MESSAGE": _op_msg, "LOG": _op_msg,
        "DONE": _op_done, "END": _op_done, "FINISH": _op_done,
    }


# ==========================================================================
# 6. 编译与运行句柄
# ==========================================================================
class PolyglotProgram:
    """一份外部源码的编译 / 运行句柄。

    ``inline_source`` 用于「编辑器里改完直接试跑」——此时源码会被写进缓存目录
    里一个**命名正确**的文件（Java 的 public 类名要求依赖这一点）。
    """

    def __init__(self, lang: str, source_path: Optional[str | Path] = None,
                 inline_source: Optional[str] = None,
                 workdir: Optional[str | Path] = None,
                 display_name: str = "") -> None:
        self.spec = language_spec(lang)
        self.lang = self.spec.key
        self.display_name = display_name or (
            Path(source_path).stem if source_path else "custom")
        self._inline = inline_source
        self._built: Optional[BuildResult] = None
        self._ctx: Optional[BuildContext] = None
        self._out_root: Path = cache_dir()
        self._align_error = ""        # Java 类名/文件名对齐副本投递失败的原因
        self.last_stats: Optional[RunStats] = None

        if inline_source is not None:
            text = inline_source
            if self.lang == "java":
                name = f"{main_class_name(text, 'java', 'Template')}.java"
            elif self.lang == "cs":
                name = "Program.cs"
            else:
                name = f"{self.display_name}{self.spec.suffix}"
            work = Path(workdir) if workdir else cache_dir() / "src"
            work.mkdir(parents=True, exist_ok=True)
            self.source = work / name
            self.source.write_text(text, encoding="utf-8", newline="\n")
        else:
            if source_path is None:
                raise PolyglotError("必须提供 source_path 或 inline_source")
            self.source = Path(source_path).resolve()
            if not self.source.is_file():
                raise PolyglotError(f"源文件不存在：{self.source}")

        self.workdir = (Path(workdir) if workdir else self.source.parent).resolve()

    # ---- 源码 ------------------------------------------------------------
    def read_source(self) -> str:
        return self.source.read_text(encoding="utf-8", errors="replace")

    def refresh_inline(self, text: str) -> None:
        """把编辑器里的最新内容写回临时源文件（并让编译缓存失效）。"""
        if self._inline is None:
            raise PolyglotError("该句柄不是由 inline_source 创建的")
        if self.read_source() != text:
            self.source.write_text(text, encoding="utf-8", newline="\n")
        self._inline = text
        self._built = None

    # ---- 构建参数 --------------------------------------------------------
    @property
    def build_root(self) -> Path:
        return self._out_root

    def _build_ctx(self, probe: bool = True) -> BuildContext:
        tc = toolchain(self.lang, probe=probe)
        if not tc.available:
            raise ToolchainMissing(f"{self.spec.name} 工具链不可用：{tc.error}")
        text = self.read_source()
        digest = source_digest(self.lang, text, self.spec.suffix)
        self._out_root = cache_dir() / f"{self.lang}_{_safe_name(self.source.stem)}_{digest}"
        outdir = self._out_root / "out"
        exe_name = self.source.stem + (".exe" if _WIN else "")
        cls = main_class_name(text, self.lang, self.source.stem)
        src = str(self.source)

        # javac 强制要求「public 类名 == 文件名」。用户把模板另存成别的名字时
        # （例如 MyQuickSort.java 里还是 public class Template）会直接编译失败，
        # 报错信息还相当晦涩，所以这里在构建目录里自动投一份「类名.java」再编译。
        if self.lang == "java" and cls != self.source.stem:
            aligned = self._out_root / f"{cls}.java"
            try:
                # 注意：构建根目录此前还没建过（outdir 要更晚才 mkdir），
                # 忘了这一步会让 write_text 抛 FileNotFoundError 而被静默吞掉，
                # 于是又退回原文件、javac 照旧报「类名与文件名不符」。
                self._out_root.mkdir(parents=True, exist_ok=True)
                if (not aligned.is_file()) or \
                        aligned.read_text(encoding="utf-8") != text:
                    aligned.write_text(text, encoding="utf-8", newline="\n")
                src = str(aligned)
            except OSError as exc:
                self._align_error = str(exc)             # 投递失败就用原文件，交给 javac 报错

        ctx = BuildContext(
            tool=tc.tool,
            java=_java_launcher(tc.tool),
            src=src,
            dir=str(self.source.parent),
            stem=self.source.stem,
            cls=cls,
            outdir=str(outdir),
            exe=str(outdir / exe_name),
        )
        self._ctx = ctx
        return ctx

    def exe_path(self) -> str:
        return (self._ctx or self._build_ctx()).exe

    def command_lines(self) -> Tuple[str, str]:
        """返回 ``(编译命令行, 运行命令行)``，供 UI 展示。

        用 ``probe=False``：这只是拼一串给人看的命令，绝不能因为缓存还没建好
        就把一批 ``--version`` 子进程拖进调用方的线程（UI 线程会直接卡住）。
        """
        try:
            ctx = self._ctx or self._build_ctx(probe=False)
            comp = ("—（脚本语言无需编译）" if self.spec.is_script
                    else _pretty_argv(_fmt(self.spec.compile_argv, ctx)))
            return comp, _pretty_argv(self.run_argv())
        except PolyglotError as exc:
            return f"（不可用：{exc}）", "—"

    def run_argv(self) -> List[str]:
        ctx = self._ctx or self._build_ctx()
        if self.lang == "cs":
            # dotnet build 会同时产出 apphost（custom.exe / custom）与 custom.dll，
            # 两者共存时 `dotnet custom.dll` 会因依赖清单冲突而启动失败，
            # 所以能直接跑 apphost 就直接跑，跑不了再退回 dotnet + dll。
            apphost = Path(ctx.outdir) / ("custom.exe" if _WIN else "custom")
            if apphost.is_file():
                return [str(apphost)]
            return [ctx.tool, str(Path(ctx.outdir) / "custom.dll")]
        return _fmt(self.spec.run_argv, ctx)

    def program_line(self) -> str:
        try:
            return _pretty_argv(self.run_argv())
        except PolyglotError as exc:
            return f"（不可用：{exc}）"

    # ---- 编译 ------------------------------------------------------------
    def build(self, force: bool = False) -> BuildResult:
        """编译（带内容哈希缓存）。脚本语言直接返回 ``skipped`` 结果。"""
        if self._built is not None and not force:
            return self._built

        ctx = self._build_ctx()

        if self.spec.is_script:
            res = BuildResult(ok=True, skipped=True, cached=True)
            res.argv = _fmt(self.spec.run_argv, ctx)
            self._built = res
            return res

        if self.spec.needs_project:
            proj = self._prepare_dotnet_project(ctx)
            ctx.dir = str(proj)
            ctx.src = str(proj / "Program.cs")

        outdir = Path(ctx.outdir)
        stamp = outdir / ".svu_ok"
        if not force and stamp.is_file():
            res = BuildResult(ok=True, cached=True,
                              argv=_fmt(self.spec.compile_argv, ctx))
            self._built = res
            return res

        outdir.mkdir(parents=True, exist_ok=True)
        argv = _fmt(self.spec.compile_argv, ctx)
        t0 = time.perf_counter()
        try:
            p = subprocess.run(argv, cwd=str(self.workdir), env=self.child_env(),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", stdin=subprocess.DEVNULL,
                               timeout=self.spec.compile_timeout,
                               **no_window_kwargs())
            out, err, rc = p.stdout or "", p.stderr or "", p.returncode
        except FileNotFoundError as exc:
            res = BuildResult(ok=False, argv=argv, error=f"找不到编译器：{exc}")
            self._built = res
            return res
        except OSError as exc:
            res = BuildResult(ok=False, argv=argv, error=f"无法启动编译器：{exc}")
            self._built = res
            return res
        except subprocess.TimeoutExpired:
            res = BuildResult(ok=False, argv=argv, cwd=str(self.workdir),
                              elapsed=self.spec.compile_timeout,
                              error=f"编译超时（>{self.spec.compile_timeout:.0f}s）")
            self._built = res
            return res
        dt = time.perf_counter() - t0

        res = BuildResult(ok=(rc == 0), argv=argv, cwd=str(self.workdir),
                          stdout=out, stderr=err, elapsed=dt)
        if rc == 0:
            stamp.write_text("ok", encoding="utf-8")
        else:
            res.error = f"编译器返回码 {rc}"
            if self._align_error:
                res.stderr = (res.stderr + "\n[内部] Java 类名/文件名对齐副本投递失败："
                              + self._align_error).strip()
        self._built = res
        return res

    # ---- C# 最小工程 -----------------------------------------------------
    def _prepare_dotnet_project(self, ctx: BuildContext) -> Path:
        proj = self._out_root / "proj"
        proj.mkdir(parents=True, exist_ok=True)
        text = self.read_source()
        target = proj / "Program.cs"
        if (not target.is_file()) or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8", newline="\n")
        csproj = proj / "custom.csproj"
        body = (
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup>\n'
            '    <OutputType>Exe</OutputType>\n'
            f'    <TargetFramework>{_dotnet_tfm()}</TargetFramework>\n'
            '    <Nullable>disable</Nullable>\n'
            '    <ImplicitUsings>disable</ImplicitUsings>\n'
            '    <AssemblyName>custom</AssemblyName>\n'
            '    <RootNamespace>SortingVisualizerCustom</RootNamespace>\n'
            '    <InvariantGlobalization>true</InvariantGlobalization>\n'
            '    <GenerateDocumentationFile>false</GenerateDocumentationFile>\n'
            '    <SatelliteResourceLanguages>en</SatelliteResourceLanguages>\n'
            '  </PropertyGroup>\n'
            '</Project>\n')
        csproj.write_text(body, encoding="utf-8", newline="\n")
        ctx.stem = "custom"
        ctx.exe = str(Path(ctx.outdir) / ("custom.exe" if _WIN else "custom"))
        return proj

    # ---- 子进程环境 ------------------------------------------------------
    def child_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        for k, v in _ROOT_ENV.items():
            env.setdefault(k, v)
        for k, v in self.spec.env:
            env[k] = v
        return env


def _safe_name(text: str) -> str:
    return re.sub(r"[^\w.-]+", "_", text)[:40] or "src"


def _java_launcher(javac_path: str) -> str:
    """由 javac 推出同目录的 java 启动器；推不出来就退回 PATH 里的 java。"""
    p = Path(javac_path)
    for cand in (p.with_name("java.exe"), p.with_name("java")):
        if cand.is_file():
            return str(cand)
    return shutil.which("java") or "java"


def _dotnet_tfm() -> str:
    """按已安装的 .NET SDK 主版本挑 TargetFramework。"""
    try:
        p = subprocess.run(["dotnet", "--version"], capture_output=True,
                           text=True, timeout=8,
                           stdin=subprocess.DEVNULL, **no_window_kwargs())
        major = int((p.stdout or "8").strip().split(".")[0])
    except Exception:
        major = 8
    return f"net{max(6, min(major, 10))}.0"


# ==========================================================================
# 7. 跑一次：写入 stdin、读回指令流
# ==========================================================================
def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass


def _start_readers(proc: subprocess.Popen, interp: OpInterpreter
                   ) -> "queue.Queue[Optional[str]]":
    """先起读线程——必须在写 stdin **之前**，否则可能双向卡死。"""
    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:                        # type: ignore[union-attr]
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)

    def _drain_err() -> None:
        try:
            for line in proc.stderr:                        # type: ignore[union-attr]
                interp.stats.stderr += line
                if len(interp.stats.stderr) > MAX_STDERR_CHARS:
                    interp.stats.stderr = interp.stats.stderr[-MAX_STDERR_CHARS:]
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True, name="svu-stdout").start()
    threading.Thread(target=_drain_err, daemon=True, name="svu-stderr").start()
    return q


def _write_stdin(proc: subprocess.Popen, payload: str,
                 errors: List[str]) -> threading.Thread:
    """在独立线程里写入 stdin，避免大数据量把主线程堵住。"""
    def _w() -> None:
        try:
            proc.stdin.write(payload)                       # type: ignore[union-attr]
            proc.stdin.flush()                              # type: ignore[union-attr]
        except Exception as exc:
            errors.append(f"写入子进程 stdin 失败：{exc}")
        finally:
            try:
                proc.stdin.close()                          # type: ignore[union-attr]
            except Exception:
                pass

    t = threading.Thread(target=_w, daemon=True, name="svu-stdin")
    t.start()
    return t


def _consume(q: "queue.Queue[Optional[str]]", interp: OpInterpreter,
             deadline: float, max_lines: int) -> None:
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            interp.stats.timed_out = True
            return
        try:
            line = q.get(timeout=min(0.2, remain))
        except queue.Empty:
            continue
        if line is None:
            return
        if len(line) > MAX_LINE_CHARS:
            interp.note_bad_fresh(line[:80], "单行过长")
            continue
        interp.feed(line)
        if interp.stats.lines >= max_lines:
            interp.note_bad_fresh(line, f"输出行数已达上限 {max_lines}，强制中止")
            interp.stats.killed = True
            return
        if interp.stats.bad_lines >= MAX_BAD_LINES:
            interp.note_bad_fresh(line, f"坏行数已达上限 {MAX_BAD_LINES}，判定程序有 bug")
            interp.stats.killed = True
            return


def run_program(program: PolyglotProgram, values: Sequence[int],
                timeout: float = DEFAULT_RUN_TIMEOUT,
                max_ops: int = DEFAULT_MAX_OPS,
                build: bool = True,
                target: Optional[VisualArray] = None) -> Tuple[Trace, RunStats]:
    """跑一次外部程序，返回 ``(指令流, 运行统计)``。

    ``target`` 为空时内部自建一个 :class:`VisualArray` 收集指令流；
    传入已有的 ``va`` 则指令流会**直接落在它的 trace 上**——这样在
    ``record()`` 里作为算法函数调用时，全程只有一遍开销。
    """
    if build:
        br = program.build()
        if not br.ok:
            raise PolyglotError("编译失败：\n" + br.log())

    if target is None:
        tr = Trace()
        va = VisualArray(values, tr, max_ops=max_ops)
    else:
        va = target
        tr = va.trace

    interp = OpInterpreter(va)
    payload = f"{va.n}\n{' '.join(str(v) for v in va.data)}\n"
    max_lines = max(1024, max_ops + 64)

    t0 = time.perf_counter()
    proc: Optional[subprocess.Popen] = None
    errors: List[str] = []
    try:
        try:
            proc = subprocess.Popen(
                program.run_argv(), cwd=str(program.workdir),
                env=program.child_env(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                **no_window_kwargs())
        except (FileNotFoundError, OSError) as exc:
            raise PolyglotError(f"无法启动外部程序：{exc}") from exc

        q = _start_readers(proc, interp)          # 先读后写，杜绝死锁
        _write_stdin(proc, payload, errors)
        _consume(q, interp, time.monotonic() + timeout, max_lines)
    except AlgorithmTimeout:
        interp.stats.truncated = True
        raise
    finally:
        if proc is not None:
            _terminate(proc)
            if proc.returncode is None:
                interp.stats.killed = True
            else:
                interp.stats.returncode = proc.returncode
        if errors:
            interp.stats.stderr = (interp.stats.stderr + "\n" + "\n".join(errors))[-MAX_STDERR_CHARS:]
        interp.stats.elapsed = time.perf_counter() - t0
        interp.stats.sorted_ok = is_sorted_values(va.data)
        tr.elapsed = interp.stats.elapsed
        program.last_stats = interp.stats
    return tr, interp.stats


@dataclass
class RunOutcome:
    """一次「编译 + 运行」的完整结果，供 UI 直接展示。"""

    lang: str
    program: Optional[PolyglotProgram] = None
    build: Optional[BuildResult] = None
    trace: Optional[Trace] = None
    stats: RunStats = field(default_factory=RunStats)
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error and self.trace is not None

    @property
    def ops(self) -> int:
        return self.trace.n_ops if self.trace is not None else 0

    @property
    def sorted_ok(self) -> bool:
        return self.stats.sorted_ok

    def report(self) -> str:
        lines: List[str] = []
        if self.build is not None:
            run_argv = None
            if self.program is not None:
                try:
                    run_argv = self.program.run_argv()
                except PolyglotError:
                    run_argv = None
            lines.append(self.build.log(run_argv))
        if self.error:
            lines.append("✗ " + self.error)
        if self.stats.ops or self.stats.lines or self.stats.stderr.strip():
            lines.append("--- 运行统计 ---")
            lines.append(self.stats.detail())
        return "\n".join(lines)


def run_source(lang: str, source: str, values: Sequence[int],
               timeout: float = DEFAULT_RUN_TIMEOUT,
               max_ops: int = DEFAULT_MAX_OPS,
               display_name: str = "preview") -> RunOutcome:
    """编译并运行一段源码（对话框里的「编译并运行」/ 预览走这条路径）。

    与 :func:`run_program` 的区别是它会**把异常收进返回值**，
    方便 UI 一次性把「编译日志 + 运行统计 + 错误」全画出来。
    """
    outcome = RunOutcome(lang=lang)
    t0 = time.perf_counter()
    try:
        program = PolyglotProgram(lang, inline_source=source,
                                  display_name=display_name)
    except PolyglotError as exc:
        outcome.error = str(exc)
        return outcome
    outcome.program = program

    try:
        br = program.build()
    except ToolchainMissing as exc:
        outcome.build = BuildResult(ok=False, error=str(exc))
        outcome.error = str(exc)
        return outcome
    except PolyglotError as exc:
        outcome.build = BuildResult(ok=False, error=str(exc))
        outcome.error = str(exc)
        return outcome
    outcome.build = br
    if not br.ok:
        outcome.error = "编译未通过，请查看编译日志"
        return outcome

    tr = Trace()
    va = VisualArray(values, tr, max_ops=max_ops)
    try:
        run_program(program, values, timeout=timeout, max_ops=max_ops,
                    build=False, target=va)
    except PolyglotError as exc:
        outcome.error = str(exc)
        return outcome
    except AlgorithmTimeout:
        outcome.trace = tr
        outcome.stats = program.last_stats or RunStats(truncated=True)
        outcome.stats.truncated = True
        outcome.error = f"达到步数上限（{max_ops:,} 步）已安全截断"
        outcome.elapsed = time.perf_counter() - t0
        return outcome

    outcome.trace = tr
    outcome.stats = program.last_stats or RunStats()
    outcome.elapsed = time.perf_counter() - t0
    return outcome


# ==========================================================================
# 8. 接入算法库
# ==========================================================================
def make_runner(lang: str, source_path: Optional[str | Path] = None,
                inline_source: Optional[str] = None,
                workdir: Optional[str | Path] = None,
                timeout: float = DEFAULT_RUN_TIMEOUT,
                display_name: str = "") -> Callable[[VisualArray], None]:
    """生成一个可直接交给 ``register_external`` 的算法函数。

    该函数接收 :class:`VisualArray`，把外部程序的指令流**就地重放**上去，
    因此与内置算法共用 ``record()`` → ``Trace`` → ``TracePlayer`` 的完整管线。
    """
    program = PolyglotProgram(lang, source_path=source_path,
                              inline_source=inline_source, workdir=workdir,
                              display_name=display_name)

    def runner(va: VisualArray) -> None:
        try:
            br = program.build()
        except ToolchainMissing as exc:
            va.msg(f"[外部算法] 工具链不可用：{exc}")
            raise
        if not br.ok:
            va.msg(f"[外部算法] 编译失败：{br.error or '详见编译日志'}")
            raise PolyglotError("编译失败：\n" + br.log())

        tr, stats = run_program(program, [], timeout=timeout,
                                build=False, target=va)
        _annotate(va, stats)

    runner.polyglot_program = program                    # type: ignore[attr-defined]
    return runner


def _annotate(va: VisualArray, stats: RunStats) -> None:
    """把运行统计写成最后一条 MSG，让 HUD 上看得到外部程序的真实情况。

    若指令流已经顶到 ``max_ops`` 上限，补 MSG 会再次触发截断——那种情况下
    静默放弃注释即可，不影响「已安全截断」的既有语义。
    """
    verdict = "数组已有序 ✓" if stats.sorted_ok else "数组尚未有序 ✗"
    try:
        va.msg(f"[外部算法] {verdict}｜{stats.summary()}")
    except AlgorithmTimeout:
        pass


def _slug(text: str, fallback: str = "custom") -> str:
    out = re.sub(r"[^0-9a-zA-Z_]+", "_", (text or "").strip()).strip("_").lower()
    if not out:
        out = fallback
    if out[0].isdigit():
        out = "a" + out
    return out[:48]


def next_custom_id(slug: str, taken: Optional[Iterable[str]] = None) -> str:
    """生成 ``901_custom_xxx`` 形式的算法 ID（从 901 起，避开内置 001~160）。"""
    from core.registry import REGISTRY

    existing = set(taken or ()) | set(REGISTRY)
    n = 901
    while True:
        cand = f"{n:03d}_custom_{_slug(slug)}"
        if cand not in existing:
            return cand
        n += 1


def register_custom(lang: str, source_path: Optional[str | Path] = None,
                    inline_source: Optional[str] = None,
                    name_zh: str = "", name_en: str = "",
                    algo_id: str = "", category: str = CUSTOM_CATEGORY,
                    time_best: str = "外部实现", time_avg: str = "外部实现",
                    time_worst: str = "外部实现", space: str = "外部实现",
                    stable: bool = False, desc: str = "",
                    timeout: float = DEFAULT_RUN_TIMEOUT,
                    persist: bool = True,
                    workdir: Optional[str | Path] = None):
    """把一份外部源码注册进算法库，返回 :class:`~core.registry.AlgoMeta`。

    注册后它会出现在左侧算法树（类别「99. 外部自定义算法」）、可参与四宫格
    同屏赛马、可导出视频，与内置算法完全平权。
    """
    from core.registry import register_external

    spec = language_spec(lang)
    tc = toolchain(spec.key)
    if not tc.available:
        raise ToolchainMissing(f"{spec.name} 工具链不可用：{tc.error}")

    label = name_en or (Path(source_path).stem if source_path else "")
    if not name_zh:
        name_zh = f"自定义 {spec.name}：{label or '未命名'}"
    if not name_en:
        name_en = f"Custom {spec.name} ({label or 'untitled'})"

    aid = algo_id.strip() or next_custom_id(label or name_zh)
    runner = make_runner(spec.key, source_path=source_path,
                         inline_source=inline_source, workdir=workdir,
                         timeout=timeout, display_name=label or "custom")
    meta = register_external(
        algo_id=aid, name_zh=name_zh, name_en=name_en, runner=runner,
        category=category, time_best=time_best, time_avg=time_avg,
        time_worst=time_worst, space=space, stable=stable, desc=desc,
        source_lang=spec.key,
        # 源码路径随元数据一起带着走：「查看源码」按钮不必回头去翻清单，
        # 清单丢了（换机器 / 手改过）也还能打开源码。
        extra={"source_path": str(Path(source_path).resolve()) if source_path else ""})

    if persist:
        try:
            save_manifest(upsert={
                "algo_id": aid, "name_zh": name_zh, "name_en": name_en,
                "lang": spec.key, "category": category,
                "path": str(Path(source_path).resolve()) if source_path else "",
                "time_best": time_best, "time_avg": time_avg,
                "time_worst": time_worst, "space": space,
                "stable": stable, "desc": desc,
            })
        except Exception:
            pass
    return meta


# ---- 持久化清单 ----------------------------------------------------------
def manifest_path(base: Optional[str | Path] = None) -> Path:
    return (Path(base) if base else default_export_dir()) / "custom_index.json"


def load_manifest(base: Optional[str | Path] = None) -> List[Dict[str, object]]:
    p = manifest_path(base)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def save_manifest(upsert: Optional[Dict[str, object]] = None,
                  base: Optional[str | Path] = None,
                  records: Optional[List[Dict[str, object]]] = None) -> Path:
    """写入 / 更新自定义算法清单（同一 ``algo_id`` 覆盖）。"""
    p = manifest_path(base)
    items = load_manifest(base) if records is None else list(records)
    if upsert is not None:
        aid = str(upsert.get("algo_id", ""))
        items = [d for d in items if str(d.get("algo_id", "")) != aid]
        items.append(upsert)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def autoload_custom(base: Optional[str | Path] = None,
                    report: Optional[List[str]] = None) -> int:
    """启动时按清单重新注册上次导入过的自定义算法（源码仍在的才注册）。

    返回成功注册的条数；跳过/失败原因会追加到 ``report``。
    """
    from core.registry import REGISTRY

    ok = 0
    for rec in load_manifest(base):
        aid = str(rec.get("algo_id", ""))
        path = str(rec.get("path", ""))
        if not aid or aid in REGISTRY:
            continue
        if not path:
            if report is not None:
                report.append(f"{aid} 清单里没有源码路径，跳过")
            continue
        if not Path(path).is_file():
            if report is not None:
                report.append(f"源码已不存在，跳过：{path}")
            continue
        try:
            register_custom(
                lang=str(rec.get("lang", "python")), source_path=path,
                name_zh=str(rec.get("name_zh", "")),
                name_en=str(rec.get("name_en", "")),
                algo_id=aid, category=str(rec.get("category", CUSTOM_CATEGORY)),
                time_best=str(rec.get("time_best", "外部实现")),
                time_avg=str(rec.get("time_avg", "外部实现")),
                time_worst=str(rec.get("time_worst", "外部实现")),
                space=str(rec.get("space", "外部实现")),
                stable=bool(rec.get("stable", False)),
                desc=str(rec.get("desc", "")), persist=False)
            ok += 1
        except Exception as exc:
            if report is not None:
                report.append(f"注册 {aid} 失败：{exc}")
    return ok


def unregister_custom(algo_id: str, base: Optional[str | Path] = None) -> bool:
    """从算法库与清单里同时移除一个自定义算法。"""
    from core.registry import REGISTRY

    removed = REGISTRY.pop(algo_id, None) is not None
    records = [d for d in load_manifest(base)
               if str(d.get("algo_id", "")) != algo_id]
    try:
        save_manifest(base=base, records=records)
    except Exception:
        pass
    return removed
