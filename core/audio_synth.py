# -*- coding: utf-8 -*-
"""实时音效合成引擎与离线音轨生成器。

两条完全独立的音轨通路，共用同一套「数值 → 频率」映射与包络整形函数，
保证**实时听到的声音**与**导出视频里的声音**逐样本一致：

1. :class:`AudioSynth` —— 实时通路
   ``NumPy`` 生成正弦 / 三角 / 方波 / 锯齿波的短音，经 ``sounddevice``
   的低延迟输出流播放。内部维护一个**环形缓冲**：每次比较/交换时把一小段
   已整形好的波形**混音（叠加）**进环形缓冲，音频回调线程只做一次内存拷贝。
   多声部叠加时做软限幅（``tanh``），既不会因为波形叠加越界产生刺耳削波，
   也不会出现爆音。

2. :class:`OfflineTrack` —— 离线通路
   视频导出器逐帧渲染时，往时间轴上登记音符；全部帧渲染完毕后调用
   :meth:`OfflineTrack.render` 一次性生成整条立体声 MP3/WAV 音轨，
   避免「边导出边播放」带来的采样抖动。

防爆音的关键是 **ADSR 包络**：每个音符都有 4 ms 的淡入与至少 6 ms 的淡出，
让波形在起点和终点都严格归零，从根本上消除「咔哒」声。

``sounddevice`` 与 ``scipy`` 都是**可选依赖**：前者缺失（或机器上没有输出
设备）时实时音效自动降级为静音，后者缺失时 WAV 写出回退到标准库 ``wave``。
"""

from __future__ import annotations

import math
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "WAVEFORMS", "value_to_freq", "adsr_envelope", "synthesize_tone",
    "AudioSynth", "OfflineTrack", "write_wav", "audio_backend_status",
]

#: 可选波形（对应 spec 中的正弦 / 三角波，另附方波与锯齿波供扩展）
WAVEFORMS: Tuple[Tuple[str, str], ...] = (
    ("sine", "正弦波 (Sine)"),
    ("triangle", "三角波 (Triangle)"),
    ("square", "方波 (Square)"),
    ("saw", "锯齿波 (Sawtooth)"),
)

#: 音高范围：最低音 → 最高音（Hz）。跨约 3.6 个八度，听感明亮又不刺耳。
FREQ_LO = 110.0
FREQ_HI = 1400.0


# --------------------------------------------------------------------------
# 1. 基础信号处理
# --------------------------------------------------------------------------
def value_to_freq(value: float, n_max: int,
                  lo: float = FREQ_LO, hi: float = FREQ_HI) -> float:
    """把数组元素值**对数映射**到听觉舒适的频率区间。

    线性映射会让小数值挤在低频、大数值挤在高频；取对数后相邻元素之间的
    音程大致相等，排序动画听起来像一串连续上行的音阶，因此又叫「音阶化」。
    """
    if n_max <= 1:
        return lo
    t = (float(value) - 1.0) / float(n_max - 1)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return float(lo * (hi / lo) ** t)


def adsr_envelope(n: int, sample_rate: int,
                  attack: float = 0.004, decay: float = 0.018,
                  sustain: float = 0.36, release: float = 0.055) -> np.ndarray:
    """生成 ADSR 音量包络（长度 ``n`` 的 float32 数组，取值 0~1）。

    * ``attack``  4 ms 淡入 —— 消除起音瞬间的「咔」；
    * ``decay``   衰减到 sustain 电平；
    * ``sustain`` 保持段电平（相对峰值）；
    * ``release`` 结尾淡出 —— 消除收音瞬间的「哒」。

    若音符短到装不下四段，就按比例压缩各段，保证首尾一定为 0。
    """
    n = int(n)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    env = np.zeros(n, dtype=np.float32)
    if n <= 2:                          # 单样本音符无从整形，直接静音
        return env

    a = max(1, int(attack * sample_rate))
    d = max(1, int(decay * sample_rate))
    r = max(1, int(release * sample_rate))
    s = n - a - d - r
    if s <= 0:
        # 音符短到装不下四段：把 a/d/r 按比例压进 n-1 个样本
        avail = n - 1
        total = a + d + r
        a = max(1, int(round(avail * a / total)))
        d = max(1, int(round(avail * d / total)))
        r = max(1, avail - a - d)
        if r < 1:
            a = max(1, avail // 3)
            d = max(1, avail // 3)
            r = max(1, avail - a - d)
        s = max(0, n - a - d - r)

    i = 0                               # 逐段填充，每段都做 min 保护
    seg = min(a, n - i)
    if seg > 0:
        env[i:i + seg] = np.linspace(0.0, 1.0, seg, endpoint=False, dtype=np.float32)
        i += seg
    seg = min(d, n - i)
    if seg > 0:
        env[i:i + seg] = np.linspace(1.0, sustain, seg, endpoint=False, dtype=np.float32)
        i += seg
    seg = min(s, n - i)
    if seg > 0:
        env[i:i + seg] = sustain
        i += seg
    seg = n - i                         # 收尾段：从当前位置平滑归零
    if seg > 0:
        start = float(env[i - 1]) if i > 0 else 1.0
        env[i:i + seg] = np.linspace(start, 0.0, seg, dtype=np.float32)
    env[0] = 0.0
    env[-1] = 0.0
    return env


def _oscillator(waveform: str, phase: np.ndarray) -> np.ndarray:
    """按相位数组生成波形（相位单位：弧度）。"""
    if waveform == "sine":
        return np.sin(phase)
    if waveform == "triangle":
        # 三角波 = 正弦的反正弦，形状规整且谐波比方波干净
        return (2.0 / math.pi) * np.arcsin(np.sin(phase))
    if waveform == "square":
        return np.sign(np.sin(phase))
    if waveform == "saw":
        # 用相位除以 pi 取小数部分得到锯齿
        return 2.0 * ((phase / (2.0 * math.pi)) % 1.0) - 1.0
    return np.sin(phase)


def synthesize_tone(freq: float, duration: float, sample_rate: int,
                    waveform: str = "sine", volume: float = 0.3,
                    decay_to: float = 0.0) -> np.ndarray:
    """合成一个带 ADSR 包络的单音，返回 float32 一维数组。

    ``decay_to`` 用于「铃音」效果：整段按指数缓慢衰减到该比例（0 表示不衰减）。
    """
    n = max(1, int(duration * sample_rate))
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    phase = 2.0 * math.pi * freq * t
    wave_arr = _oscillator(waveform, phase).astype(np.float32)
    wave_arr *= adsr_envelope(n, sample_rate)
    if decay_to > 0.0:
        wave_arr *= np.linspace(1.0, decay_to, n, dtype=np.float32)
    return (wave_arr * float(volume)).astype(np.float32)


def _soft_clip(x: np.ndarray, ceiling: float = 0.92) -> np.ndarray:
    """软限幅：把任意叠加后的信号压进 [-ceiling, ceiling] 且不产生硬削波。"""
    if x.size == 0:
        return x
    return (ceiling * np.tanh(x / ceiling)).astype(np.float32)


# --------------------------------------------------------------------------
# 2. 实时乐器
# --------------------------------------------------------------------------
class AudioSynth:
    """实时音效合成器：把数组元素值变成一段段「叮咚」声。

    典型用法::

        synth = AudioSynth(enabled=True)
        synth.play(value, n_max)          # 单音
        synth.play_many(values, n_max)    # 批量（自动抽样，防止糊成噪音）
        synth.finish_chord(8)             # 排序完成的爬升和弦
        synth.close()

    线程模型：主线程只做「往环形缓冲里混音」；``sounddevice`` 在独立的高
    优先级音频线程里回调取值。两者之间用一把普通互斥锁保护，临界区里只有
    几次 NumPy 的内存操作，不会造成音频 underrun。
    """

    def __init__(self, sample_rate: int = 44100, enabled: bool = False,
                 waveform: str = "sine", volume: float = 0.30,
                 ring_seconds: float = 0.8, max_voices: int = 6,
                 device: Optional[int] = None) -> None:
        self.sample_rate = int(sample_rate)
        self.waveform = waveform
        self.volume = float(volume)
        self.max_voices = int(max_voices)
        self.note_seconds = 0.075         # 单个音符的时长：短促清脆
        self._ring_len = max(1024, int(ring_seconds * self.sample_rate))
        self._ring = np.zeros(self._ring_len, dtype=np.float32)
        self._rpos = 0          # 播放读指针（缓冲里最早未播出的样本）
        self._pending = 0       # 已排入环形缓冲、尚未播出的样本数
        self._lock = threading.Lock()
        self._stream = None
        self._device = device
        self._available = False
        self._error = ""
        self._enabled = False
        if enabled:
            self.set_enabled(True)

    # ---- 设备开关 --------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        """输出设备是否真的打开了（``sounddevice`` 缺失时为 False）。"""
        return self._available

    @property
    def error(self) -> str:
        return self._error

    def set_enabled(self, on: bool) -> bool:
        """打开/关闭实时输出流。返回是否处于可用状态。"""
        on = bool(on)
        if on and not self._available:
            self._open_stream()
        elif not on:
            self._close_stream()
        self._enabled = on and self._available
        return self._available

    def _open_stream(self) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:                       # pragma: no cover
            self._error = f"未安装 sounddevice（{type(exc).__name__}）"
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                latency="low", device=self._device, callback=self._callback,
                blocksize=0)
            self._stream.start()
            self._available = True
            self._error = ""
        except Exception as exc:                       # pragma: no cover
            self._stream = None
            self._available = False
            self._error = f"音频设备打开失败：{exc}"

    def _close_stream(self) -> None:
        st = self._stream
        self._stream = None
        self._available = False
        if st is not None:
            try:                                       # pragma: no cover
                st.stop()
                st.close()
            except Exception:
                pass

    def close(self) -> None:
        self._close_stream()
        self._enabled = False

    # ---- 音频回调（独立线程）--------------------------------------------
    def _callback(self, outdata, frames, time_info, status) -> None:  # pragma: no cover
        ring = self._ring
        with self._lock:
            take = self._pending if self._pending < frames else frames
            start = self._rpos
            if take > 0:
                end = start + take
                if end <= self._ring_len:
                    outdata[:take, 0] = ring[start:end]
                    ring[start:end] = 0.0
                else:                                  # 环形回绕，分两段取
                    head = self._ring_len - start
                    outdata[:head, 0] = ring[start:]
                    outdata[head:take, 0] = ring[:take - head]
                    ring[start:] = 0.0
                    ring[:take - head] = 0.0
                self._rpos = end % self._ring_len
                self._pending -= take
            if take < frames:
                outdata[take:, 0] = 0.0

    # ---- 混音 ------------------------------------------------------------
    def _mix(self, tone: np.ndarray) -> None:
        """把一段波形叠加进环形缓冲（调用方需持有锁或已在锁内）。"""
        if tone.size == 0:
            return
        n = tone.size
        if n > self._ring_len:
            tone = tone[-self._ring_len:]
            n = tone.size
        # 缓冲剩余空间不足时，丢弃最旧的待播样本，保证混音永远完整
        overflow = self._pending + n - self._ring_len
        if overflow > 0:
            drop = min(overflow, self._pending)
            self._rpos = (self._rpos + drop) % self._ring_len
            self._pending -= drop
        w = (self._rpos + self._pending) % self._ring_len
        end = w + n
        if end <= self._ring_len:
            self._ring[w:end] += tone
        else:
            head = self._ring_len - w
            self._ring[w:] += tone[:head]
            self._ring[:n - head] += tone[head:]
        self._pending += n

    def set_waveform(self, waveform: str) -> None:
        self.waveform = waveform

    def play(self, value: float, n_max: int, gain: float = 1.0,
             duration: Optional[float] = None) -> None:
        """播放单个音符（实时通路，未启用时为空操作）。"""
        if not self._enabled or not self._available:
            return
        freq = value_to_freq(value, n_max)
        tone = synthesize_tone(freq, duration or self.note_seconds,
                               self.sample_rate, self.waveform,
                               abs(self.volume) * float(gain))
        with self._lock:
            self._mix(tone)

    def play_many(self, values: Sequence[float], n_max: int,
                  gain: float = 1.0) -> None:
        """批量播放若干音符：超过 ``max_voices`` 时**均匀抽样**。

        极速档一帧可能推进上千步，若把每一步都发声会糊成一团噪音，因此只从
        中均匀抽取少量代表值，既保留「音阶上行」的听感又不失真。
        """
        if not self._enabled or not self._available or not values:
            return
        vals = list(values)
        limit = max(1, self.max_voices)
        if len(vals) > limit:
            step = len(vals) / limit
            vals = [vals[int(i * step)] for i in range(limit)]
        g = abs(self.volume) * float(gain) / max(1.0, math.sqrt(len(vals)) * 0.6)
        with self._lock:
            for v in vals:
                freq = value_to_freq(v, n_max)
                tone = synthesize_tone(freq, self.note_seconds, self.sample_rate,
                                       self.waveform, g)
                self._mix(tone)

    def finish_chord(self, steps: int = 10, n_max: Optional[int] = None) -> None:
        """排序完成时的「和弦爬升」音效：一串快速上行的琶音。"""
        if not self._enabled or not self._available:
            return
        steps = max(2, min(int(steps), 32))
        with self._lock:
            for k in range(steps):
                t = k / (steps - 1)
                freq = FREQ_LO * (FREQ_HI / FREQ_LO) ** t
                tone = synthesize_tone(freq, 0.16, self.sample_rate,
                                       self.waveform,
                                       abs(self.volume) * 0.55,
                                       decay_to=0.05)
                # 让琶音一个接一个，而不是同时炸响
                self._mix(np.zeros(int(0.018 * self.sample_rate), dtype=np.float32))
                self._mix(tone)

    def beep(self, freq: float = 880.0, duration: float = 0.09) -> None:
        if not self._enabled or not self._available:
            return
        with self._lock:
            self._mix(synthesize_tone(freq, duration, self.sample_rate,
                                      self.waveform, abs(self.volume) * 0.7))


# --------------------------------------------------------------------------
# 3. 离线音轨（供视频导出器使用）
# --------------------------------------------------------------------------
@dataclass
class _Note:
    t: float          # 起始时间（秒）
    freq: float
    duration: float
    volume: float
    waveform: str


class OfflineTrack:
    """离线音轨：按时间轴登记音符，最后一次性渲染成立体声 PCM。

    导出 1080P@60FPS 视频时，每一帧渲染完就调用 :meth:`add_value` 把该帧
    发生的事件写进时间轴；渲染完毕后 :meth:`render` 会一次性合成整条音轨，
    因此**音画天然同步**，不可能出现逐帧抖动。
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = int(sample_rate)
        self.notes: List[_Note] = []
        self.note_seconds = 0.055

    def add_value(self, t: float, value: float, n_max: int,
                  gain: float = 1.0, waveform: str = "sine",
                  duration: Optional[float] = None) -> None:
        self.notes.append(_Note(float(t), value_to_freq(value, n_max),
                                duration or self.note_seconds,
                                float(gain), waveform))

    def add_freq(self, t: float, freq: float, duration: float = 0.1,
                 volume: float = 0.3, waveform: str = "sine") -> None:
        self.notes.append(_Note(float(t), float(freq), float(duration),
                                float(volume), waveform))

    def add_finish_chord(self, t: float, steps: int = 10,
                         spread: float = 0.05, volume: float = 0.22,
                         waveform: str = "sine") -> None:
        for k in range(max(2, steps)):
            u = k / (max(2, steps) - 1)
            self.add_freq(t + k * spread,
                          FREQ_LO * (FREQ_HI / FREQ_LO) ** u,
                          0.34, volume, waveform)

    def clear(self) -> None:
        self.notes.clear()

    def render(self, duration: float, master_volume: float = 0.85,
               stereo: bool = True) -> np.ndarray:
        """渲染为 float32 数组：``stereo=True`` 时形状为 ``(N, 2)``。

        所有音符按重叠区**加法混音**，然后统一软限幅，避免多音叠加削顶。
        """
        n = max(1, int(math.ceil(duration * self.sample_rate)))
        mono = np.zeros(n + self.sample_rate, dtype=np.float32)   # 尾部留裕量
        for note in self.notes:
            i0 = max(0, int(round(note.t * self.sample_rate)))
            if i0 >= n:
                continue
            tone = synthesize_tone(note.freq, note.duration, self.sample_rate,
                                   note.waveform, note.volume, decay_to=0.08)
            i1 = min(tone.size, mono.size - i0)
            if i1 > 0:
                mono[i0:i0 + i1] += tone[:i1]
        mono = mono[:n]
        mono = _soft_clip(mono * float(master_volume))
        if not stereo:
            return mono
        # 轻量立体声展宽：左右声道做 ±0.4 ms 的微延时，听感更宽阔
        delay = max(1, int(0.0004 * self.sample_rate))
        left = mono
        right = np.concatenate([np.zeros(delay, dtype=np.float32), mono[:-delay]])
        return np.stack([_soft_clip(left * master_volume),
                         _soft_clip(right * master_volume)], axis=1)


# --------------------------------------------------------------------------
# 4. WAV 写出
# --------------------------------------------------------------------------
def write_wav(path: str | Path, samples: np.ndarray,
              sample_rate: int = 44100) -> str:
    """把 float32 波形写成 16 bit PCM WAV，返回落盘路径。

    优先使用 ``scipy.io.wavfile``（若已安装），否则回退到标准库 ``wave``，
    这样即使不装 SciPy 也能导出视频音轨。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    pcm = np.clip(data, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    channels = int(pcm.shape[1])

    try:                                               # 首选 scipy
        from scipy.io import wavfile as _wav
        _wav.write(str(path), int(sample_rate), pcm)
        return str(path)
    except Exception:
        pass

    with wave.open(str(path), "wb") as fh:             # 回退标准库
        fh.setnchannels(channels)
        fh.setsampwidth(2)
        fh.setframerate(int(sample_rate))
        fh.writeframes(pcm.tobytes())
    return str(path)


def audio_backend_status() -> Dict[str, object]:
    """返回音频后端自检信息（供 HUD / 首启动向导展示）。"""
    info: Dict[str, object] = {"sounddevice": False, "scipy": False,
                               "device": "", "note": ""}
    try:
        import sounddevice as sd
        info["sounddevice"] = True
        try:
            dev = sd.query_devices(kind="output")
            info["device"] = f"{dev.get('name', '?')}"
        except Exception as exc:
            info["note"] = f"无可用输出设备：{exc}"
    except Exception as exc:
        info["note"] = f"未安装 sounddevice：{exc}"
    try:
        import scipy  # noqa: F401
        info["scipy"] = True
    except Exception:
        info["note"] = (str(info["note"]) + "；未安装 scipy（WAV 将回退标准库）").strip("；")
    return info
