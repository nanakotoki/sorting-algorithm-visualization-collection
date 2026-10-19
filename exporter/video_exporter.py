# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— 离线高清视频导出器（FFmpeg 管道 + 音画同步）。

规范书 6.1 落地
---------------
* **分辨率**：1920×1080 / 2560×1440 / 3840×2160，帧率 30 / 60 / 120 FPS。
* **目标时长**：把整个排序过程**平滑浓缩**为 10 / 15 / 20 / 30 / 45 / 60 秒，
  开头保留 0.6 s 初始状态、结尾附带 **1.5 s 翠绿扫光定格**。
* **离屏渲染管道**：完全绕开窗口系统，用 :func:`ui.canvas_widget.render_frame_to_array`
  的 NumPy 向量化内核逐帧绘制高清位图，再用 ``QPainter`` 在**同一块 RGB 缓冲**
  上叠加 HUD 看板与底部进度条，最后把整块缓冲按 ``rawvideo/rgb24`` 推进
  FFmpeg 的 stdin。
* **音画完全同步**：导出前一次性把整条时间轴的音符合成成 16 bit 立体声 WAV，
  再作为第二个输入交给 FFmpeg。视频时间轴与音频时间轴由**同一个帧号映射**
  推导，因此不存在逐帧抖动或累积漂移。

为什么「绝不掉帧」
------------------
本导出器写入 FFmpeg 的是**无时间戳的裸帧流**，输出帧率完全由
``-framerate 60`` 决定：

* 每一帧都会被 ``stdin.write`` 写出去，我们**不跳过、不重复**任何一帧；
* 如果编码器跑得比实时慢，管道自然阻塞，我们的写入线程就等着 ——
  代价是导出耗时变长，而**不是**丢帧。

这与「边播边录」的方案有本质区别：后者会因为渲染跟不上播放时钟而丢帧。

依赖
----
``ffmpeg`` 可执行文件（自动在 PATH、程序目录、``bin/``、常见安装位置与
环境变量 ``SVU_FFMPEG`` 中查找）。编码器优先 ``libx264``，并按
``h264_nvenc`` → ``h264_qsv`` → ``h264_amf`` → ``mpeg4`` 的顺序自动降级。
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter,
                           QPen)

from core.audio_synth import OfflineTrack, write_wav
from core.protocol import (Trace, TracePlayer, collect_notes_between,
                           hot_events_window)
from ui.canvas_widget import C_BG, VizFrame, make_renderer

__all__ = [
    "ExportError", "RESOLUTIONS", "FPS_CHOICES", "DURATION_PRESETS", "EASINGS",
    "ENCODER_CHOICES", "ExportSettings", "ExportProgress", "ExportResult",
    "find_ffmpeg", "ffmpeg_report", "available_encoders", "choose_encoder",
    "step_for_frame", "sweep_for_frame", "FrameData", "FrameComposer",
    "build_audio_track", "VideoExporter", "export_video", "ExportWorker",
    "default_output_path", "default_output_dir",
]

# ==========================================================================
# 1. 选项表与常量
# ==========================================================================
#: (键, 中文标签, 宽, 高)
RESOLUTIONS: Tuple[Tuple[str, str, int, int], ...] = (
    ("1080p", "1920 × 1080  (Full HD)", 1920, 1080),
    ("1440p", "2560 × 1440  (QHD)", 2560, 1440),
    ("4k", "3840 × 2160  (4K UHD)", 3840, 2160),
)

RESOLUTION_MAP: Dict[str, Tuple[int, int]] = {
    key: (w, h) for key, _label, w, h in RESOLUTIONS}

FPS_CHOICES: Tuple[int, ...] = (30, 60, 120)

DURATION_PRESETS: Tuple[int, ...] = (10, 15, 20, 30, 45, 60, 90)

#: (键, 标签, 说明)
EASINGS: Tuple[Tuple[str, str], ...] = (
    ("linear", "线性匀速 (Linear)"),
    ("ease_in_out", "平滑缓入缓出 (Ease In-Out)"),
    ("slow_tail", "慢速收尾 (Slow Tail)"),
    ("slow_head", "开场慢镜 (Slow Head)"),
)

ENCODER_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("auto", "自动选择（推荐）"),
    ("libx264", "libx264 · CPU 软编（兼容性最好）"),
    ("h264_nvenc", "h264_nvenc · NVIDIA 硬件编码"),
    ("h264_qsv", "h264_qsv · Intel QuickSync"),
    ("h264_amf", "h264_amf · AMD AMF"),
    ("mpeg4", "mpeg4 · 兜底（无 H.264 时）"),
)

#: 默认开头静止时长（秒）：让观众看清初始数组
DEFAULT_HOLD_HEAD = 0.6
#: 默认结尾翠绿扫光定格时长（秒）—— 规范书明确要求 1.5 s
DEFAULT_HOLD_TAIL = 1.5
#: 扫光带掠过整幅画面所需时长（秒），剩下的时间用于「定格」
SWEEP_RAMP = 1.0

#: 音频采样率（与实时音效引擎保持一致，保证「听到的 = 导出的」）
AUDIO_SAMPLE_RATE = 44100
#: 每帧最多叠加的音符数（超采样后抽样，避免糊成噪音）
AUDIO_VOICES = 6

#: FFmpeg stderr 保留的诊断行数
_ERR_LINES = 240

#: 等宽字体候选（与界面保持一致）
_MONO_FAMILIES = ("JetBrains Mono", "Cascadia Mono", "Consolas",
                  "DejaVu Sans Mono", "Menlo", "Monaco", "Courier New")
#: 等宽字体缺中文字形时按此列表回退，避免导出视频里出现方块
_CJK_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC",
                 "Source Han Sans SC", "SimHei", "PingFang SC", "sans-serif")


class ExportError(RuntimeError):
    """视频导出过程中的可预期错误（缺 FFmpeg、编码失败、写入中断等）。"""


# ==========================================================================
# 2. FFmpeg 发现与探测
# ==========================================================================
_FFMPEG_CACHE: Optional[str] = None
_ENCODER_CACHE: Dict[str, frozenset] = {}
_FONT_FAMILY: Optional[str] = None


def _exe_names() -> Tuple[str, ...]:
    """候选可执行文件名。

    Windows 上大小写不敏感，但 PyInstaller ``--add-binary`` 会**原样保留**
    源文件名（常见下载包里的名字就是全大写的 ``ffmpeg.EXE``）；在大小写
    敏感的平台上这会造成找不到，所以两种都列上。
    """
    if os.name == "nt":
        return ("ffmpeg.exe", "ffmpeg.EXE")
    return ("ffmpeg", "ffmpeg.exe")


def _no_window_kwargs() -> Dict[str, object]:
    """Windows 下静默启动子进程，避免打开发出黑框。"""
    if os.name == "nt":
        return {"creationflags": 0x08000000}      # CREATE_NO_WINDOW
    return {}


def candidate_ffmpeg_paths() -> List[Path]:
    """按「越具体越优先」的顺序列出所有候选 ffmpeg 路径。"""
    exes = _exe_names()
    out: List[Path] = []

    env = os.environ.get("SVU_FFMPEG", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            out += [p / e for e in exes]
        else:
            out.append(p)

    which = shutil.which("ffmpeg")
    if which:
        out.append(Path(which))

    bases: List[Path] = [Path.cwd()]
    try:
        bases.append(Path(__file__).resolve().parent.parent)   # 源码树根目录
    except Exception:                                          # pragma: no cover
        pass
    if getattr(sys, "frozen", False):                          # PyInstaller
        bases.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bases.append(Path(meipass))

    for base in bases:
        for e in exes:
            out += [base / e, base / "bin" / e, base / "ffmpeg" / e,
                    base / "ffmpeg" / "bin" / e, base / "tools" / e]

    local = os.environ.get("LOCALAPPDATA", "")
    if local and os.name == "nt":
        prog = Path(local) / "Programs"
        # 常见的手动解包目录：...\Programs\ffmpeg-8.0.1-...\ffmpeg-8.0.1-...\bin
        try:
            for top in sorted(prog.glob("ffmpeg*")):
                for sub in sorted(top.glob("ffmpeg*")):
                    out.append(sub / "bin" / "ffmpeg.exe")
                out.append(top / "bin" / "ffmpeg.exe")
        except OSError:                                        # pragma: no cover
            pass
        out.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe")
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        root = os.environ.get(env_key, "")
        if root:
            out += [Path(root) / "ffmpeg" / "bin" / "ffmpeg.exe",
                    Path(root) / "chocolatey" / "bin" / "ffmpeg.exe"]
    home = Path.home()
    out += [home / "scoop" / "shims" / "ffmpeg.exe",
            Path("/usr/local/bin/ffmpeg"), Path("/usr/bin/ffmpeg"),
            Path("/opt/homebrew/bin/ffmpeg")]
    return out


def find_ffmpeg(force: bool = False) -> Optional[str]:
    """定位 ``ffmpeg`` 可执行文件；找不到返回 ``None``（结果带缓存）。"""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE and not force:
        return _FFMPEG_CACHE
    for p in candidate_ffmpeg_paths():
        try:
            if p.is_file():
                _FFMPEG_CACHE = str(p)
                return _FFMPEG_CACHE
        except OSError:                                        # pragma: no cover
            continue
    if force:
        _FFMPEG_CACHE = None
    return None


def ffmpeg_version(exe: Optional[str] = None) -> str:
    """返回形如 ``ffmpeg version 8.0.1`` 的首行；失败返回空串。"""
    exe = exe or find_ffmpeg()
    if not exe:
        return ""
    try:
        cp = subprocess.run([exe, "-hide_banner", "-version"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=20, **_no_window_kwargs())
    except Exception:                                          # pragma: no cover
        return ""
    first = (cp.stdout or cp.stderr or "").splitlines()
    return first[0].strip() if first else ""


def available_encoders(exe: Optional[str] = None) -> frozenset:
    """解析 ``ffmpeg -encoders``，返回可用编码器名集合。"""
    exe = exe or find_ffmpeg()
    if not exe:
        return frozenset()
    hit = _ENCODER_CACHE.get(exe)
    if hit is not None:
        return hit
    names = set()
    try:
        cp = subprocess.run([exe, "-hide_banner", "-encoders"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=30, **_no_window_kwargs())
        # 输出长这样（前半段是图例行，必须跳过，否则会把 "=" 当成编码器名）：
        #     Encoders:
        #      V..... = Video
        #      ...
        #      ------
        #      V....D libx264   libx264 H.264 / AVC ...
        # 因此以「整行都是短横线」的分隔行为界，只解析它之后的内容。
        in_list = False
        for line in (cp.stdout or "").splitlines():
            stripped = line.strip()
            if not in_list:
                if stripped and set(stripped) == {"-"}:
                    in_list = True
                continue
            parts = stripped.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] == "V":
                names.add(parts[1])
    except Exception:                                          # pragma: no cover
        pass
    result = frozenset(names)
    _ENCODER_CACHE[exe] = result
    return result


#: 编码器 → (显示名, 附加参数模板)
_ENCODER_ARGS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "libx264": ("libx264", ("-preset", "{preset}", "-crf", "{crf}",
                            "-pix_fmt", "yuv420p", "-profile:v", "high")),
    "h264_nvenc": ("h264_nvenc", ("-preset", "p5", "-rc", "vbr", "-cq", "21",
                                  "-b:v", "0", "-pix_fmt", "yuv420p")),
    "h264_qsv": ("h264_qsv", ("-preset", "medium", "-global_quality", "21",
                              "-pix_fmt", "nv12")),
    "h264_amf": ("h264_amf", ("-quality", "balanced", "-rc", "cqp",
                              "-qp_i", "21", "-qp_p", "23", "-pix_fmt",
                              "yuv420p")),
    "mpeg4": ("mpeg4", ("-q:v", "3", "-pix_fmt", "yuv420p")),
}

#: 自动选择时的偏好顺序（越靠前越优先）
_ENCODER_ORDER = ("libx264", "h264_nvenc", "h264_qsv", "h264_amf", "mpeg4")


def choose_encoder(exe: Optional[str] = None, prefer: str = "auto",
                   crf: int = 18, preset: str = "medium"
                   ) -> Tuple[str, List[str]]:
    """决定实际使用的编码器，返回 ``(编码器名, 附加参数列表)``。

    ``prefer="auto"`` 时按 :data:`_ENCODER_ORDER` 挑第一个可用的；显式指定
    但不可用时**不静默回退**，而是抛出 :class:`ExportError` —— 用户既然手选
    了 NVENC，我们就不该偷偷改用 CPU 慢慢编。
    """
    exe = exe or find_ffmpeg()
    have = available_encoders(exe)
    prefer = (prefer or "auto").strip()

    if prefer == "auto":
        if not have:                      # 探测失败（老版本 / 裁剪版）→ 赌 x264
            return _encoder_args("libx264", crf, preset)
        for name in _ENCODER_ORDER:
            if name in have:
                return _encoder_args(name, crf, preset)
        raise ExportError(
            "当前 FFmpeg 不含任何可用的 H.264 编码器，请更换完整版 FFmpeg。")

    if have and prefer not in have:
        usable = sorted(n for n in have
                        if n.startswith(("libx264", "h264", "mpeg4")))
        if usable:
            raise ExportError(f"当前 FFmpeg 不含编码器 {prefer}。可用："
                              + "、".join(usable))
        raise ExportError(f"当前 FFmpeg 不含编码器 {prefer}，"
                          "且整个构建里没有任何 H.264 编码器。")
    if prefer not in _ENCODER_ARGS:
        raise ExportError(f"未知编码器：{prefer}")
    return _encoder_args(prefer, crf, preset)


def _encoder_args(name: str, crf: int, preset: str) -> Tuple[str, List[str]]:
    _label, tpl = _ENCODER_ARGS[name]
    args = [str(crf) if a == "{crf}" else (preset if a == "{preset}" else a)
            for a in tpl]
    return name, args


def ffmpeg_report() -> Dict[str, object]:
    """给 UI 用的 FFmpeg 体检报告。"""
    exe = find_ffmpeg()
    info: Dict[str, object] = {"available": bool(exe), "path": exe or "",
                               "version": "", "encoders": [], "note": ""}
    if not exe:
        info["note"] = ("未找到 ffmpeg。请安装后加入 PATH，或用环境变量 "
                        "SVU_FFMPEG 指定路径，或把 ffmpeg.exe 放到程序目录。")
        return info
    info["version"] = ffmpeg_version(exe)
    have = available_encoders(exe)
    info["encoders"] = [n for n in _ENCODER_ORDER if n in have]
    if not info["encoders"]:
        info["note"] = "该 FFmpeg 缺少 H.264 编码器（建议使用 gyan.dev 的 full 版）。"
    return info


# ==========================================================================
# 3. 导出参数
# ==========================================================================
@dataclass
class ExportSettings:
    """一次导出的全部参数。"""

    output: str = "sorting_visualization.mp4"
    width: int = 1920
    height: int = 1080
    fps: int = 60
    duration: float = 15.0
    hold_head: float = DEFAULT_HOLD_HEAD
    hold_tail: float = DEFAULT_HOLD_TAIL
    easing: str = "ease_in_out"

    style: str = "bars"
    palette: str = "rainbow"

    audio: bool = True
    waveform: str = "sine"
    volume: float = 0.85

    show_hud: bool = True
    show_progress: bool = True
    hot_window: int = 16

    encoder: str = "auto"
    crf: int = 18
    preset: str = "medium"
    ffmpeg: Optional[str] = None
    extra_ffmpeg_args: Tuple[str, ...] = ()

    # ---- 派生属性 --------------------------------------------------------
    @property
    def frames(self) -> int:
        """总帧数（至少 1 帧）。"""
        return max(1, int(round(float(self.duration) * int(self.fps))))

    @property
    def duration_exact(self) -> float:
        """按帧数回算的精确时长，避免 ``-shortest`` 截掉尾帧。"""
        return self.frames / float(max(1, self.fps))

    @property
    def resolution_key(self) -> str:
        for key, _label, w, h in RESOLUTIONS:
            if (w, h) == (self.width, self.height):
                return key
        return f"{self.width}x{self.height}"

    @property
    def audio_seconds(self) -> float:
        return self.duration_exact if self.audio else 0.0

    def label(self) -> str:
        return (f"{self.width}×{self.height} @ {self.fps}FPS · "
                f"{self.duration:g}s · {self.frames} 帧")

    def validate(self) -> List[str]:
        """返回参数问题清单（空列表表示合法）。"""
        problems: List[str] = []
        if self.width < 320 or self.height < 240:
            problems.append("分辨率至少 320×240")
        if self.width % 2 or self.height % 2:
            problems.append("H.264 要求宽高均为偶数")
        if self.fps not in FPS_CHOICES and not (5 <= self.fps <= 240):
            problems.append("帧率需在 5 ~ 240 之间")
        if self.duration <= 0:
            problems.append("时长必须为正数")
        if self.hold_head < 0 or self.hold_tail < 0:
            problems.append("开头 / 结尾定格时长不能为负数")
        if self.hold_head + self.hold_tail >= self.duration:
            problems.append("开头 + 结尾定格已占满全片，没有留给排序动画")
        if not self.output.strip():
            problems.append("输出路径不能为空")
        if self.easing not in dict(EASINGS):
            problems.append(f"未知缓动曲线：{self.easing}")
        return problems

    @classmethod
    def for_resolution(cls, key: str, **kwargs) -> "ExportSettings":
        w, h = RESOLUTION_MAP.get(key, (1920, 1080))
        return cls(width=w, height=h, **kwargs)

    def frame_layout(self) -> Tuple[float, float]:
        """返回排序动画区间的归一化起止 ``(t0, t1)``（0~1）。"""
        d = max(1e-6, float(self.duration))
        t0 = min(0.9, max(0.0, self.hold_head / d))
        t1 = max(t0, 1.0 - max(0.0, self.hold_tail) / d)
        return t0, t1


@dataclass
class ExportProgress:
    """一次进度回调。"""

    stage: str = "render"        # prepare / audio / render / mux / done
    frame: int = 0
    frames: int = 0
    percent: float = 0.0
    fps: float = 0.0
    eta: float = 0.0
    message: str = ""

    def text(self) -> str:
        if self.message:
            return self.message
        return f"{self.percent:5.1f}%   {self.frame}/{self.frames} 帧"


@dataclass
class ExportResult:
    """导出结果。"""

    output: str = ""
    width: int = 0
    height: int = 0
    fps: int = 0
    frames: int = 0
    duration: float = 0.0
    encoder: str = ""
    ffmpeg: str = ""
    bytes_written: int = 0
    elapsed: float = 0.0
    audio_seconds: float = 0.0
    cancelled: bool = False
    log: str = ""

    @property
    def mib(self) -> float:
        return self.bytes_written / (1024.0 * 1024.0)

    def summary(self) -> str:
        state = "已取消" if self.cancelled else "完成"
        return (f"导出{state}：{Path(self.output).name}\n"
                f"{self.width}×{self.height} @ {self.fps}FPS · {self.frames} 帧 · "
                f"{self.duration:.2f}s · {self.mib:.1f} MB\n"
                f"编码器 {self.encoder} · 音轨 {self.audio_seconds:.2f}s · "
                f"耗时 {self.elapsed:.1f}s")


def default_output_dir() -> Path:
    """默认输出目录：程序工作目录下的 ``exports/``。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "exports"
    return Path.cwd() / "exports"


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in (text or "")]
    out = "".join(keep).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out[:48] or "sorting"


def default_output_path(meta, settings: ExportSettings) -> str:
    """为当前算法生成一个合理的默认文件名。"""
    if meta is not None:
        stem = f"{int(getattr(meta, 'index', 0)):03d}_{_slug(getattr(meta, 'name_en', ''))}"
    else:
        stem = "sorting"
    return str(default_output_dir() / f"{stem}_{settings.height}p"
                                      f"{settings.fps}fps.mp4")


# ==========================================================================
# 4. 时间轴映射（帧号 → 步号 / 扫光进度）
# ==========================================================================
def ease(t: float, kind: str) -> float:
    """把归一化时间 ``t ∈ [0,1]`` 映射成归一化进度。"""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else float(t))
    if kind == "ease_in_out":
        # smoothstep：起止两端导数连续，观感最「顺」
        return t * t * (3.0 - 2.0 * t)
    if kind == "slow_tail":
        # 收尾减速：结尾几步看得更清楚
        return 1.0 - (1.0 - t) ** 2.2
    if kind == "slow_head":
        return t ** 2.2
    return t


def step_for_frame(frame_index: int, n_frames: int, total_ops: int,
                   settings: ExportSettings) -> int:
    """把第 ``frame_index`` 帧映射到 ``[0, total_ops]`` 之间的步号。

    开头 ``hold_head`` 秒停在 0 步（看清初始数组），结尾 ``hold_tail`` 秒停在
    末尾（扫光定格），中间的排序区间按所选缓动曲线插值。
    """
    total_ops = max(0, int(total_ops))
    if total_ops == 0 or n_frames <= 1:
        return total_ops
    t = frame_index / float(n_frames - 1)
    t0, t1 = settings.frame_layout()
    if t <= t0:
        u = 0.0
    elif t >= t1:
        u = 1.0
    else:
        u = ease((t - t0) / max(1e-9, t1 - t0), settings.easing)
    return int(round(u * total_ops))


def sweep_for_frame(frame_index: int, n_frames: int,
                    settings: ExportSettings) -> float:
    """返回该帧的翠绿扫光进度 ``0~1``（0 = 不扫）。"""
    tail = float(settings.hold_tail)
    if tail <= 0.0 or n_frames <= 1 or settings.fps <= 0:
        return 0.0
    t = frame_index / float(settings.fps)
    start = settings.duration_exact - tail
    if t < start:
        return 0.0
    return min(1.0, (t - start) / max(1e-6, min(SWEEP_RAMP, tail)))


# ==========================================================================
# 5. 字体与 HUD 绘制
# ==========================================================================
def mono_family() -> str:
    """挑一款可用的等宽字体（结果缓存）。

    返回空串表示**当前平台查不到任何字体库**（例如 ``QT_QPA_PLATFORM=offscreen``
    的精简字体引擎），此时交给 Qt 使用默认字体，而不是硬报一个可能不存在的
    家族名 —— 否则 HUD 上的中英文会统统变成「豆腐块」。
    """
    global _FONT_FAMILY
    if _FONT_FAMILY is not None:
        return _FONT_FAMILY
    fams = set()
    try:
        fams = set(QFontDatabase.families())
    except Exception:                                          # pragma: no cover
        pass
    if not fams:
        _FONT_FAMILY = ""
    else:
        _FONT_FAMILY = next((n for n in _MONO_FAMILIES if n in fams),
                            "Consolas" if os.name == "nt" else "monospace")
    return _FONT_FAMILY


_FONT_CACHE: Dict[Tuple[int, bool], QFont] = {}


def mono_font(px: int, bold: bool = False) -> QFont:
    """按**像素**尺寸取等宽字体，并挂上中文字体回退链。

    导出视频里 HUD 全是中文指标名（分类 / 时间复杂度 / 稳定性…），而
    Consolas / JetBrains Mono 都不含中文字形；只设一个 family 会渲染成方块，
    因此这里用 ``setFamilies`` 显式指定回退顺序。
    """
    px = max(6, int(px))
    key = (px, bool(bold))
    hit = _FONT_CACHE.get(key)
    if hit is not None:
        return hit
    family = mono_family()
    f = QFont(family) if family else QFont()
    if family:
        try:
            f.setFamilies([family, *_CJK_FAMILIES])
        except Exception:                                      # pragma: no cover
            pass
    f.setPixelSize(px)
    f.setBold(bool(bold))
    f.setStyleHint(QFont.Monospace)
    if len(_FONT_CACHE) > 64:
        _FONT_CACHE.clear()
    _FONT_CACHE[key] = f
    return f


def _rgb(color: str, alpha: int = 255) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


@dataclass
class FrameData:
    """一帧的画面内容（不含任何与分辨率相关的布局信息）。"""

    values: Sequence[int] = ()
    aux: Sequence[int] = ()
    aux_active: bool = False
    marks: Dict[str, set] = field(default_factory=dict)
    hot: Dict[int, str] = field(default_factory=dict)
    hot_aux: Dict[int, str] = field(default_factory=dict)
    n_max: int = 1
    palette: str = "white"
    sweep: float = 0.0
    step: int = 0
    total: int = 0
    cmp: int = 0
    swaps: int = 0
    main_writes: int = 0
    aux_writes: int = 0
    accesses: int = 0
    elapsed_ms: float = 0.0
    msg: str = ""
    state: str = ""
    done: bool = False
    truncated: bool = False
    #: 帧序号与帧率。次世代视图（全息双螺旋自转、极光飘动、切片激光扫描）
    #: 需要时间相位，导出时用 ``index / fps`` 给出 —— 成片因此完全确定性，
    #: 同一份指令流重复导出必然逐帧一致。
    index: int = 0
    fps: float = 60.0


class FrameComposer:
    """把「一帧数据」合成成一张 ``(H, W, 3) uint8`` 的高清位图。

    绘制分两段：

    1. **可视化区**：直接调用 :func:`ui.canvas_widget.render_frame_to_array`
       的纯 NumPy 内核渲染到子缓冲，再整块 ``np.copyto`` 贴到大画布上。
       这一路完全不碰 Qt，因此可以放心地在工作线程里跑。
    2. **HUD 与进度条**：在**同一块大画布**上包一层 ``QImage``，用
       ``QPainter`` 画半透明毛玻璃浮层、等宽字体指标与底部进度条。
       只在 QImage（而不是 QWidget）上作画，所以在 QThread 里也合法。
    """

    def __init__(self, settings: ExportSettings, meta=None,
                 n_value: Optional[int] = None, dist_label: str = "") -> None:
        self.settings = settings
        self.meta = meta
        self.n_value = int(n_value) if n_value else None
        self.dist_label = dist_label or ""

        self.w = max(320, int(settings.width))
        self.h = max(240, int(settings.height))

        # ---- 版式 --------------------------------------------------------
        self.pad = max(4, int(round(self.h * 0.010)))
        self.gap = max(4, int(round(self.h * 0.009)))
        s = self.scale = self.h / 720.0
        self.bar_th = max(6, int(round(12 * s)))
        self.foot_text_h = int(round(26 * s))
        foot_h = self.bar_th + int(round(10 * s)) + self.foot_text_h

        self.viz = (self.pad, self.pad,
                    self.w - 2 * self.pad,
                    self.h - 2 * self.pad - foot_h - self.gap)
        if self.viz[3] < 80:                          # 极端比例下自保
            self.viz = (self.pad, self.pad, self.w - 2 * self.pad,
                        max(80, self.h - 2 * self.pad - 30))
        self.foot = (self.pad, self.h - self.pad - foot_h,
                     self.w - 2 * self.pad, foot_h)

        self._renderer = make_renderer(settings.style, self.viz[2], self.viz[3])
        self._canvas = np.empty((self.h, self.w, 3), dtype=np.uint8)
        self._canvas[:, :] = C_BG
        self._viz_view = self._canvas[
            self.viz[1]:self.viz[1] + self.viz[3],
            self.viz[0]:self.viz[0] + self.viz[2]]
        self._qimage: Optional[QImage] = None
        self._last_ms = 0.0
        #: HUD 里大部分文字（指标名、标题、算法名）每帧都一样，而
        #: ``QFontMetrics.elidedText`` 要逐字符量宽；缓存之后每帧能省掉
        #: 十几次文本排版，1080P 下大约快 3~4 ms/帧。
        self._elide_cache: Dict[Tuple[str, int, int], str] = {}

    def _elide(self, painter: QPainter, text: str, mode, width: int) -> str:
        """带缓存的文本省略。

        ``mode`` 是 ``Qt.TextElideMode`` 枚举 —— PySide6 6.x 里它是真正的
        Python 枚举，``int(mode)`` 会抛 ``TypeError``，因此缓存键取
        ``mode.value``。
        """
        key = (text, max(0, int(width)), getattr(mode, "value", mode))
        hit = self._elide_cache.get(key)
        if hit is not None:
            return hit
        out = painter.fontMetrics().elidedText(text, mode, int(width))
        if len(self._elide_cache) > 768:
            self._elide_cache.clear()
        self._elide_cache[key] = out
        return out

    # ---- 渲染 ------------------------------------------------------------
    def compose(self, fd: FrameData) -> np.ndarray:
        """合成一帧，返回大画布的视图（内容每帧被覆盖，请立即使用）。"""
        t0 = time.perf_counter()
        # 整块复位背景 —— 这一步**不能省**。
        # HUD、进度条、水印都是用 QPainter「增量叠加」画上去的：文字以
        # 半透明抗锯齿边缘混合到已有像素上，如果不清底，上一帧的字会留在
        # 下面，而计数器每帧都在变（673 → 674 → …），900 帧叠下来就是一片
        # 重影黑糊。可视化区本来就会被整块 np.copyto 覆盖，但画布上除可视化
        # 区以外的像素只有这里能复位。
        self._canvas[:, :] = C_BG
        vframe = VizFrame(values=fd.values, aux=fd.aux, aux_active=fd.aux_active,
                          marks=fd.marks, hot=fd.hot, hot_aux=fd.hot_aux,
                          n_max=fd.n_max, palette=fd.palette, sweep=fd.sweep,
                          done=fd.done,
                          # 时空瀑布流靠步号识别倒带；导出时序严格单调，
                          # 这个字段同时也是「换算法就重置」的判据
                          step=fd.step,
                          # 动画相位：逐帧确定性推进（见 FrameData.index 说明）
                          t=fd.index / max(1e-6, float(fd.fps)))
        np.copyto(self._viz_view, self._renderer.render(vframe))

        if self.settings.show_hud or self.settings.show_progress:
            if self._qimage is None:
                self._qimage = QImage(self._canvas.data, self.w, self.h,
                                      3 * self.w, QImage.Format_RGB888)
            painter = QPainter(self._qimage)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                if self.settings.show_hud:
                    self._paint_hud(painter, fd)
                if self.settings.show_progress:
                    self._paint_foot(painter, fd)
                self._paint_watermark(painter, fd)
            finally:
                painter.end()
        self._last_ms = (time.perf_counter() - t0) * 1000.0
        return self._canvas

    # ---- HUD 看板 --------------------------------------------------------
    def _hud_rows(self, fd: FrameData) -> List[Tuple[str, str, str]]:
        meta = self.meta
        rows: List[Tuple[str, str, str]] = []
        if meta is not None:
            rows.append(("分类", str(getattr(meta, "category", "—")), "#00B4D8"))
            rows.append(("时间复杂度", f"best {getattr(meta, 'time_best', '?')}"
                                      f" / avg {getattr(meta, 'time_avg', '?')}", ""))
            rows.append(("", f"worst {getattr(meta, 'time_worst', '?')}", ""))
            rows.append(("空间复杂度", str(getattr(meta, "space", "?")), ""))
            stable = bool(getattr(meta, "stable", False))
            rows.append(("稳定性", "Stable ✓" if stable else "Unstable ✗",
                         "#00E676" if stable else "#FF9E2C"))
            if getattr(meta, "external", False):
                rows.append(("来源", f"外部自定义（{getattr(meta, 'source_lang', '?')}）",
                             "#FF9E2C"))
        n_label = f"{self.n_value}" if self.n_value else "—"
        rows.append(("数据规模 N", f"{n_label}   {self.dist_label}".rstrip(), ""))
        rows.append(("Comparisons", f"{fd.cmp:,}", "#FFEA00"))
        rows.append(("Swaps", f"{fd.swaps:,}", "#FF2A55"))
        rows.append(("Main Writes", f"{fd.main_writes:,}", ""))
        rows.append(("Aux  Writes", f"{fd.aux_writes:,}", "#4DD0E1"))
        rows.append(("Total Accesses", f"{fd.accesses:,}", ""))
        pct = 100.0 * (fd.step / fd.total) if fd.total else 0.0
        rows.append(("进度", f"{fd.step:,} / {fd.total:,}   {pct:5.1f}%", ""))
        rows.append(("算法耗时", f"{fd.elapsed_ms:.2f} ms", ""))
        state_col = "#00E676" if fd.done else "#ECEFF4"
        rows.append(("状态", fd.state or "—", state_col))
        rows.append(("MSG", fd.msg or "—", "#00F5D4"))
        return rows

    def _paint_hud(self, painter: QPainter, fd: FrameData) -> None:
        s = self.scale
        rows = self._hud_rows(fd)
        px_title = int(round(21 * s))
        px_sub = int(round(12.5 * s))
        px_row = int(round(14 * s))
        row_h = int(round(23 * s))
        pad_in = int(round(15 * s))
        panel_w = min(self.viz[2] - int(round(24 * s)), int(round(462 * s)))
        panel_h = (pad_in * 2 + px_title + int(round(6 * s)) + px_sub
                   + int(round(11 * s)) + row_h * len(rows))
        x = self.viz[0] + int(round(16 * s))
        y = self.viz[1] + int(round(16 * s))
        rect = QRectF(x, y, panel_w, panel_h)

        painter.save()
        painter.setPen(QPen(_rgb("#2A313D", 210), max(1, int(round(s)))))
        painter.setBrush(_rgb("#0B0D12", 208))
        radius = int(round(10 * s))
        painter.drawRoundedRect(rect, radius, radius)
        painter.setClipRect(rect)

        cx = x + pad_in
        cy = y + pad_in

        if self.meta is not None:
            title = (f"#{int(getattr(self.meta, 'index', 0)):03d}  "
                     f"{getattr(self.meta, 'name_zh', '')}")
            sub = str(getattr(self.meta, "name_en", ""))
        else:
            title = "Sorting Visualizer Ultimate"
            sub = ""
        inner_w = panel_w - 2 * pad_in
        painter.setFont(mono_font(px_title, True))
        painter.setPen(_rgb("#ECEFF4"))
        painter.drawText(QRectF(cx, cy, inner_w, px_title * 1.5),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self._elide(painter, title, Qt.ElideRight, inner_w))
        cy += int(px_title * 1.55)

        painter.setFont(mono_font(px_sub))
        painter.setPen(_rgb("#7C8AA0"))
        painter.drawText(QRectF(cx, cy, inner_w, px_sub * 1.6),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self._elide(painter, sub, Qt.ElideRight, inner_w))
        cy += int(px_sub * 1.6) + int(round(2 * s))

        painter.setPen(QPen(_rgb("#252A34"), 1))
        painter.drawLine(int(cx), int(cy), int(x + panel_w - pad_in), int(cy))
        cy += int(round(11 * s))

        value_x = cx + int(round(150 * s))
        label_w = value_x - cx - int(round(8 * s))
        value_w = x + panel_w - pad_in - value_x
        for label, value, color in rows:
            # 指标名与数值都做右侧省略：HUD 面板宽度有限，而最长的两项
            # （「时间复杂度 best… / avg…」与长算法名）一定会超框。
            painter.setFont(mono_font(px_row))
            painter.setPen(_rgb("#6E7A8C"))
            painter.drawText(QRectF(cx, cy, label_w, row_h),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             self._elide(painter, label, Qt.ElideRight, label_w))
            painter.setFont(mono_font(px_row, True))
            painter.setPen(_rgb(color or "#D8DEE9"))
            painter.drawText(QRectF(value_x, cy, value_w, row_h),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             self._elide(painter, value, Qt.ElideMiddle, value_w))
            cy += row_h
        painter.restore()

        if fd.done and not fd.truncated:
            self._paint_badge(painter, "✓ SORTED 已排序")

    def _paint_badge(self, painter: QPainter, text: str) -> None:
        s = self.scale
        px = int(round(17 * s))
        pad_x = int(round(16 * s))
        pad_y = int(round(8 * s))
        painter.save()
        painter.setFont(mono_font(px, True))
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        bw = tw + pad_x * 2
        bh = px + pad_y * 2
        bx = self.viz[0] + self.viz[2] - bw - int(round(16 * s))
        by = self.viz[1] + int(round(16 * s))
        rect = QRectF(bx, by, bw, bh)
        painter.setPen(QPen(_rgb("#00E676", 235), max(1, int(round(1.6 * s)))))
        painter.setBrush(_rgb("#04170D", 215))
        radius = int(round(bh / 2))
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(_rgb("#00E676"))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()

    # ---- 底部进度条 ------------------------------------------------------
    def _paint_foot(self, painter: QPainter, fd: FrameData) -> None:
        s = self.scale
        bx, by, bw, bh = self.foot
        ratio = 0.0
        if fd.total > 0:
            ratio = min(1.0, max(0.0, fd.step / float(fd.total)))
        elif fd.done:
            ratio = 1.0

        painter.save()
        bar = QRectF(bx, by, bw, self.bar_th)
        radius = max(2, self.bar_th // 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_rgb("#15181F"))
        painter.drawRoundedRect(bar, radius, radius)

        fill_w = max(0.0, bar.width() * ratio)
        if fill_w > 1.0:
            fill = QRectF(bx, by, fill_w, self.bar_th)
            # 进度色从科技蓝渐变到翠绿，视觉上呼应「已完成」语义
            col = QColor(
                int(round(0x00 + (0x00 - 0x00) * ratio)),
                int(round(0xB4 + (0xE6 - 0xB4) * ratio)),
                int(round(0xD8 + (0x76 - 0xD8) * ratio)))
            painter.setBrush(col)
            painter.drawRoundedRect(fill, radius, radius)
        painter.setPen(QPen(_rgb("#252A34"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(bar, radius, radius)

        px = int(round(14 * s))
        ty = by + self.bar_th + int(round(4 * s))
        th = float(self.foot_text_h)

        # 左右两块**不重叠**：左块到 58% 为止并做中段省略，右块从 58% 起右对齐。
        # 早期版本左块占 62%、右块从 38% 起，两段在中间互相盖住（640×360 下
        # 尤其明显，"100.0%" 会和算法名糊在一起）。
        split = bx + bw * 0.58
        painter.setFont(mono_font(px, True))
        left = self._elide(painter, self._foot_left(fd), Qt.ElideMiddle,
                           int(split - bx - 8))
        painter.setPen(_rgb("#D8DEE9"))
        painter.drawText(QRectF(bx, ty, split - bx - 8, th),
                         Qt.AlignLeft | Qt.AlignVCenter, left)

        pct = 100.0 * ratio
        right = (f"步 {fd.step:,}/{fd.total:,}   {pct:5.1f}%   "
                 f"{self.settings.width}×{self.settings.height}@{self.settings.fps}")
        painter.setFont(mono_font(px, fd.done))
        painter.setPen(_rgb("#00E676" if fd.done else "#7C8AA0"))
        painter.drawText(QRectF(split, ty, bx + bw - split, th),
                         Qt.AlignRight | Qt.AlignVCenter, right)
        painter.restore()

    def _foot_left(self, fd: FrameData) -> str:
        if self.meta is not None:
            name = f"#{int(getattr(self.meta, 'index', 0)):03d} " \
                   f"{getattr(self.meta, 'name_zh', '')}"
            en = str(getattr(self.meta, "name_en", ""))
            text = f"{name}  ·  {en}" if en else name
        else:
            text = "Sorting Visualizer Ultimate"
        if fd.truncated:
            text += "   ⚠ 指令流已截断"
        elif fd.done:
            text += "   ✓ 排序完成"
        if fd.msg:
            text += f"   |   {fd.msg}"
        return text

    # ---- 右下角水印 ------------------------------------------------------
    def _paint_watermark(self, painter: QPainter, fd: FrameData) -> None:
        """可视化区右下角的小字水印：视图样式 / 配色 / 音效，方便成片溯源。

        放在右下而不是右上，是因为右上角要留给「✓ SORTED 已排序」徽标，
        两者叠在一起会互相糊住。
        """
        s = self.scale
        painter.save()
        px = int(round(12 * s))
        painter.setFont(mono_font(px))
        painter.setPen(_rgb("#5A6474"))
        parts = [self.settings.style.upper(), self.settings.palette.upper()]
        if self.settings.audio:
            parts.append(self.settings.waveform.upper())
        if not self.settings.show_hud:
            # HUD 关掉时把品牌名也带上，否则画面只剩一串缩写很突兀
            parts.insert(0, "Sorting Visualizer Ultimate")
        h = px * 2.0
        rect = QRectF(self.viz[0], self.viz[1] + self.viz[3]
                      - h - int(round(8 * s)),
                      self.viz[2] - int(round(16 * s)), h)
        painter.drawText(rect, Qt.AlignRight | Qt.AlignBottom, " · ".join(parts))
        painter.restore()

    # ---- 预览 ------------------------------------------------------------
    @property
    def last_compose_ms(self) -> float:
        return self._last_ms


# ==========================================================================
# 6. 离线音轨构建（与视频时间轴共用同一套帧号映射）
# ==========================================================================
def build_audio_track(trace: Trace, initial: Sequence[int], n_max: int,
                      settings: ExportSettings,
                      on_progress: Optional[Callable[[ExportProgress], None]] = None,
                      should_cancel: Optional[Callable[[], bool]] = None
                      ) -> OfflineTrack:
    """按视频时间轴把整条排序过程映射成音符时间轴。

    关键点：这里用的是与 :func:`step_for_frame` **完全相同**的映射，所以
    「第几秒听到什么」与「第几秒看到什么」天然一致，不需要任何手工对齐。

    抽样策略与实时播放一致：每帧最多取 ``AUDIO_VOICES`` 个代表元素，
    这样极速档听到的是清晰的上行音阶，而不是一团白噪音。
    """
    track = OfflineTrack(sample_rate=AUDIO_SAMPLE_RATE)
    total = int(trace.n_ops)
    if total <= 0:
        return track

    t0, t1 = settings.frame_layout()
    f0 = int(round(t0 * settings.frames))
    f1 = int(round(t1 * settings.frames))
    n_frames = max(1, f1 - f0)

    voices = max(1, int(min(AUDIO_VOICES, max(1, len(initial)))))
    player = TracePlayer(trace, initial, max_snapshots=4)
    wave = settings.waveform

    for k in range(n_frames):
        if should_cancel is not None and should_cancel():
            break
        frame_index = f0 + k
        target = step_for_frame(frame_index, settings.frames, total, settings)
        if target <= player.step:
            continue
        lo, hi = player.step, target
        player.seek(target)
        values = collect_notes_between(trace, lo, hi, player.data,
                                       limit=voices * 4)
        if not values:
            continue
        if len(values) > voices:
            step = len(values) / float(voices)
            values = [values[int(i * step)] for i in range(voices)]
        t = frame_index / float(settings.fps)
        gain = settings.volume / max(1.0, math.sqrt(len(values)) * 0.6)
        for v in values:
            track.add_value(t, v, max(1, n_max), gain=gain, waveform=wave)
        if on_progress is not None and (k % 32 == 0):
            on_progress(ExportProgress(
                stage="audio", frame=k, frames=n_frames,
                percent=100.0 * k / max(1, n_frames),
                message=f"合成音轨 {k}/{n_frames} 帧"))

    # 结尾和弦爬升（规范书 5.1：排序完成后触发翠绿扫光 + 和弦爬升音效）
    t_end = max(0.0, settings.duration_exact - float(settings.hold_tail) * 0.55)
    track.add_finish_chord(t_end, steps=10, spread=0.05,
                           volume=min(0.30, 0.26 * settings.volume * 1.2),
                           waveform=wave)
    return track


# ==========================================================================
# 7. 导出引擎
# ==========================================================================
class VideoExporter:
    """离线导出引擎：可同步调用，也可放进 :class:`ExportWorker` 线程里跑。

    典型用法::

        settings = ExportSettings.for_resolution("1080p", duration=15, fps=60)
        result = export_video(meta=meta, values=values, trace=trace,
                              settings=settings, n_value=512,
                              on_progress=print)
    """

    def __init__(self, *, meta, values: Sequence[int], trace: Trace,
                 settings: ExportSettings,
                 n_value: Optional[int] = None, dist_kind: str = "random",
                 on_progress: Optional[Callable[[ExportProgress], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None) -> None:
        self.meta = meta
        self.values = [int(v) for v in values]
        self.trace = trace
        self.settings = settings
        self.n_value = int(n_value) if n_value else len(self.values)
        self.dist_kind = dist_kind
        self._on_progress = on_progress
        self._should_cancel = should_cancel
        self._cancelled = False
        self._err_lines: Deque[str] = deque(maxlen=_ERR_LINES)
        self._err_lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    # ---- 控制 ------------------------------------------------------------
    def cancel(self) -> None:
        """请求停止导出：关闭管道并结束 FFmpeg 进程。"""
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:                                  # pragma: no cover
                pass
            try:
                proc.terminate()
            except Exception:                                  # pragma: no cover
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def _should_stop(self) -> bool:
        if self._cancelled:
            return True
        return bool(self._should_cancel and self._should_cancel())

    def _emit(self, stage: str, frame: int = 0, frames: int = 0,
              percent: float = 0.0, fps: float = 0.0, eta: float = 0.0,
              message: str = "") -> None:
        if self._on_progress is None:
            return
        try:
            self._on_progress(ExportProgress(stage=stage, frame=frame,
                                             frames=frames, percent=percent,
                                             fps=fps, eta=eta,
                                             message=message))
        except Exception:                                      # pragma: no cover
            pass

    # ---- stderr 抽干线程 -------------------------------------------------
    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        if proc.stderr is None:                                # pragma: no cover
            return
        try:
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                with self._err_lock:
                    self._err_lines.append(line)
        except Exception:                                      # pragma: no cover
            pass

    def _stderr_tail(self, limit: int = 12) -> str:
        with self._err_lock:
            lines = list(self._err_lines)[-limit:]
        return "\n".join(lines)

    # ---- 主流程 ----------------------------------------------------------
    def run(self) -> ExportResult:
        st = self.settings
        problems = st.validate()
        if problems:
            raise ExportError("导出参数不合法：" + "；".join(problems))

        exe = st.ffmpeg or find_ffmpeg()
        if not exe:
            raise ExportError(
                "未找到 FFmpeg。请安装 FFmpeg 并加入 PATH，或设置环境变量 "
                "SVU_FFMPEG 指向 ffmpeg.exe，或把它放到程序目录 / bin/ 下。")
        encoder, enc_args = choose_encoder(exe, st.encoder,
                                           crf=int(st.crf), preset=str(st.preset))

        out_path = Path(st.output).expanduser()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"无法创建输出目录：{exc}") from exc

        t_start = time.perf_counter()
        self._emit("prepare", percent=0.0, message="准备导出…")

        # ---- 1. 音轨（一次性合成，随后交给 FFmpeg 做第二路输入）---------
        tmp_dir = Path(tempfile.mkdtemp(prefix="svu_export_"))
        wav_path: Optional[Path] = None
        audio_seconds = 0.0
        try:
            if st.audio:
                self._emit("audio", percent=0.0, message="合成立体声音轨…")
                track = build_audio_track(
                    self.trace, self.values, max(1, int(self.n_value)), st,
                    on_progress=self._on_progress,
                    should_cancel=self._should_stop)
                n_samples = max(1, int(round(st.duration_exact * AUDIO_SAMPLE_RATE)))
                samples = track.render(n_samples / float(AUDIO_SAMPLE_RATE),
                                       master_volume=1.0, stereo=True)
                wav_path = tmp_dir / "audio.wav"
                write_wav(wav_path, samples, AUDIO_SAMPLE_RATE)
                audio_seconds = samples.shape[0] / float(AUDIO_SAMPLE_RATE)
                if self._should_stop():
                    return self._cancelled_result(out_path, encoder, exe, t_start,
                                                  audio_seconds)
                self._emit("audio", percent=100.0,
                           message=f"音轨就绪：{audio_seconds:.2f}s / 立体声")

            # ---- 2. FFmpeg 命令行 ---------------------------------------
            args = self._build_argv(exe, encoder, enc_args, wav_path, out_path)
            self._emit("render", percent=0.0, message="启动 FFmpeg 编码管道…")

            # 注意：stdin 用默认带缓冲模式，不要设 bufsize=0。
            # bufsize=0 时 stdin 是 io.FileIO，其 write() 允许**部分写入**，
            # 4K 帧（24 MB）一次性推流很容易只写进去一半就返回 —— 那会导致
            # 画面撕裂。BufferedWriter.write() 会保证写完（并在此之前把数据
            # 拷进内部缓冲），因此下一帧覆写画布缓冲不会产生别名问题。
            proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, **_no_window_kwargs())
            self._proc = proc
            err_thread = threading.Thread(target=self._drain_stderr,
                                          args=(proc,), daemon=True,
                                          name="svu-ffmpeg-stderr")
            err_thread.start()

            # ---- 3. 逐帧渲染并推流 --------------------------------------
            composer = FrameComposer(st, meta=self.meta, n_value=self.n_value,
                                     dist_label=self._dist_label())
            player = TracePlayer(self.trace, self.values)
            total_ops = int(self.trace.n_ops)
            frames = st.frames
            hot_window = max(1, int(st.hot_window))
            written = 0
            t_render0 = time.perf_counter()
            last_emit = 0.0
            cancelled = False

            for f in range(frames):
                if self._should_stop():
                    cancelled = True
                    break

                step = step_for_frame(f, frames, total_ops, st)
                if step > player.step:
                    player.seek(step)
                if hot_window > 1:
                    hot, hot_aux = hot_events_window(
                        self.trace, max(0, step - hot_window), step,
                        window=hot_window)
                else:
                    hot, hot_aux = hot_events_window(self.trace, step - 1, step,
                                                     window=1)

                done = total_ops > 0 and player.step >= total_ops
                fd = FrameData(
                    values=player.data, aux=player.aux,
                    aux_active=player.aux_active, marks=player.marks,
                    hot=hot, hot_aux=hot_aux,
                    n_max=max(1, int(self.n_value)), palette=st.palette,
                    sweep=sweep_for_frame(f, frames, st),
                    step=player.step, total=total_ops,
                    cmp=player.cmp, swaps=player.swaps,
                    main_writes=player.main_writes,
                    aux_writes=player.aux_writes, accesses=player.accesses,
                    elapsed_ms=self.trace.elapsed * 1000.0,
                    msg=player.msg,
                    state=self._state_text(done, player),
                    done=done, truncated=bool(self.trace.truncated),
                    index=f, fps=float(st.fps))
                buf = composer.compose(fd)

                try:
                    proc.stdin.write(memoryview(buf).cast("B"))
                except (BrokenPipeError, OSError, ValueError):
                    if proc.poll() is not None:
                        raise ExportError(
                            "FFmpeg 提前退出（编码失败）。诊断信息：\n"
                            + (self._stderr_tail() or "（无输出）"))
                    raise
                written += 1

                now = time.perf_counter()
                if now - last_emit >= 0.08 or f == frames - 1:
                    last_emit = now
                    done_n = f + 1
                    speed = done_n / max(1e-6, now - t_render0)
                    eta = (frames - done_n) / speed if speed > 0 else 0.0
                    self._emit("render", frame=done_n, frames=frames,
                               percent=100.0 * done_n / frames, fps=speed,
                               eta=eta,
                               message=(f"渲染 {done_n}/{frames} 帧 · "
                                        f"{speed:5.1f} FPS · 剩余约 {eta:5.1f}s"))

            # ---- 4. 收尾 -------------------------------------------------
            if cancelled:
                self.cancel()
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:                                  # pragma: no cover
                pass
            rc = proc.wait()
            err_thread.join(timeout=5.0)

            if cancelled:
                return self._cancelled_result(out_path, encoder, exe, t_start,
                                              audio_seconds, written)
            if rc != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
                raise ExportError(
                    f"FFmpeg 返回码 {rc}，未生成有效视频。诊断信息：\n"
                    + (self._stderr_tail() or "（无输出）"))

            elapsed = time.perf_counter() - t_start
            size = out_path.stat().st_size
            self._emit("done", frame=written, frames=frames, percent=100.0,
                       message=f"导出完成：{out_path.name}（{size / 1048576:.1f} MB）")
            return ExportResult(
                output=str(out_path), width=st.width, height=st.height,
                fps=st.fps, frames=written, duration=st.duration_exact,
                encoder=encoder, ffmpeg=exe, bytes_written=size,
                elapsed=elapsed, audio_seconds=audio_seconds,
                log=self._stderr_tail(40))
        finally:
            self._proc = None
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 辅助 ------------------------------------------------------------
    def _dist_label(self) -> str:
        try:
            from core.data_generator import describe
            return describe(self.dist_kind)
        except Exception:                                      # pragma: no cover
            return self.dist_kind

    def _state_text(self, done: bool, player: TracePlayer) -> str:
        if self.trace.truncated:
            return f"⚠ 指令流截断于 {self.trace.n_ops:,} 步"
        if done:
            return "已完成 ✓ 正在扫光校验"
        if self.trace.n_ops == 0:
            return "（空指令流）"
        return "播放中 ▶"

    def _cancelled_result(self, out_path: Path, encoder: str, exe: str,
                          t_start: float, audio_seconds: float,
                          written: int = 0) -> ExportResult:
        size = 0
        try:
            if out_path.is_file():
                size = out_path.stat().st_size
        except OSError:                                        # pragma: no cover
            pass
        self._emit("done", frame=written, percent=100.0, message="导出已取消")
        return ExportResult(
            output=str(out_path), width=self.settings.width,
            height=self.settings.height, fps=self.settings.fps,
            frames=written, duration=self.settings.duration_exact,
            encoder=encoder, ffmpeg=exe, bytes_written=size,
            elapsed=time.perf_counter() - t_start,
            audio_seconds=audio_seconds, cancelled=True,
            log=self._stderr_tail(20))

    def _build_argv(self, exe: str, encoder: str, enc_args: Sequence[str],
                    wav_path: Optional[Path], out_path: Path) -> List[str]:
        st = self.settings
        argv: List[str] = [exe, "-y", "-hide_banner", "-loglevel", "warning"]
        argv += ["-f", "rawvideo", "-pix_fmt", "rgb24",
                 "-video_size", f"{st.width}x{st.height}",
                 "-framerate", str(st.fps), "-i", "pipe:0"]
        if wav_path is not None:
            argv += ["-i", str(wav_path)]
            argv += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            argv += ["-map", "0:v:0", "-an"]
        argv += ["-c:v", encoder, *enc_args]
        # 关键帧间隔固定为 2 秒：拖动进度条时定位更快，社交平台转码也更友好
        if encoder == "libx264":
            argv += ["-x264-params", f"keyint={st.fps * 2}:min-keyint={st.fps}"]
        if wav_path is not None:
            argv += ["-c:a", "aac", "-b:a", "192k",
                     "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2"]
        argv += ["-shortest", "-movflags", "+faststart", "-f", "mp4"]
        argv += [str(a) for a in st.extra_ffmpeg_args]
        argv += [str(out_path)]
        return argv


# ==========================================================================
# 8. Qt 线程封装
# ==========================================================================
class ExportWorker(QThread):
    """把 :class:`VideoExporter` 放进后台线程，避免导出时界面卡死。"""

    progressed = Signal(object)      # ExportProgress
    finished_ok = Signal(object)     # ExportResult
    failed = Signal(str)

    def __init__(self, meta, values: Sequence[int], trace: Trace,
                 settings: ExportSettings, n_value: Optional[int] = None,
                 dist_kind: str = "random", parent=None) -> None:
        super().__init__(parent)
        self._exporter = VideoExporter(
            meta=meta, values=values, trace=trace, settings=settings,
            n_value=n_value, dist_kind=dist_kind,
            on_progress=self._on_progress, should_cancel=self._cancelled_flag)

    def _cancelled_flag(self) -> bool:
        return self.isInterruptionRequested()

    def _on_progress(self, prog: ExportProgress) -> None:
        self.progressed.emit(prog)

    def cancel(self) -> None:
        """请求取消：先停引擎，再让线程尽快退出。"""
        self._exporter.cancel()
        self.requestInterruption()

    def run(self) -> None:                                 # pragma: no cover
        try:
            result = self._exporter.run()
        except ExportError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:                           # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit(result)


# ==========================================================================
# 9. 便捷函数
# ==========================================================================
def export_video(*, meta, values: Sequence[int], trace: Trace,
                 settings: ExportSettings, n_value: Optional[int] = None,
                 dist_kind: str = "random",
                 on_progress: Optional[Callable[[ExportProgress], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None
                 ) -> ExportResult:
    """同步导出（阻塞当前线程），返回 :class:`ExportResult`。

    GUI 里请改用 :class:`ExportWorker`，否则界面会卡住。
    """
    return VideoExporter(
        meta=meta, values=values, trace=trace, settings=settings,
        n_value=n_value, dist_kind=dist_kind,
        on_progress=on_progress, should_cancel=should_cancel).run()
