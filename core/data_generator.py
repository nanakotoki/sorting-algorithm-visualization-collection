# -*- coding: utf-8 -*-
"""8 种初始数据分布生成器。

所有分布都保证元素为 **[1, N] 区间内的正整数**，这样计数排序、基数排序、
桶排序、闪电排序、重力（算盘珠子）排序等值域敏感算法都能直接跑。

支持的分布
----------
``random``              完全随机（1..N 的一个随机排列）
``reversed``            完全逆序
``nearly_sorted``       近乎有序（少量相邻扰动）
``few_unique``          大量重复值（可指定 4 / 8 / 16 种取值）
``sine_wave``           正弦波
``sawtooth``            锯齿波
``organ_pipe``          山峰管风琴
``scrambled_segments``  局部乱序块
"""

from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Optional, Sequence, Tuple

__all__ = ["DISTRIBUTIONS", "DISTRIBUTION_LABELS", "generate", "normalize",
           "describe", "random_seed"]

#: (键, 中文标签)
DISTRIBUTIONS: Tuple[Tuple[str, str], ...] = (
    ("random", "完全随机 (Random)"),
    ("reversed", "完全逆序 (Reversed)"),
    ("nearly_sorted", "近乎有序 (Nearly Sorted)"),
    ("few_unique_4", "少量重复值 ×4 (Few Unique 4)"),
    ("few_unique_8", "少量重复值 ×8 (Few Unique 8)"),
    ("few_unique_16", "少量重复值 ×16 (Few Unique 16)"),
    ("sine_wave", "正弦波 (Sine Wave)"),
    ("sawtooth", "锯齿波 (Sawtooth)"),
    ("organ_pipe", "山峰管风琴 (Organ Pipe)"),
    ("scrambled_segments", "局部乱序块 (Scrambled Segments)"),
)

DISTRIBUTION_LABELS: Dict[str, str] = dict(DISTRIBUTIONS)


def random_seed(seed: Optional[int] = None) -> random.Random:
    """统一随机源；seed 为 None 时使用系统随机。"""
    return random.Random(seed)


# --------------------------------------------------------------------------
# 各分布实现
# --------------------------------------------------------------------------
def _random(n: int, rng: random.Random, **_) -> List[int]:
    vals = list(range(1, n + 1))
    rng.shuffle(vals)
    return vals


def _reversed(n: int, rng: random.Random, **_) -> List[int]:
    return list(range(n, 0, -1))


def _nearly_sorted(n: int, rng: random.Random, swaps_ratio: float = 0.03, **_) -> List[int]:
    vals = list(range(1, n + 1))
    count = max(1, int(n * swaps_ratio))
    for _ in range(count):
        i = rng.randrange(0, max(1, n - 1))
        span = rng.randint(1, max(1, min(6, n - 1)))
        j = min(n - 1, i + span)
        vals[i], vals[j] = vals[j], vals[i]
    return vals


def _few_unique(n: int, rng: random.Random, kinds: int = 4, **_) -> List[int]:
    kinds = max(2, min(kinds, n))
    # 取值在 1..n 内均匀铺开，保证值域仍被充分利用
    pool = sorted({max(1, round(1 + i * (n - 1) / (kinds - 1))) if kinds > 1 else n
                   for i in range(kinds)})
    return [pool[rng.randrange(len(pool))] for _ in range(n)]


def _sine_wave(n: int, rng: random.Random, cycles: float = 2.5, **_) -> List[int]:
    out = []
    for i in range(n):
        t = 0.5 + 0.5 * math.sin(2 * math.pi * cycles * i / max(1, n))
        out.append(int(round(1 + t * (n - 1))))
    return out


def _sawtooth(n: int, rng: random.Random, teeth: int = 4, **_) -> List[int]:
    teeth = max(1, min(teeth, n))
    span = max(1, n // teeth)
    out = []
    for i in range(n):
        pos = i % span
        out.append(int(round(1 + (n - 1) * pos / max(1, span - 1))) if span > 1 else n)
    return out


def _organ_pipe(n: int, rng: random.Random, **_) -> List[int]:
    half = (n + 1) // 2
    up = list(range(1, half + 1))
    down = list(range(half if n % 2 == 0 else half - 1, 0, -1))
    return up + down


def _scrambled_segments(n: int, rng: random.Random, segments: int = 12, **_) -> List[int]:
    vals = list(range(1, n + 1))
    seg = max(2, n // max(1, segments))
    i = 0
    while i < n:
        j = min(n, i + seg)
        block = vals[i:j]
        rng.shuffle(block)
        vals[i:j] = block
        i = j
    return vals


_GENERATORS: Dict[str, Callable[..., List[int]]] = {
    "random": _random,
    "reversed": _reversed,
    "nearly_sorted": _nearly_sorted,
    "few_unique_4": lambda n, rng, **kw: _few_unique(n, rng, kinds=4, **kw),
    "few_unique_8": lambda n, rng, **kw: _few_unique(n, rng, kinds=8, **kw),
    "few_unique_16": lambda n, rng, **kw: _few_unique(n, rng, kinds=16, **kw),
    "sine_wave": _sine_wave,
    "sawtooth": _sawtooth,
    "organ_pipe": _organ_pipe,
    "scrambled_segments": _scrambled_segments,
}


# --------------------------------------------------------------------------
# 公开 API
# --------------------------------------------------------------------------
def generate(kind: str = "random", n: int = 128, seed: Optional[int] = None,
             **kwargs) -> List[int]:
    """生成一个长度为 ``n`` 的初始数组。"""
    n = int(n)
    if n <= 0:
        return []
    gen = _GENERATORS.get(kind)
    if gen is None:
        gen = _random
    rng = random_seed(seed)
    vals = gen(n, rng, **kwargs)
    return normalize(vals, n)


def normalize(values: Sequence[int], n: int) -> List[int]:
    """把任意数值序列归一化到 [1, n]，且保持元素为整数。"""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [max(1, min(n, 1)) for _ in values]
    span = max(1, n - 1)
    out = []
    for v in values:
        x = int(round(1 + (v - lo) * span / (hi - lo)))
        out.append(max(1, min(n, x)))
    return out


def describe(kind: str) -> str:
    return DISTRIBUTION_LABELS.get(kind, kind)


def distribution_keys() -> List[str]:
    return [k for k, _ in DISTRIBUTIONS]
