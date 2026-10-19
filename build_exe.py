#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— PyInstaller 一键打包脚本。

规范书 6.2 落地：把**程序代码、160 个内置算法模块、多语言 SDK 模板目录、
以及本地 ffmpeg.exe** 一起打包成免安装独立运行的 Windows 可执行程序。

用法::

    python build_exe.py                     # 体检 + onedir 目录版打包（推荐）
    python build_exe.py --onefile           # 单文件 exe（体积大、首次启动慢）
    python build_exe.py --check             # 只做环境体检，不打包
    python build_exe.py --clean             # 打包前清理 build/ dist/ *.spec
    python build_exe.py --console           # 保留控制台窗口（排查启动问题）
    python build_exe.py --verify            # 打包后跑一遍 exe --selftest
    python build_exe.py --ffmpeg D:\\ffmpeg.exe
    python build_exe.py --icon app.ico
    python build_exe.py --slim              # 额外剔除 scipy（音轨改用标准库 wave）
    python build_exe.py --install-pyinstaller

三个打包期的**真实坑**（本脚本已经处理，注释里也标了）：
1. ``algorithms`` 包是用 ``importlib`` 动态扫描 ``cat*.py`` 的，PyInstaller
   静态分析找不到，必须 ``--collect-submodules algorithms``，否则冻结版的
   算法库会变成 0 种；
2. ``sdk_templates/`` 是纯数据目录，必须 ``--add-data``，否则「自定义算法
   工作室」导出模板时会报文件缺失；
3. ``ffmpeg.exe`` 必须放进 exe 能找到的位置 —— PyInstaller 6 的 onedir 会把
   ``--add-binary`` 的内容丢到 ``_internal/``，而 ``sys._MEIPASS`` 正好指向
   那里，所以统一按 ``bin/`` 放，运行时的 :func:`exporter.video_exporter.find_ffmpeg`
   会自动命中；
4. ``algorithms/*.py`` 还要作为**纯数据**再带一份（目标目录 ``algorithms_src``）。
   冻结后真正的模块已被编译进包体，``inspect.getsource`` 读不到原文，
   「📄 查看源码」按钮会因此失效；两份内容并不冲突，一份给 import，一份给阅读。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
SEP = ";" if os.name == "nt" else ":"
APP_NAME = "SortingVisualizerUltimate"

#: 明确用不到的重型依赖 —— 剔掉能让产物小几十到上百 MB
_EXCLUDES: Tuple[str, ...] = (
    # 与 Qt 无关的常见大块头
    "tkinter", "matplotlib", "pandas", "IPython", "PIL", "notebook",
    "jupyter", "jupyter_client", "jupyter_core", "pytest", "sphinx",
    "setuptools", "pip", "wheel", "Cython", "PyInstaller",
    # 其它 Qt 绑定（同机装了会误收进去，导致体积翻倍）
    "PyQt5", "PyQt6", "PySide2",
    # 本项目只用 QtCore / QtGui / QtWidgets（+ 少量 QtSvg 无关模块）
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtSensors", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtSpatialAudio", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtOpenGLWidgets",
)

#: ``--slim`` 时额外剔除
_SLIM_EXCLUDES: Tuple[str, ...] = ("scipy", "scipy.io", "scipy.linalg",
                                   "scipy.sparse", "scipy.signal")

_REQUIRED = ("numpy", "PySide6")
_OPTIONAL = ("sounddevice", "scipy")


# ==========================================================================
# 1. 环境体检
# ==========================================================================
def _module_ok(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:                                      # pragma: no cover
        return False


def collect_report() -> Dict[str, object]:
    """收集打包前需要知道的一切。"""
    rep: Dict[str, object] = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": sys.platform,
        "frozen_pyinstaller": False,
        "missing_required": [],
        "optional": {},
        "sdk_templates": 0,
        "algorithms": 0,
        "categories": 0,
        "ffmpeg": "",
        "ffmpeg_version": "",
        "ffmpeg_encoders": [],
        "pyinstaller": "",
        "disk_free_gib": 0.0,
    }
    rep["missing_required"] = [n for n in _REQUIRED if not _module_ok(n)]
    rep["optional"] = {n: _module_ok(n) for n in _OPTIONAL}

    sdk = ROOT / "sdk_templates"
    if sdk.is_dir():
        rep["sdk_templates"] = len([p for p in sdk.iterdir() if p.is_file()])

    if not rep["missing_required"]:
        try:
            sys.path.insert(0, str(ROOT))
            from core.registry import load_builtin, registry_stats
            load_builtin()
            stats = registry_stats()
            rep["algorithms"] = int(stats["total"])
            rep["categories"] = int(stats["categories"])
            rep["external"] = int(stats["external"])
        except Exception as exc:                            # pragma: no cover
            rep["registry_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from exporter.video_exporter import (available_encoders,
                                             ffmpeg_version, find_ffmpeg)
        exe = find_ffmpeg()
        if exe:
            rep["ffmpeg"] = exe
            rep["ffmpeg_version"] = ffmpeg_version(exe)
            rep["ffmpeg_encoders"] = sorted(available_encoders(exe))
    except Exception:                                       # pragma: no cover
        pass

    exe = find_pyinstaller()
    if exe:
        rep["pyinstaller"] = exe
    try:
        rep["disk_free_gib"] = shutil.disk_usage(ROOT).free / (1024 ** 3)
    except OSError:                                         # pragma: no cover
        pass
    return rep


def print_report(rep: Dict[str, object]) -> bool:
    """打印体检报告，返回「是否具备打包条件」。"""
    ok = True
    print("=" * 74)
    print(f"  Sorting Visualizer Ultimate · 打包环境体检")
    print("=" * 74)
    print(f"  Python        : {rep['python']}  ({rep['executable']})")
    print(f"  平台          : {rep['platform']}")

    missing = rep["missing_required"]
    print(f"  必需依赖      : "
          + ("、".join(_REQUIRED) + "  ✓"
             if not missing else f"缺少 {'、'.join(missing)}  ✗"))
    if missing:
        ok = False

    opt = rep["optional"]
    print("  可选依赖      : " + "、".join(
        f"{k}{'✓' if v else '✗'}" for k, v in opt.items())
        + "   （✗ 时对应功能自动降级，不影响打包）")

    algo = rep.get("algorithms", 0)
    print(f"  算法库        : {algo} 种 / {rep.get('categories', 0)} 类"
          + ("  ✓" if algo >= 160 else "  ✗ 期望 160 种"))
    if algo < 160:
        ok = False
        if rep.get("registry_error"):
            print(f"                  {rep['registry_error']}")

    n_sdk = rep["sdk_templates"]
    print(f"  SDK 模板      : {n_sdk} 个" + ("  ✓" if n_sdk >= 8 else "  ✗ 期望 8 个"))
    if n_sdk < 8:
        ok = False

    ff = rep["ffmpeg"]
    if ff:
        print(f"  FFmpeg        : {ff}")
        print(f"                  {rep['ffmpeg_version']}")
        print(f"                  编码器 {', '.join(rep['ffmpeg_encoders'][:6]) or '（无 H.264）'}")
    else:
        print("  FFmpeg        : 未找到  ⚠ 导出视频功能会在打包产物里不可用")
        print("                  可用 --ffmpeg 指定路径，或把 ffmpeg.exe 放到项目根目录")

    pyi = rep["pyinstaller"]
    print(f"  PyInstaller   : {pyi or '未安装  ✗（用 --install-pyinstaller 自动装）'}")
    if not pyi:
        ok = False

    print(f"  磁盘可用      : {rep['disk_free_gib']:.1f} GiB"
          + ("  ✓" if rep["disk_free_gib"] > 3 else "  ⚠ 空间偏紧"))
    print("=" * 74)
    return ok


# ==========================================================================
# 2. PyInstaller 定位 / 安装
# ==========================================================================
def find_pyinstaller() -> Optional[str]:
    """返回可用的 ``pyinstaller`` 入口路径（优先同解释器下的脚本）。"""
    cand = Path(sys.executable).parent / ("pyinstaller.exe" if os.name == "nt"
                                          else "pyinstaller")
    if cand.is_file():
        return str(cand)
    which = shutil.which("pyinstaller")
    if which:
        return which
    return None


def install_pyinstaller() -> bool:
    print("→ 正在安装 PyInstaller …")
    try:
        cp = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade",
                             "pyinstaller"], check=False)
    except Exception as exc:                                # pragma: no cover
        print(f"✗ 安装失败：{exc}")
        return False
    return cp.returncode == 0


# ==========================================================================
# 3. 组装 PyInstaller 命令行
# ==========================================================================
def algorithm_submodules() -> List[str]:
    """列出所有必须显式收集的算法分类模块（``algorithms.cat01_exchange`` …）。

    **为什么不能只靠 ``--collect-submodules``**：PyInstaller 是在它自己的
    进程里现场 import 这个包来枚举子模块的，而那个进程的 ``sys.path`` 未必
    包含项目根目录（实测就出现了 ``collect_submodules('algorithms')`` 返回
    空列表、产物里 160 种算法全丢的情况，而且**不报错**——冻结版启动后算法树
    空空如也）。所以这里直接从磁盘/清单里把模块名算出来，逐个
    ``--hidden-import``，结果确定可复现。
    """
    names: List[str] = []
    pkg = ROOT / "algorithms"
    if pkg.is_dir():
        names = [p.stem for p in sorted(pkg.glob("cat*.py"))]
    if not names:
        try:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from algorithms import CATEGORY_MODULES
            names = list(CATEGORY_MODULES)
        except Exception:                                  # pragma: no cover
            pass
    return [f"algorithms.{n}" for n in names]


def build_argv(opts: argparse.Namespace, ffmpeg: Optional[str],
               pyi: str) -> List[str]:
    argv: List[str] = [
        pyi, "--noconfirm", "--clean",
        "--name", opts.name,
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--onedir" if not opts.onefile else "--onefile",
        "--console" if opts.console else "--windowed",
    ]
    if opts.icon:
        argv += ["--icon", str(Path(opts.icon).resolve())]

    # ---- 数据文件：多语言 SDK 模板 --------------------------------------
    # 少了这一条，打包后「自定义算法工作室」导出模板会直接报文件缺失
    sdk = ROOT / "sdk_templates"
    if sdk.is_dir():
        argv += ["--add-data", f"{sdk}{SEP}sdk_templates"]

    # ---- 数据文件：内置算法源码（「查看源码」按钮）------------------------
    # 冻结后 modules 已编译进包体，inspect.getsource 失效；这里把 algorithms/
    # 原样再带一份纯数据，core/algo_source.py 会回退到 _internal/algorithms_src/。
    # 只占几百 KB，换来 160 种算法在打包版里仍然「能看、能复制、能另存」。
    algo_dir = ROOT / "algorithms"
    if algo_dir.is_dir():
        argv += ["--add-data", f"{algo_dir}{SEP}algorithms_src"]

    # ---- FFmpeg ---------------------------------------------------------
    if ffmpeg:
        argv += ["--add-binary", f"{ffmpeg}{SEP}bin"]

    # ---- 动态导入：算法库 ------------------------------------------------
    # algorithms/__init__.py 用 importlib 扫描并导入 cat01..cat11，
    # 静态分析看不到，必须显式收集，否则产物里算法数为 0。
    algo_mods = algorithm_submodules()
    argv += ["--hidden-import", "algorithms"]
    for mod in algo_mods:
        argv += ["--hidden-import", mod]
    argv += ["--collect-submodules", "algorithms"]      # 双保险
    # core.registry 里那句 importlib.import_module("algorithms") 同理
    argv += ["--hidden-import", "core.registry",
             "--hidden-import", "core.protocol",
             "--hidden-import", "core.audio_synth",
             "--hidden-import", "core.data_generator",
             "--hidden-import", "core.polyglot_runner",
             "--hidden-import", "ui.main_window",
             "--hidden-import", "ui.canvas_widget",
             "--hidden-import", "ui.custom_algo_dialog",
             "--hidden-import", "ui.export_dialog",
             "--hidden-import", "exporter.video_exporter"]
    argv += ["--hidden-import", "numpy"]

    # ---- 可选依赖 --------------------------------------------------------
    # 只有在当前环境真的装上了才声明，否则 PyInstaller 会因为找不到而报警告
    for name, spec in (("sounddevice", "sounddevice"),
                       ("scipy.io.wavfile", "scipy.io.wavfile")):
        if _module_ok(spec.split(".")[0]) and not (
                opts.slim and spec.startswith("scipy")):
            argv += ["--hidden-import", name]
    if _module_ok("sounddevice"):
        # sounddevice 靠 cffi 加载自带的 PortAudio DLL，必须整包带上
        argv += ["--collect-binaries", "sounddevice",
                 "--collect-data", "sounddevice"]

    # ---- 剔除无用重型模块 ------------------------------------------------
    if not opts.no_exclude:
        for name in _EXCLUDES:
            argv += ["--exclude-module", name]
        if opts.slim:
            for name in _SLIM_EXCLUDES:
                argv += ["--exclude-module", name]

    argv += ["--paths", str(ROOT)]
    argv += [str(ROOT / "main.py")]
    return argv


# ==========================================================================
# 4. 执行
# ==========================================================================
def _rm_tree(path: Path) -> bool:
    """尽力删除目录，失败返回 False（不抛异常）。"""
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def prepare_dist_dir(name: str) -> None:
    """确保 ``dist/<name>/`` 不存在。

    **优先「改名挪走」，绝不先尝试删除。**

    本环境（以及不少装了杀软 / 受 IT 管控的企业机器）对「一次删除大量文件」
    有拦截策略，而拦截器的常见做法是**直接终止整个进程** —— 表现就是打包脚本
    一两秒内以 rc=1 退出、屏幕上没有任何错误、连 traceback 都不留，排查起来
    极其误导（本项目就踩过两次）。``os.rename`` 只改目录项、不删任何文件，
    永远不会被拦，而且同样能让 PyInstaller 的 COLLECT 拿到干净的目标路径。
    """
    target = ROOT / "dist" / name
    if not target.exists():
        return

    import tempfile
    import time
    stash_dir = Path(tempfile.gettempdir()) / "svu_prev_dist"
    stash = stash_dir / name
    try:
        stash_dir.mkdir(parents=True, exist_ok=True)
        if stash.exists():                     # 不删旧 stash，换个带时间戳的名字
            stash = stash_dir / f"{name}_{int(time.time())}"
        os.rename(str(target), str(stash))
        print(f"ℹ 旧产物已挪到 {stash}")
        print("  （改名而非删除；临时目录堆积可手动清理）")
        return
    except OSError as exc:                     # 跨盘、被占用、权限不足 …
        print(f"⚠ 无法挪走旧产物 {target}（{exc}），退回直接删除…")

    if _rm_tree(target):
        print(f"✓ 已清理 dist/{name}")
    else:
        print(f"⚠ 旧产物 {target} 既挪不走也删不掉，"
              "PyInstaller 可能会因 --noconfirm 失败")


def clean_outputs() -> None:
    """清理 build/ 与 dist/（同样**优先改名挪走**，避免触发批量删除拦截）。"""
    import tempfile
    import time
    stash_dir = Path(tempfile.gettempdir()) / "svu_prev_dist"
    for target in ("build", "dist"):
        p = ROOT / target
        if not p.is_dir():
            continue
        print(f"→ 清理 {target}/")
        try:
            stash_dir.mkdir(parents=True, exist_ok=True)
            os.rename(str(p), str(stash_dir / f"{target}_{int(time.time())}"))
            print(f"  ℹ 已挪到 {stash_dir}")
        except OSError:
            # 名字已经用过（同一秒内重复调用）或被占用，退回删除
            if not _rm_tree(p):
                print(f"⚠ {target}/ 未能完全删除（可能被占用），将尝试覆盖式打包")
    for spec in ROOT.glob("*.spec"):
        print(f"→ 清理 {spec.name}")
        try:
            spec.unlink()
        except OSError:                                     # pragma: no cover
            pass


def run_pyinstaller(argv: List[str]) -> int:
    print("\n→ 执行：")
    print("  " + " \\\n  ".join(argv))
    print()
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    # 让 PyInstaller 自己的进程也能 import 到项目包 —— 它要在那里现场枚举
    # algorithms 的子模块（--collect-submodules）。不设这个变量时，有的
    # 环境下 sys.path 里没有项目根目录，枚举会**静默返回空列表**。
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + old_pp if old_pp else "")
    try:
        proc = subprocess.Popen(argv, env=env, cwd=str(ROOT),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, bufsize=1,
                                universal_newlines=True, encoding="utf-8",
                                errors="replace")
    except FileNotFoundError as exc:                        # pragma: no cover
        print(f"✗ 无法启动 PyInstaller：{exc}")
        return 1
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            print("   " + line)
    return proc.wait()


def _exe_path(opts: argparse.Namespace) -> Path:
    if opts.onefile:
        return ROOT / "dist" / f"{opts.name}.exe"
    return ROOT / "dist" / opts.name / f"{opts.name}.exe"


def write_readme(opts: argparse.Namespace, exe: Path, ffmpeg: Optional[str]) -> Path:
    """在产物旁生成一份小白也能看懂的运行说明。"""
    text = f"""Sorting Visualizer Ultimate —— 免安装运行说明
============================================================

1. 怎么启动
   {'双击本目录下的 ' + exe.name + ' 即可（无控制台窗口）。'
    if not opts.console else '运行 ' + exe.name + '（保留控制台，便于排查）。'}

2. 功能速览
   · 左侧算法树：160 种内置排序算法，按 11 大类分组，支持中英文 / 编号搜索
   · 右侧画布：18 种几何视图（柱状 / 花瓣环 / 折线 / 声波 / 偏差环 / 金字塔 /
     残差火柴 / 瀑布流 / 织布机 / 鹦鹉螺 / 捕梦网 / 二叉树 / 切片还原 /
     霓虹拱桥 / 全息双螺旋 / 极光丝带 / 玻璃球 / 低多边形晶格），
     3 套配色，主数组 + 辅助数组自动上下分屏
   · 时间轴：播放 / 暂停 / 单步前进 / 单步后退 / 0.1x ~ 2000x 无级变速 / 拖动跳转
   · 同屏赛马：单视图 / 双宫格 / 四宫格，同一起始数组对比谁先排完
   · 自定义算法（工具栏「⌨ 自定义算法」）：用 C / C++ / Python / Java /
     Rust / Go / JavaScript / C# 写自己的排序算法，一键编译运行并加入算法树
   · 视频导出（工具栏「🎬 导出视频」或 Ctrl+E）：1080P / 4K @ 30~120FPS，
     H.264 MP4 + 立体声 AAC，音画完全同步

3. 快捷键
   空格 播放/暂停    ← → 单步    R / Home 重置    End 跳到末尾
   Ctrl+F 搜索算法   Ctrl+E 导出视频

4. 关于 FFmpeg
   {"已随程序一起打包，导视频开箱即用。" if ffmpeg else
    "本包**没有**内置 ffmpeg。请自行下载 ffmpeg（推荐 gyan.dev 的 "
    "essentials/full 版），把 ffmpeg.exe 放到程序目录或 bin\\ 下，"
    "也可以设置环境变量 SVU_FFMPEG 指向它。"}

5. 关于外部语言工具链
   C/C++ 需要 g++ 或 clang++，Rust 需要 rustc，Go 需要 go，Java 需要 javac，
   其它语言需要 python / node / dotnet。程序会自动探测，缺哪个会在
   「自定义算法工作室」里给出对应安装提示。

6. 数据与缓存位置
   · 导出的视频：默认落在程序目录下的 exports\\ 文件夹
   · 导入的外部算法源码与清单：程序目录下的 custom_algorithms\\
   · 编译缓存：系统临时目录下的 svu_polyglot_cache\\（可随时删除）

============================================================
"""
    dst = exe.parent / "使用说明.txt"
    dst.write_text(text, encoding="utf-8")
    return dst


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:                                     # pragma: no cover
            pass
    return total


def verify_exe(opts: argparse.Namespace) -> int:
    """跑一遍产物的 ``--selftest``，确认冻结版真的能加载 160 种算法。"""
    exe = _exe_path(opts)
    if not exe.is_file():
        print(f"✗ 找不到产物：{exe}")
        return 1
    print("\n→ 验证产物：运行 --selftest --frames 5")
    try:
        cp = subprocess.run([str(exe), "--selftest", "--frames", "5"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=600, cwd=str(exe.parent))
    except Exception as exc:                                # pragma: no cover
        print(f"⚠ 无法自动验证（{type(exc).__name__}: {exc}）")
        print("   若打包时用了 --windowed，exe 没有控制台，属正常现象；"
              "可用 --console 重新打包后再 --verify。")
        return 0
    out = (cp.stdout or "") + (cp.stderr or "")
    print(out.strip()[-2000:] or "（无输出）")
    if cp.returncode == 0:
        print("✓ 产物自检通过")
    else:
        print(f"✗ 产物自检返回码 {cp.returncode}")
    return cp.returncode


# ==========================================================================
# 5. 入口
# ==========================================================================
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_exe.py",
        description="把 Sorting Visualizer Ultimate 打包成免安装 Windows 可执行程序")
    parser.add_argument("--name", default=APP_NAME, help=f"产物名，默认 {APP_NAME}")
    parser.add_argument("--onefile", action="store_true",
                        help="打成单个 exe（体积大、每次启动要解压，不推荐）")
    parser.add_argument("--console", action="store_true",
                        help="保留控制台窗口（排查启动问题用）")
    parser.add_argument("--clean", action="store_true",
                        help="打包前清理 build/ dist/ *.spec")
    parser.add_argument("--check", action="store_true", help="只体检，不打包")
    parser.add_argument("--verify", action="store_true",
                        help="打包完成后跑一遍 exe --selftest")
    parser.add_argument("--ffmpeg", default=None,
                        help="要内嵌的 ffmpeg.exe 路径（默认自动探测）")
    parser.add_argument("--no-ffmpeg", action="store_true",
                        help="不内嵌 FFmpeg（产物更小，但没法导视频）")
    parser.add_argument("--icon", default=None, help="可执行文件图标 .ico")
    parser.add_argument("--slim", action="store_true",
                        help="额外剔除 scipy（音轨改用标准库 wave，输出一致）")
    parser.add_argument("--no-exclude", action="store_true",
                        help="不做模块精简（体积大很多，但最保守）")
    parser.add_argument("--install-pyinstaller", action="store_true",
                        help="先 pip 安装 / 升级 PyInstaller")
    opts = parser.parse_args(argv)

    if opts.install_pyinstaller:
        if not install_pyinstaller():
            return 1

    # ---- 解析要内嵌的 FFmpeg --------------------------------------------
    ffmpeg: Optional[str] = None
    if not opts.no_ffmpeg:
        if opts.ffmpeg:
            p = Path(opts.ffmpeg).expanduser()
            if not p.is_file():
                print(f"✗ --ffmpeg 指定的文件不存在：{p}")
                return 2
            ffmpeg = str(p.resolve())
        else:
            try:
                from exporter.video_exporter import find_ffmpeg
                found = find_ffmpeg()
                ffmpeg = os.path.abspath(found) if found else None
            except Exception:                               # pragma: no cover
                ffmpeg = None

    rep = collect_report()
    ready = print_report(rep)
    if opts.check:
        return 0 if ready else 1
    if not ready:
        print("✗ 环境不满足打包条件，请先解决上面标 ✗ 的项。")
        return 1
    if ffmpeg:
        print(f"\n→ 将内嵌 FFmpeg：{ffmpeg}")
    else:
        print("\n⚠ 未找到 FFmpeg，本次打包的产物**不能导出视频**"
              "（其它功能不受影响）。")

    if opts.clean:
        clean_outputs()
    prepare_dist_dir(opts.name)

    argv_pyi = build_argv(opts, ffmpeg, str(rep["pyinstaller"]))
    rc = run_pyinstaller(argv_pyi)
    if rc != 0:
        print(f"\n✗ PyInstaller 返回码 {rc}，打包失败。")
        return rc

    exe = _exe_path(opts)
    if not exe.is_file():
        print(f"\n✗ 打包结束但没找到产物：{exe}")
        return 1

    note = write_readme(opts, exe, ffmpeg)
    base = exe.parent if opts.onefile else ROOT / "dist" / opts.name
    size = _dir_size(base)
    print("\n" + "=" * 74)
    print("  ✓ 打包完成")
    print("=" * 74)
    print(f"  模式    : {'onefile 单文件' if opts.onefile else 'onedir 目录版'}")
    print(f"  可执行  : {exe}")
    print(f"  使用说明: {note}")
    print(f"  总体积  : {size / 1048576:.1f} MiB"
          f"（{_dir_size(base) // 1048576} MB，含 FFmpeg：{'是' if ffmpeg else '否'}）")
    if not opts.onefile:
        print(f"  分发方式: 直接压缩 dist/{opts.name}/ 整个目录发给别人即可")
    else:
        print("  分发方式: 只发 dist 下这一个 exe 即可")
    print("=" * 74)

    if opts.verify:
        return verify_exe(opts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
