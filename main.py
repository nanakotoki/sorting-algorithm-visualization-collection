#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— 程序启动入口。

用法::

    python main.py                       # 打开图形界面
    python main.py --algo 076_dual_pivot_quicksort --n 512
    python main.py --list                # 列出全部 160 种算法后退出
    python main.py --selftest            # 无头自检（7 项，含 FFmpeg 导出链路）

    # 不进界面，直接把算法导成 1080P@60FPS 的 MP4
    python main.py --export out.mp4 --algo 076_dual_pivot_quicksort \\
                   --n 512 --duration 20 --res 1080p --fps 60

依赖：``PySide6``、``numpy``（必需），``sounddevice``、``scipy``（可选，
分别用于实时音效与 WAV 写出，缺失时自动降级）；视频导出另外需要
``ffmpeg`` 可执行文件（可用环境变量 ``SVU_FFMPEG`` 指定路径）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

# 保证以任意工作目录启动都能 import 到项目包
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _force_utf8_console() -> None:
    """把控制台输出强制切成 UTF-8（**必须在任何 print 之前调用**）。

    Windows 控制台默认是 GBK/cp936，而自检、导出日志里到处是 ``✓`` ``✗``
    ``←→`` 这类字符；更糟的是 PyInstaller 打出来的 exe 里 ``sys.stdout``
    继承的是 **OEM 代码页**，一 print 就
    ``UnicodeEncodeError: 'gbk' codec can't encode character '\\u2717'``
    直接把进程带崩 —— 打包产物「一跑就退」的经典死法。

    这里做三件事：
    1. ``reconfigure(encoding="utf-8", errors="replace")`` —— 就算终端不认
       UTF-8，也只会显示成乱码而不会抛异常；
    2. 顺手把 Windows 控制台的输出代码页切到 65001，让 cmd/PowerShell 里
       真正能正常显示中文与符号；
    3. ``--windowed`` 打包后**根本没有控制台**，此时 ``sys.stdout`` /
       ``sys.stderr`` 会是 ``None``，而任何一句 ``print()`` 都会
       ``AttributeError: 'NoneType' object has no attribute 'write'`` ——
       又一个「打包产物一跑就退」。这里用一个写向 ``os.devnull`` 的流顶上，
       让全部日志调用退化成安全的空操作。
    """
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:                              # pragma: no cover
            pass
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:                             # --windowed 打包时没有
            try:
                setattr(sys, name,
                        open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:                            # pragma: no cover
                pass
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # pragma: no cover
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_force_utf8_console()


def _warn(msg: str) -> None:
    """写诊断信息。

    PyInstaller ``--windowed`` 打包出来的 exe 没有控制台，``sys.stderr`` 会是
    ``None``；此时直接 ``sys.stderr.write`` 会抛 ``AttributeError`` 把程序带崩，
    所以统一走这个兜底函数。
    """
    for stream in (sys.stderr, sys.stdout):
        if stream is None:
            continue
        try:
            stream.write(msg)
            stream.flush()
            return
        except Exception:                              # pragma: no cover
            continue


def _fatal(msg: str) -> int:
    _warn("\n[启动失败] " + msg + "\n\n")
    return 2


def _check_deps() -> str:
    """返回空字符串表示依赖齐全，否则返回人类可读的缺失说明。"""
    missing = []
    try:
        import numpy  # noqa: F401
    except Exception:
        missing.append("numpy")
    try:
        import PySide6  # noqa: F401
    except Exception:
        missing.append("PySide6")
    if missing:
        return ("缺少必需依赖：" + "、".join(missing)
                + "\n请先执行：pip install -r requirements.txt"
                + "\n（若只想跑无头自检，仍需要 numpy 与 PySide6）")
    return ""


# --------------------------------------------------------------------------
# 无头自检
# --------------------------------------------------------------------------
def run_selftest(n: int = 128, verbose: bool = True, frames: int = 60) -> int:
    """不创建可见窗口地验证渲染内核、音效合成与算法录制链路。

    这是一个**离线可跑**的冒烟测试：离屏渲染全部 18 种几何样式、合成整条音轨、
    抽查若干算法确认能录出非空且排序正确的指令流，最后实测稳态渲染帧率。
    """
    import numpy as np

    # 次世代矢量视图（slice / arcs / helix3d / aurora / orbs / crystal）要用
    # QPainter 往 QImage 上画，而 QPainter 的渐变与字形都要先有 Qt 平台。
    # 这里在**任何渲染之前**建好 QGuiApplication —— 桌面环境直接可用，
    # 无显示环境（CI）退回离屏平台即可，QImage 绘制两者都支持。
    try:
        from PySide6.QtGui import QGuiApplication
        _qapp = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        if _qapp is None:                               # pragma: no cover
            raise RuntimeError("QGuiApplication 创建失败")
    except Exception as exc:                            # pragma: no cover
        print(f"[0/7] ✗ Qt 平台初始化失败：{exc}")
        return 1

    from core.audio_synth import AudioSynth, OfflineTrack, value_to_freq
    from core.data_generator import generate
    from core.protocol import TracePlayer, is_sorted_values, record
    from core.registry import all_algos, load_builtin
    from ui.canvas_widget import STYLES, VizFrame, make_renderer, render_frame_to_array

    ok = True
    bad: list = []

    # ---- 1. 算法库 ------------------------------------------------------
    total = load_builtin()
    metas = all_algos()
    if verbose:
        print(f"[1/7] 算法库加载：{total} 种（all_algos 返回 {len(metas)} 条）")
    if total != 160:
        print(f"      ✗ 期望 160 种，实际 {total} 种")
        ok = False

    # 「查看源码」功能依赖源码可读：开发态直接读 algorithms/*.py，
    # 冻结态回退到 _internal/algorithms_src/（build_exe.py 的 --add-data）。
    # 这里把 160 条全部走一遍 resolve_source，打包漏了数据目录会立刻暴露。
    from core.algo_source import SourceUnavailable, resolve_source
    src_bad: list = []
    for m in metas:
        try:
            bundle = resolve_source(m)
        except SourceUnavailable as exc:
            src_bad.append(f"#{m.index:03d} 源码不可用：{exc}")
            continue
        if "def " not in bundle.code:
            src_bad.append(f"#{m.index:03d} 源码为空")
    if verbose:
        print(f"      查看源码：{len(metas) - len(src_bad)}/{len(metas)} 可取用"
              + ("（AST 切块 + 辅助函数补全）" if not src_bad
                 else f"，失败 {len(src_bad)} 条"))
    if src_bad:
        ok = False
        bad.extend(src_bad[:3])

    # ---- 2. 录制 + 回放 -------------------------------------------------
    samples = [m for m in metas if m.index in (1, 24, 62, 76, 100, 137, 138, 145, 160)]
    for meta in samples:
        vals = generate("random", n, seed=20261016)
        tr = record(meta.func, vals, max_ops=4_000_000)
        if tr.n_ops == 0:
            bad.append(f"#{meta.index:03d} 指令流为空")
            continue
        p = TracePlayer(tr, vals)
        p.run_to_end()
        if not is_sorted_values(p.data):
            bad.append(f"#{meta.index:03d} 回放后未排好")
        p.seek(0)
        if p.data != vals:
            bad.append(f"#{meta.index:03d} 回溯到 0 步状态不一致")
    if verbose:
        print(f"[2/7] 录制与回溯：抽查 {len(samples)} 种，" +
              ("全部通过 ✓" if not bad else "失败 " + "; ".join(bad)))
    if bad:
        ok = False

    # ---- 3. 离屏渲染 ----------------------------------------------------
    vals = generate("sawtooth", min(n, 257), seed=7)
    frame = VizFrame(values=vals, aux=vals[: max(1, len(vals) // 3)],
                     aux_active=True, marks={"PIVOT": {3}, "SORTED": set(range(0, 5))},
                     hot={3: "cmp", 7: "swap"}, hot_aux={1: "aux_set"},
                     n_max=max(vals), palette="rainbow", sweep=0.4)
    times = {}
    for key, _label in STYLES:
        t0 = time.perf_counter()
        arr = render_frame_to_array(frame, 900, 520, key)
        times[key] = (time.perf_counter() - t0) * 1000.0
        if arr.shape != (520, 900, 3) or arr.dtype != np.uint8 or arr.max() == 0:
            bad.append(f"{key} 渲染结果异常")
    dense = VizFrame(values=generate("random", 4000, seed=1), n_max=4000)
    t0 = time.perf_counter()
    arr = render_frame_to_array(dense, 900, 520, "bars")
    dense_ms = (time.perf_counter() - t0) * 1000.0
    if arr.max() == 0:
        bad.append("稠密模式渲染结果全黑")
    if verbose:
        detail = "  ".join(f"{k}:{v:.1f}ms" for k, v in times.items())
        print(f"[3/7] 离屏渲染 900x520（含主辅分屏）：{detail}   稠密 N=4000:"
              f"{dense_ms:.1f}ms")

    # ---- 4. 音效 --------------------------------------------------------
    synth = AudioSynth(enabled=False)
    trk = OfflineTrack()
    for k, v in enumerate(vals[:40]):
        trk.add_value(k * 0.03, v, max(vals))
    trk.add_finish_chord(1.4, 8)
    wave = trk.render(2.2)
    peak = float(np.abs(wave).max())
    expect = int(2.2 * 44100)
    if not (expect <= wave.shape[0] <= expect + 1) or wave.shape[1] != 2 or peak > 1.0:
        bad.append(f"离线音轨异常 shape={wave.shape} peak={peak:.3f}")
    if verbose:
        print(f"[4/7] 音频合成：{wave.shape[0]} 采样 × {wave.shape[1]} 声道，"
              f"峰值 {peak:.3f}（未削波），"
              f"数值 1→{value_to_freq(1, 999):.0f}Hz / 999→{value_to_freq(999, 999):.0f}Hz")
        print(f"      实时后端：sounddevice={synth.available}  {synth.error or '可用'}")
    synth.close()

    # ---- 5. 稳态帧率 ----------------------------------------------------
    if frames > 0:
        w, h = 1180, 620                      # 与默认窗口下的画布尺寸一致
        big = VizFrame(values=generate("random", 10000, seed=3),
                       aux=generate("random", 5000, seed=4), aux_active=True,
                       marks={"PIVOT": {9}, "SORTED": set(range(20))},
                       hot={1: "cmp", 2: "swap"}, n_max=10000, palette="rainbow")
        rows = []
        for key, _label in STYLES:
            r = make_renderer(key, w, h)
            r.render(big)                     # 预热（构建极坐标缓存等）
            t0 = time.perf_counter()
            for _ in range(frames):
                r.render(big)
            ms = (time.perf_counter() - t0) / frames * 1000.0
            rows.append((key, ms, 1000.0 / ms if ms > 0 else 0.0))
        if verbose:
            print(f"[5/7] 稳态渲染 {w}x{h}，N=10000（{frames} 帧均值）：")
            for key, ms, fps in rows:
                mark = "✓" if fps >= 60 else "△"
                print(f"        {mark} {key:8s} {ms:6.2f} ms  -> {fps:6.1f} FPS")
        slow = [k for k, _ms, fps in rows if fps < 60]
        if slow:
            ok = False
            bad.append("以下样式未达 60 FPS：" + ", ".join(slow))

    # ---- 6. 多语言自定义算法引擎 ----------------------------------------
    from core.polyglot_runner import (LANGUAGES, detect_toolchains, run_source,
                                      sdk_dir, template_source)

    missing = [s.template for s in LANGUAGES
               if not (sdk_dir() / s.template).is_file()]
    if missing:
        ok = False
        bad.append("SDK 模板缺失：" + ", ".join(missing))

    tc = detect_toolchains(force=True)
    ready = [s.key for s in LANGUAGES if tc[s.key].available]
    # 只实测前两种可用语言（脚本 + 一种编译型），兼顾覆盖面与自检耗时
    order = ["python", "java", "cpp", "c", "rust", "go", "js", "cs"]
    probes = [k for k in order if k in ready][:2]
    external_ok: List[str] = []
    for key in probes:
        try:
            out = run_source(key, template_source(key),
                             generate("random", 48, seed=5), timeout=180)
        except Exception as exc:                      # noqa: BLE001
            ok = False
            bad.append(f"{key} 模板运行抛异常：{type(exc).__name__}: {exc}")
            continue
        if not out.ok or not out.stats.sorted_ok or out.stats.bad_lines:
            ok = False
            bad.append(f"{key} 模板未跑通：ops={out.ops} "
                       f"sorted={out.stats.sorted_ok} bad={out.stats.bad_lines} "
                       f"rc={out.stats.returncode} err={(out.error or '')[:80]}")
        else:
            external_ok.append(f"{key}:{out.ops} 条指令")
    if verbose:
        print(f"[6/7] 多语言引擎：SDK 模板 {len(LANGUAGES) - len(missing)}/"
              f"{len(LANGUAGES)} 就位；工具链就绪 {len(ready)} 种"
              f"（{' / '.join(ready) or '无'}）")
        if external_ok:
            print("      模板实测（" + " / ".join(external_ok)
                  + "）→ 编译 + 运行 + 指令流翻译 + 排序校验 全部通过 ✓")
        else:
            print("      模板实测：本机没有可用工具链，已跳过")

    # ---- 7. FFmpeg 离线导出（Batch 6）--------------------------------------
    step7 = _selftest_export(verbose)
    if step7 is None:
        pass                                        # 无 FFmpeg / 无 Qt，已提示
    elif not step7:
        ok = False
        bad.append("离线视频导出未通过（详见上一行输出）")

    if bad:
        if verbose:
            print("\n问题清单：")
            for b in bad:
                print("  ✗ " + b)
    print("\n自检结果：" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    return 0 if ok else 1


def _selftest_export(verbose: bool = True) -> "bool | None":
    """自检第 7 关：真跑一遍 FFmpeg 导出链路。

    返回 ``True`` / ``False`` 表示通过与否，``None`` 表示环境不具备（缺 FFmpeg
    或 Qt 平台起不来）——这种情况只提示、不算失败，否则一个没装 FFmpeg 的
    机器上整个自检都会红。
    """
    from exporter.video_exporter import (ExportSettings, choose_encoder,
                                         export_video, find_ffmpeg)

    exe = find_ffmpeg()
    if not exe:
        if verbose:
            print("[7/7] FFmpeg 离线导出：本机未找到 FFmpeg，已跳过"
                  "（可用 SVU_FFMPEG 环境变量指定路径）")
        return None
    try:
        from PySide6.QtGui import QGuiApplication
        qapp = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    except Exception as exc:                            # pragma: no cover
        if verbose:
            print(f"[7/7] FFmpeg 离线导出：Qt 平台初始化失败（{exc}），已跳过")
        return None
    if qapp is None:                                    # pragma: no cover
        return None

    import tempfile

    from core.data_generator import generate
    from core.protocol import is_sorted_values, record
    from core.registry import all_algos

    meta = next((m for m in all_algos() if m.index == 76), all_algos()[0])
    vals = generate("random", 64, seed=99)
    trace = record(meta.func, vals)
    out = os.path.join(tempfile.gettempdir(), "svu_selftest_export.mp4")
    # 320x240 是本自检能用的最小合法分辨率（H.264 要求宽高为偶数），
    # 20 帧上下即可跑完「音轨合成 → 逐帧渲染 → 管道推流 → 封装」全链路。
    st = ExportSettings(width=320, height=240, fps=20, duration=1.0,
                        hold_head=0.1, hold_tail=0.3, style="bars",
                        palette="rainbow", crf=30, preset="ultrafast",
                        hot_window=8, output=out)
    problems = st.validate()
    if problems:                                        # pragma: no cover
        if verbose:
            print(f"[7/7] FFmpeg 离线导出：参数非法 {problems}")
        return False
    try:
        encoder, _args = choose_encoder(exe, st.encoder, crf=30,
                                        preset="ultrafast")
        res = export_video(meta=meta, values=vals, trace=trace, settings=st,
                           n_value=len(vals))
    except Exception as exc:                            # noqa: BLE001
        if verbose:
            print(f"[7/7] FFmpeg 离线导出：✗ {type(exc).__name__}: {exc}")
        return False
    finally:
        pass

    good = (res.frames == st.frames and res.bytes_written > 0
            and os.path.isfile(res.output))
    if verbose:
        mark = "✓" if good else "✗"
        print(f"[7/7] FFmpeg 离线导出：{mark} {os.path.basename(res.output)} "
              f"{res.width}×{res.height}@{res.fps} · {res.frames}/{st.frames} 帧 · "
              f"{res.mib:.2f} MiB · 编码器 {res.encoder} · "
              f"音轨 {res.audio_seconds:.2f}s · 耗时 {res.elapsed:.1f}s")
    try:
        os.remove(res.output)
    except OSError:                                     # pragma: no cover
        pass
    return good


# --------------------------------------------------------------------------
# 无头导出（命令行一键出片）
# --------------------------------------------------------------------------
def run_export(args) -> int:
    """``--export`` 的实现：不进 GUI，直接把算法导出成 MP4。

    这条通路和界面里的「🎬 导出视频」**共用同一个引擎**
    （``exporter.video_exporter.export_video``），因此适合在 CI /
    无头服务器上做回归，也方便批量出片。
    """
    if not args.algo:
        _warn("[导出] 需要同时指定 --algo（例如 --algo 076_dual_pivot_quicksort）\n")
        return 2

    from exporter.video_exporter import (ExportSettings, export_video,
                                         ffmpeg_report, find_ffmpeg)

    rep = ffmpeg_report()
    if not rep["available"]:
        _warn("[导出] " + str(rep["note"]) + "\n")
        return 2
    if not rep["encoders"]:
        _warn(f"[导出] {rep['note']}\n")
        return 2

    # Qt 平台必须在任何 QPainter / QFont 之前建好；桌面环境直接可用，
    # 无显示环境（CI）退回离屏平台（离屏字体库是空的，HUD 文字会退化成
    # 方块 —— 但导出链路本身仍然完整可验证）。
    try:
        from PySide6.QtGui import QGuiApplication
        qapp = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    except Exception as exc:                            # pragma: no cover
        _warn(f"[导出] Qt 平台初始化失败：{exc}\n"
                         "        可尝试设置 QT_QPA_PLATFORM=offscreen\n")
        return 2
    if qapp is None:                                    # pragma: no cover
        return 2

    from core.data_generator import generate
    from core.protocol import ensure_deep_recursion, is_sorted_values, record
    from core.registry import all_algos, load_builtin

    ensure_deep_recursion()
    load_builtin()
    meta = next((m for m in all_algos() if m.algo_id == args.algo), None)
    if meta is None:
        _warn(f"[导出] 找不到算法：{args.algo}（用 --list 查看全部 ID）\n")
        return 2

    n = max(8, min(10000, int(args.n)))
    vals = generate(args.dist, n, seed=args.seed)
    t0 = time.perf_counter()
    trace = record(meta.func, vals)
    sys.stdout.write(f"[导出] #{meta.index:03d} {meta.name_zh}  N={n}  "
                     f"{trace.n_ops:,} 步指令流（录制 {time.perf_counter() - t0:.3f}s）"
                     f"  有序={is_sorted_values(_replay_end(trace, vals))}\n")

    settings = ExportSettings.for_resolution(
        args.res, fps=int(args.fps), duration=float(args.duration),
        style=args.style, palette=args.palette, easing=args.easing,
        audio=not args.no_audio, show_hud=not args.no_hud,
        encoder=args.encoder, crf=int(args.crf), preset=args.preset)
    settings.output = args.export
    problems = settings.validate()
    if problems:
        _warn("[导出] 参数不合法：" + "；".join(problems) + "\n")
        return 2

    last = [0.0]

    def _progress(p) -> None:
        now = time.perf_counter()
        if p.stage != "render" or now - last[0] >= 0.5:
            last[0] = now
            sys.stdout.write(f"\r[导出] {p.stage:7s} {p.text():<58s}")
            sys.stdout.flush()

    try:
        res = export_video(meta=meta, values=vals, trace=trace,
                           settings=settings, n_value=n, dist_kind=args.dist,
                           on_progress=_progress)
    except Exception as exc:                            # noqa: BLE001
        sys.stdout.write("\n")
        _warn(f"[导出] 失败：{type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write("\n")
    print(res.summary())
    if res.cancelled:
        return 1
    print(f"文件：{res.output}")
    return 0


def _replay_end(trace, values) -> list:
    """回放到底拿到最终数组（仅用于导出前的正确性确认）。"""
    from core.protocol import TracePlayer
    p = TracePlayer(trace, values)
    p.run_to_end()
    return p.data


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="SortingVisualizerUltimate",
        description="160 种排序算法的高性能可视化桌面系统")
    parser.add_argument("--algo", default=None, metavar="ALGO_ID",
                        help="启动时选中的算法 ID，例如 076_dual_pivot_quicksort")
    parser.add_argument("--n", type=int, default=128,
                        help="初始数据量（8 ~ 10000），默认 128")
    parser.add_argument("--dist", default="random",
                        help="初始数据分布键，例如 random / reversed / sawtooth")
    parser.add_argument("--style", default="bars",
                        help="几何视图键：bars / wheel / scatter / mirror / "
                             "disparity / pyramid / residual / waterfall / "
                             "loom / nautilus / dreamcatcher / tree / "
                             "slice / arcs / helix3d / aurora / orbs / crystal")
    parser.add_argument("--list", action="store_true",
                        help="仅列出全部算法（含编号、中文名、复杂度）后退出")
    parser.add_argument("--selftest", action="store_true",
                        help="无头自检：渲染 + 音频 + 算法录制 + 多语言引擎 + 视频导出")
    parser.add_argument("--frames", type=int, default=60,
                        help="配合 --selftest：额外渲染的帧数，用于测帧率")
    parser.add_argument("--seed", type=int, default=20261016,
                        help="初始数据随机种子，默认 20261016")

    grp = parser.add_argument_group("离线视频导出（不进 GUI，直接出片）")
    grp.add_argument("--export", default=None, metavar="OUT.mp4",
                     help="导出路径；给定时不打开界面，导出完即退出")
    grp.add_argument("--duration", type=float, default=15.0,
                     help="目标视频总时长（秒），默认 15")
    grp.add_argument("--fps", type=int, default=60,
                     help="帧率 30 / 60 / 120，默认 60")
    grp.add_argument("--res", default="1080p",
                     help="分辨率 1080p / 1440p / 4k，默认 1080p")
    grp.add_argument("--palette", default="rainbow",
                     help="配色 white / gradient / rainbow，默认 rainbow")
    grp.add_argument("--easing", default="ease_in_out",
                     help="缓动 linear / ease_in_out / slow_tail / slow_head")
    grp.add_argument("--encoder", default="auto",
                     help="编码器 auto / libx264 / h264_nvenc / h264_qsv / h264_amf")
    grp.add_argument("--crf", type=int, default=18,
                     help="x264 画质（越小越清晰），默认 18")
    grp.add_argument("--preset", default="medium",
                     help="x264 预设 ultrafast ~ slow，默认 medium")
    grp.add_argument("--no-audio", action="store_true", help="不导出音轨")
    grp.add_argument("--no-hud", action="store_true", help="不叠加 HUD 看板")
    args = parser.parse_args(argv)

    problem = _check_deps()
    if problem:
        return _fatal(problem)

    if args.list:
        from core.registry import all_algos, load_builtin, registry_stats
        total = load_builtin()
        stats = registry_stats()
        print(f"共 {total} 种算法 / {stats['categories']} 大分类\n")
        cat = ""
        for m in all_algos():
            if m.category != cat:
                cat = m.category
                print(f"\n=== {cat} ===")
            print(f"  #{m.index:03d}  {m.name_zh:24s} {m.name_en:44s} "
                  f"{m.time_avg:>12s}  {m.space:>10s}  "
                  f"{'Stable' if m.stable else 'Unstable'}")
        return 0

    if args.selftest:
        return run_selftest(n=max(8, min(10000, args.n)),
                            frames=max(0, args.frames))

    if args.export:
        return run_export(args)

    from core.protocol import ensure_deep_recursion
    ensure_deep_recursion()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    # Qt6 默认即为高 DPI 感知，这里只补一个平滑缩放的图像策略
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Sorting Visualizer Ultimate")
    app.setOrganizationName("SortingVisualizerUltimate")

    from ui.main_window import MainWindow, apply_theme
    from ui.canvas_widget import STYLES as _STYLES
    from core.data_generator import DISTRIBUTIONS as _DISTS

    apply_theme(app)

    win = MainWindow(start_algo=args.algo, start_n=max(8, min(10000, args.n)))
    didx = next((i for i, (k, _) in enumerate(_DISTS) if k == args.dist), None)
    if didx is not None:
        win.combo_dist.setCurrentIndex(didx)
    sidx = next((i for i, (k, _) in enumerate(_STYLES) if k == args.style), None)
    if sidx is not None:
        win.combo_style.setCurrentIndex(sidx)

    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
