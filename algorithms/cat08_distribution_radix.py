# -*- coding: utf-8 -*-
"""类别 08：非比较、基数与分布类排序（#115 ~ #132，共 18 种）。

本类算法**不通过元素两两比较**决定次序，而是利用「值本身」的结构信息：

* **计数/鸽巢系**：Counting / In-Place Counting / Pigeonhole
* **分桶系**：Bucket（均匀 + 插入） / Scatter（多级散射）
* **LSD 基数系**：Base 2 / 4 / 8 / 10 / 16 与原地二进制版本
* **MSD 基数系**：二进制位级快排 / Base 4 / Base 10 / 美国国旗 / 邮差
* **插值定位系**：Flash Sort（闪电排序）
* **机械模拟系**：Gravity Sort（算盘珠子重力下落）

数据生成器保证所有元素都是 [1, N] 区间内的**正整数**，因此本类算法全部适用。
"""

from __future__ import annotations

from typing import Callable

from core.protocol import (ROLE_CONSUMED, ROLE_CURSOR, ROLE_MAX, ROLE_MIN,
                           ROLE_SORTED)
from core.registry import register_algo

from ._util import copy_aux_to_main, insertion_sort_range

CATEGORY = "08. 基数与分布类排序 (Distribution & Radix Sorts)"


# ==========================================================================
# #115 Counting Sort
# ==========================================================================
@register_algo(
    algo_id="115_counting_sort",
    name_zh="计数排序 Counting Sort",
    name_en="Counting Sort",
    category=CATEGORY,
    time_best="O(n + k)", time_avg="O(n + k)", time_worst="O(n + k)",
    space="O(n + k)", stable=True,
    desc="在辅助空间依次展示三个阶段：① 频次直方图统计；② 前缀和累加把频次变成"
         "「值 v 的最后一个落点」；③ 从右向左倒序回写，等于元素相对次序不变。"
         "k 为值域宽度，本实现额外用一块输出缓冲，因此是稳定的。",
    extra={"max_n": 512},
)
def counting_sort(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    arr.aux_init(mx + 1 + n)
    out_off = mx + 1
    arr.msg("阶段一：统计每个取值的出现频次")
    for i in range(n):
        v = arr.get(i)
        arr.aux_set(v, arr.aux_get(v) + 1)
    arr.msg("阶段二：前缀和累加，得到每个取值的最后落点")
    total = 0
    for b in range(mx + 1):
        total += arr.aux_get(b)
        arr.aux_set(b, total)
    arr.msg("阶段三：从右向左倒序回写（保证稳定）")
    for i in range(n - 1, -1, -1):
        v = arr.peek(i)
        p = arr.aux_get(v) - 1
        arr.aux_set(v, p)
        arr.aux_set(out_off + p, v)
    for i in range(n):
        arr.set(i, arr.aux_get(out_off + i))


# ==========================================================================
# #116 In-Place Counting Sort（主数组内循环交换）
# ==========================================================================
def _bucket_cycle_permute(va, lo: int, hi: int, start, end, x_of) -> None:
    """按桶边界 ``[start[b], end[b])`` 在主数组内做原地循环置换归位。

    每个桶维护一个「下一个待填槽位」指针；若当前槽位上的元素不属于本桶，
    就把它交换到它所属桶的下一个空槽，再继续检查被换回来的元素。
    总交换次数不超过元素个数，因此线性时间、O(1) 额外空间。
    """
    n_buckets = len(start)
    cur = list(start)
    guard = 0
    for b in range(n_buckets):
        while cur[b] < end[b]:
            guard += 1
            if guard > (hi - lo) * 4 + 64:
                return
            pos = cur[b]
            d = x_of(va.peek(pos))
            if d == b:
                cur[b] += 1
            else:
                tgt = cur[d]
                va.swap(pos, tgt)
                cur[d] += 1


@register_algo(
    algo_id="116_inplace_counting_sort",
    name_zh="原地计数排序 In-Place Counting Sort",
    name_en="In-Place Counting Sort",
    category=CATEGORY,
    time_best="O(n + k)", time_avg="O(n + k)", time_worst="O(n + k)",
    space="O(k)", stable=False,
    desc="辅助区只保存计数与桶边界，元素**不搬家到辅助区**：先把前缀和转换为"
         "每个桶的起止下标，再用循环置换把元素直接在主数组里交换进对应桶槽。"
         "额外空间仅 O(k)。",
    extra={"max_n": 512},
)
def inplace_counting_sort(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    arr.aux_init(mx + 2)
    for i in range(n):
        v = arr.get(i)
        arr.aux_set(v, arr.aux_get(v) + 1)
    start = [0] * (mx + 1)
    s = 0
    for b in range(mx + 1):
        c = arr.aux_get(b)
        arr.aux_set(b, s)
        start[b] = s
        s += c
    arr.aux_set(mx + 1, s)
    end = [start[b + 1] if b + 1 <= mx else s for b in range(mx + 1)]
    arr.msg("用桶边界做原地循环置换，把元素直接交换进对应桶")
    _bucket_cycle_permute(arr, 0, n, start, end, lambda v: v)


# ==========================================================================
# #117 Pigeonhole Sort
# ==========================================================================
@register_algo(
    algo_id="117_pigeonhole_sort",
    name_zh="鸽巢排序 Pigeonhole Sort",
    name_en="Pigeonhole Sort",
    category=CATEGORY,
    time_best="O(n + k)", time_avg="O(n + k)", time_worst="O(n + k)",
    space="O(k)", stable=False,
    desc="为值域 ``[min, max]`` 一对一开好鸽巢，把每个元素丢进它数值对应的巢位"
         "并计数；随后按巢位从小到大顺序把值依次数写回主数组。只适合值域与"
         "元素数同量级的紧凑数据。",
    extra={"max_n": 512},
)
def pigeonhole_sort(arr):
    n = arr.n
    if n < 2:
        return
    vals = arr.values()
    mn, mx = min(vals), max(vals)
    size = mx - mn + 1
    if size > 4 * n + 8:                     # 值域过散：退化为插入排序
        insertion_sort_range(arr, 0, n - 1)
        return
    arr.aux_init(size)
    arr.msg("阶段一：把每只鸽子放进对应编号的巢")
    for i in range(n):
        v = arr.get(i)
        arr.aux_set(v - mn, arr.aux_get(v - mn) + 1)
    arr.msg("阶段二：按巢位顺序写回主数组")
    k = 0
    for b in range(size):
        c = arr.aux_get(b)
        if c:
            arr.mark(b, ROLE_MAX)
            for _ in range(c):
                arr.set(k, b + mn)
                k += 1
            arr.clear_marks()


# ==========================================================================
# #118 Bucket Sort (Uniform + Insertion)
# ==========================================================================
@register_algo(
    algo_id="118_bucket_sort",
    name_zh="桶排序（均匀分桶 + 插入）",
    name_en="Bucket Sort (Uniform + Insertion)",
    category=CATEGORY,
    time_best="O(n + k)", time_avg="O(n + k)", time_worst="O(n^2)",
    space="O(n + k)", stable=True,
    desc="按值域把数据线性均匀分入 K = √N 个桶（辅助区展示每个桶的内容），"
         "桶内元素天然按桶序成段排列在主数组上，再对每段执行插入排序，"
         "最后按桶序拼接即为全局有序。",
)
def bucket_sort(arr):
    n = arr.n
    if n < 2:
        return
    vals = arr.values()
    mn, mx = min(vals), max(vals)
    if mn == mx:
        return
    k = max(1, int(n ** 0.5))
    span = mx - mn + 1
    arr.aux_init(n)
    cnt = [0] * k
    for i in range(n):
        cnt[min(k - 1, (arr.peek(i) - mn) * k // span)] += 1
    start = [0] * k
    s = 0
    for b in range(k):
        start[b] = s
        s += cnt[b]
    cur = list(start)
    arr.msg(f"按值域均匀分入 {k} 个桶")
    for i in range(n):
        v = arr.get(i)
        b = min(k - 1, (v - mn) * k // span)
        arr.aux_set(cur[b], v)
        cur[b] += 1
    copy_aux_to_main(arr, 0, n)
    arr.msg("桶内插入排序")
    for b in range(k):
        if cnt[b] > 1:
            arr.mark(start[b], ROLE_CURSOR)
            insertion_sort_range(arr, start[b], start[b] + cnt[b] - 1)
            arr.clear_marks()


# ==========================================================================
# #119 Scatter Sort
# ==========================================================================
_SCATTER_BUCKETS = 16
_SCATTER_SMALL = 16


def _scatter(va, lo: int, hi: int, depth: int) -> None:
    n = hi - lo
    if n < 2:
        return
    if n <= _SCATTER_SMALL or depth > 16:
        insertion_sort_range(va, lo, hi - 1)
        return
    vmin = vmax = va.peek(lo)
    for i in range(lo + 1, hi):
        v = va.peek(i)
        if v < vmin:
            vmin = v
        if v > vmax:
            vmax = v
    if vmin == vmax:
        return
    k = _SCATTER_BUCKETS
    span = vmax - vmin + 1
    cnt = [0] * k
    for i in range(lo, hi):
        cnt[(va.peek(i) - vmin) * k // span] += 1
    if max(cnt) == n:
        insertion_sort_range(va, lo, hi - 1)
        return
    start = [0] * k
    s = lo
    for b in range(k):
        start[b] = s
        s += cnt[b]
    cur = list(start)
    for i in range(lo, hi):
        v = va.get(i)
        b = (v - vmin) * k // span
        va.aux_set(cur[b], v)
        cur[b] += 1
    copy_aux_to_main(va, lo, hi)
    for b in range(k):
        if cnt[b] > 1:
            _scatter(va, start[b], start[b] + cnt[b], depth + 1)


@register_algo(
    algo_id="119_scatter_sort",
    name_zh="散射桶归并排序 Scatter Sort",
    name_en="Scatter Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="把「均匀散射分桶」做成**多级递归**：每级按当前子区间的值域分成 16 个桶"
         "散射到辅助区再按桶序写回，桶内元素若仍多于阈值就继续下一级散射；"
         "元素数 ≤ 16 时切换为插入排序收尾。",
)
def scatter_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    _scatter(arr, 0, n, 0)


# ==========================================================================
# #120 ~ #124 LSD 基数排序（Base 2 / 4 / 8 / 10 / 16）
# ==========================================================================
def _lsd_pass(va, base: int, digit: Callable[[int], int], label: str) -> None:
    n = va.n
    cnt = [0] * base
    for i in range(n):
        cnt[digit(va.peek(i))] += 1
    start = [0] * base
    s = 0
    for b in range(base):
        start[b] = s
        s += cnt[b]
    cur = list(start)
    va.msg(f"{label}：按 {base} 个桶稳定分桶收集")
    # 分桶阶段主数组一个字节都不会变（全部写入 aux），旧版播到这里上面那
    # 半边画面是完全静止的 —— 看着像「程序卡住了」。这里边读边把已经搬走
    # 的位置标成 CONSUMED，主数组上就有一条肉眼可见的推进前沿在往前走，
    # 同时下方 aux 一点点被填满，数据到底在怎么流动一目了然。
    # N 很大时降采样，保证指令流不会爆炸（每轮最多 ~192 条 MARK）。
    stride = max(1, n // 192)
    for i in range(n):
        v = va.get(i)
        d = digit(v)
        if i % stride == 0:
            va.mark(i, ROLE_CONSUMED)
        va.aux_set(cur[d], v)
        cur[d] += 1
    va.clear_marks()
    copy_aux_to_main(va, 0, n)


def _lsd_bits(arr, base: int, bits: int, label: str) -> None:
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    mx = max(arr.values())
    mask = base - 1
    shift = 0
    while True:
        _lsd_pass(arr, base, lambda v, s=shift: (v >> s) & mask, f"{label} 第 {shift // bits + 1} 位")
        shift += bits
        if (mx >> shift) == 0:
            break


def _lsd_base10(arr) -> None:
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    mx = max(arr.values())
    div = 1
    level = 1
    while True:
        _lsd_pass(arr, 10, lambda v, d=div: (v // d) % 10, f"十进制第 {level} 位")
        div *= 10
        level += 1
        if mx // div == 0:
            break


@register_algo(
    algo_id="120_radix_lsd_base2",
    name_zh="二进制 LSD 基数排序",
    name_en="Radix Sort LSD (Base 2)",
    category=CATEGORY,
    time_best="O(n·w)", time_avg="O(n·w)", time_worst="O(n·w)",
    space="O(n)", stable=True,
    desc="从最低比特位（bit 0）到最高位逐位执行稳定的 0/1 分桶收集，"
         "每一轮把全部 0 排到前面、1 排到后面；w 为最大值的比特数，"
         "形成极具科技感的二进制分层波浪。",
)
def radix_lsd_base2(arr):
    _lsd_bits(arr, 2, 1, "二进制")


@register_algo(
    algo_id="121_radix_lsd_base4",
    name_zh="四进制 LSD 基数排序",
    name_en="Radix Sort LSD (Base 4)",
    category=CATEGORY,
    time_best="O(n·w/2)", time_avg="O(n·w/2)", time_worst="O(n·w/2)",
    space="O(n)", stable=True,
    desc="每次按 2 个比特位（0~3 共 4 个桶）做一轮稳定分桶收集，"
         "轮数约为二进制版本的一半。",
)
def radix_lsd_base4(arr):
    _lsd_bits(arr, 4, 2, "四进制")


@register_algo(
    algo_id="122_radix_lsd_base8",
    name_zh="八进制 LSD 基数排序",
    name_en="Radix Sort LSD (Base 8)",
    category=CATEGORY,
    time_best="O(n·w/3)", time_avg="O(n·w/3)", time_worst="O(n·w/3)",
    space="O(n)", stable=True,
    desc="每次按 3 个比特位（0~7 共 8 个桶）做一轮稳定分桶收集。",
)
def radix_lsd_base8(arr):
    _lsd_bits(arr, 8, 3, "八进制")


@register_algo(
    algo_id="123_radix_lsd_base10",
    name_zh="十进制 LSD 基数排序",
    name_en="Radix Sort LSD (Base 10)",
    category=CATEGORY,
    time_best="O(n·d)", time_avg="O(n·d)", time_worst="O(n·d)",
    space="O(n)", stable=True,
    desc="按个位、十位、百位…… 依次分入 0~9 十个桶并顺序收集；d 为最大值的"
         "十进制位数。教科书里最经典的基数排序形态。",
)
def radix_lsd_base10(arr):
    _lsd_base10(arr)


@register_algo(
    algo_id="124_radix_lsd_base16",
    name_zh="十六进制 LSD 基数排序",
    name_en="Radix Sort LSD (Base 16)",
    category=CATEGORY,
    time_best="O(n·w/4)", time_avg="O(n·w/4)", time_worst="O(n·w/4)",
    space="O(n)", stable=True,
    desc="按半字节（Nibble，0~15 共 16 个桶）极速分桶收集，轮数最少（约二进制"
         "版本的四分之一），是现代整数基数排序最常用的桶宽。",
)
def radix_lsd_base16(arr):
    _lsd_bits(arr, 16, 4, "十六进制")


# ==========================================================================
# #125 In-Place LSD Radix Sort (Base 2)
# ==========================================================================
@register_algo(
    algo_id="125_inplace_lsd_radix2",
    name_zh="原地二进制 LSD 基数排序",
    name_en="In-Place LSD Radix Sort (Base 2)",
    category=CATEGORY,
    time_best="O(n^2·w)", time_avg="O(n^2·w)", time_worst="O(n^2·w)",
    space="O(1)", stable=True,
    desc="不使用任何辅助数组：每一比特位从左向右扫描，维护「零区末尾」指针，"
         "遇到该位为 0 的元素就把它向左平移插入到零区末尾。平移不改变任何"
         "元素的相对次序，因此全程原地且保持稳定。",
)
def inplace_lsd_radix2(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    bits = max(1, mx.bit_length())
    for s in range(bits):
        arr.msg(f"第 {s + 1} 位（最低位为第 1 位）：把 0 向左平移聚集")
        z = 0
        i = 0
        while i < n:
            if ((arr.peek(i) >> s) & 1) == 0:
                j = i
                while j > z:
                    arr.swap(j - 1, j)
                    j -= 1
                z += 1
            i += 1


# ==========================================================================
# #126 Radix Sort MSD (Base 2 / Binary Quicksort)
# ==========================================================================
def _msd2(va, lo: int, hi: int, bit: int) -> None:
    if hi - lo < 2 or bit < 0:
        return
    if hi - lo <= 16:
        insertion_sort_range(va, lo, hi - 1)
        return
    va.msg(f"按第 {bit + 1} 位原地切分（0 向左、1 向右）")
    i, j = lo, hi - 1
    while True:
        while i <= j and ((va.get(i) >> bit) & 1) == 0:
            i += 1
        while i <= j and ((va.get(j) >> bit) & 1) == 1:
            j -= 1
        if i >= j:
            break
        va.swap(i, j)
        i += 1
        j -= 1
    _msd2(va, lo, i, bit - 1)
    _msd2(va, i, hi, bit - 1)


@register_algo(
    algo_id="126_radix_msd_base2",
    name_zh="二进制 MSD 基数交换（位级快排）",
    name_en="Radix Sort MSD (Base 2 / Binary Quicksort)",
    category=CATEGORY,
    time_best="O(n·w)", time_avg="O(n·w)", time_worst="O(n·w)",
    space="O(log n)", stable=False,
    desc="从最高有效位开始，用左右双指针把最高位为 0 与为 1 的元素原地交换切分，"
         "再各自递归到下一比特位；这就是教科书中的「二进制快排」。无需辅助数组，"
         "小区间（≤ 16）切换插入排序。",
)
def radix_msd_base2(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    _msd2(arr, 0, n, max(0, mx.bit_length() - 1))


# ==========================================================================
# #127 / #128 / #131 MSD 分桶基数（Base 4 / Base 10 / 邮差）
# ==========================================================================
def _msd_bucket(va, lo: int, hi: int, level: int, base: int,
                digit: Callable[[int, int], int], label: str,
                cutoff: int = 16) -> None:
    n = hi - lo
    if n < 2 or level < 0:
        return
    if cutoff and n <= cutoff:
        insertion_sort_range(va, lo, hi - 1)
        return
    cnt = [0] * base
    for i in range(lo, hi):
        cnt[digit(va.peek(i), level)] += 1
    start = [0] * base
    s = lo
    for b in range(base):
        start[b] = s
        s += cnt[b]
    cur = list(start)
    va.msg(f"{label} 第 {level + 1} 级分桶（自高位向低位）")
    for i in range(lo, hi):
        v = va.get(i)
        b = digit(v, level)
        va.aux_set(cur[b], v)
        cur[b] += 1
    copy_aux_to_main(va, lo, hi)
    for b in range(base):
        if cnt[b] > 1:
            _msd_bucket(va, start[b], start[b] + cnt[b], level - 1, base,
                        digit, label, cutoff)


@register_algo(
    algo_id="127_radix_msd_base4",
    name_zh="四进制 MSD 基数排序",
    name_en="Radix Sort MSD (Base 4)",
    category=CATEGORY,
    time_best="O(n·w/2)", time_avg="O(n·w/2)", time_worst="O(n·w/2)",
    space="O(n)", stable=True,
    desc="自顶向下按四进制高位递归分桶回写：先按最高 2 个比特把数据分成 4 组，"
         "写回主数组后逐组下钻到下一组比特位；桶内元素数 ≤ 16 时插入排序收尾。",
)
def radix_msd_base4(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    mx = max(arr.values())
    levels = max(0, (mx.bit_length() - 1) // 2)
    _msd_bucket(arr, 0, n, levels, 4, lambda v, lv: (v >> (2 * lv)) & 3, "四进制")


@register_algo(
    algo_id="128_radix_msd_base10",
    name_zh="十进制 MSD 基数排序",
    name_en="Radix Sort MSD (Base 10)",
    category=CATEGORY,
    time_best="O(n·d)", time_avg="O(n·d)", time_worst="O(n·d)",
    space="O(n)", stable=True,
    desc="自顶向下按十进制最高位（千位、百位、十位、个位）递归分桶回写，"
         "小桶（≤ 16 个元素）自动切换为插入排序，避免为微不足道的桶继续开桶。",
)
def radix_msd_base10(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    mx = max(arr.values())
    levels = len(str(mx)) - 1
    _msd_bucket(arr, 0, n, levels, 10, lambda v, lv: (v // (10 ** lv)) % 10, "十进制")


@register_algo(
    algo_id="131_postman_sort",
    name_zh="邮差排序 Postman Sort",
    name_en="Postman Sort",
    category=CATEGORY,
    time_best="O(n·d)", time_avg="O(n·d)", time_worst="O(n·d)",
    space="O(n)", stable=True,
    desc="模拟邮政分拣的三级格口：先把信件按「区」投进 10 个格口并依原顺序收拢，"
         "再在区内按「市」细分，最后按「门牌号」细分——即固定深度、不设插入兜底的"
         "纯 MSD 十进制基数分拣，级级稳定因而整体稳定。",
)
def postman_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    mx = max(arr.values())
    levels = len(str(mx)) - 1
    arr.msg("邮件按 区 → 市 → 门牌号 三级格口分拣")
    _msd_bucket(arr, 0, n, levels, 10, lambda v, lv: (v // (10 ** lv)) % 10, "邮差分拣", cutoff=0)


# ==========================================================================
# #129 American Flag Sort
# ==========================================================================
def _american_flag(va, lo: int, hi: int, shift: int) -> None:
    n = hi - lo
    if n < 2:
        return
    if n <= 32 or shift < 0:
        insertion_sort_range(va, lo, hi - 1)
        return
    cnt = [0] * 256
    for i in range(lo, hi):
        cnt[(va.peek(i) >> shift) & 0xFF] += 1
    start = [0] * 256
    s = lo
    for b in range(256):
        start[b] = s
        s += cnt[b]
    end = [start[b] + cnt[b] for b in range(256)]
    va.msg("按字节统计频次得到桶边界，随后原地循环置换归位")
    cur = list(start)
    guard = 0
    for b in range(256):
        while cur[b] < end[b]:
            guard += 1
            if guard > (hi - lo) * 4 + 256:
                break
            pos = cur[b]
            v = va.get(pos)
            d = (v >> shift) & 0xFF
            if d == b:
                cur[b] += 1
            else:
                tgt = cur[d]
                va.swap(pos, tgt)
                cur[d] += 1
    for b in range(256):
        if cnt[b] > 1:
            _american_flag(va, start[b], end[b], shift - 8)


@register_algo(
    algo_id="129_american_flag_sort",
    name_zh="美国国旗排序 American Flag Sort",
    name_en="American Flag Sort",
    category=CATEGORY,
    time_best="O(n·w)", time_avg="O(n·w)", time_worst="O(n·w)",
    space="O(1)", stable=False,
    desc="McIlroy 的经典原地基数排序：先统计 256 个字节桶的频次并算出每个桶的"
         "起始偏移边界，再通过**原地循环置换**把元素直接交换进对应桶槽，"
         "主存额外空间恒为 O(1)；随后自最高字节向最低字节递归。",
)
def american_flag_sort(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    shift = ((mx.bit_length() - 1) // 8) * 8 if mx else 0
    _american_flag(arr, 0, n, shift)


# ==========================================================================
# #130 Flash Sort
# ==========================================================================
@register_algo(
    algo_id="130_flash_sort",
    name_zh="闪电排序 Flash Sort（Neubert）",
    name_en="Flash Sort (Neubert)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n)", time_worst="O(n^2)",
    space="O(m)", stable=False,
    desc="线性插值定位 + 循环置换：用 L(A[i]) = 1 + ⌊(m-1)(A[i]-Amin)/(Amax-Amin)⌋ "
         "把数据划分成约 m = 0.43N 个「类」，原地循环置换把元素一次送到近似位置，"
         "最后用一趟插入排序收尾。均匀分布下接近线性。",
)
def flash_sort(arr):
    n = arr.n
    if n < 2:
        return
    vals = arr.values()
    mn, mx = min(vals), max(vals)
    if mn == mx:
        return
    m = max(2, int(0.43 * n))
    span = mx - mn + 1
    arr.aux_init(m + 1)

    def class_of(v: int) -> int:
        c = (m - 1) * (v - mn) // span
        return m - 2 if c >= m - 1 else c

    for i in range(n):
        arr.aux_set(class_of(arr.peek(i)), arr.aux_peek(class_of(arr.peek(i))) + 1)
    start = [0] * (m + 1)
    s = 0
    for b in range(m):
        start[b] = s
        s += arr.aux_peek(b)
    start[m] = n
    arr.msg(f"划分为 {m} 个插值类，原地循环置换把元素送入近似位置")
    cur = list(start)
    guard = 0
    for b in range(m):
        while cur[b] < start[b + 1]:
            guard += 1
            if guard > 4 * n + 64:
                break
            pos = cur[b]
            d = class_of(arr.get(pos))
            if d == b:
                cur[b] += 1
            else:
                tgt = cur[d]
                arr.swap(pos, tgt)
                cur[d] += 1
    arr.msg("各元素已落入正确的值域类，插入排序收尾")
    insertion_sort_range(arr, 0, n - 1)


# ==========================================================================
# #132 Gravity Sort (Bead Sort)
# ==========================================================================
@register_algo(
    algo_id="132_gravity_sort",
    name_zh="重力排序（算盘珠子）",
    name_en="Gravity Sort (Bead Sort)",
    category=CATEGORY,
    time_best="O(n·k)", time_avg="O(n·k)", time_worst="O(n·k)",
    space="O(n·k)", stable=False,
    desc="把每个正整数展开为水平算盘杆上的一排珠子（第 i 根杆前 a[i] 列有珠子），"
         "模拟珠子在重力作用下逐列**同时**坠落到框架底部，最后读出每行的珠子数即为"
         "有序序列。视觉冲击力极强，但空间为 O(N·k)，因此演示规模受限。",
    extra={"max_n": 128},
)
def gravity_sort(arr):
    n = arr.n
    if n < 2:
        return
    mx = max(arr.values())
    if mx < 1:
        return
    arr.aux_init(n * mx)
    arr.msg("阶段一：把每根算盘杆上的珠子立起来")
    for i in range(n):
        v = arr.get(i)
        base = i * mx
        for c in range(v):
            arr.aux_set(base + c, 1)
    arr.msg("阶段二：珠子在重力作用下逐列坠落到底部")
    for c in range(mx):
        cnt = 0
        for r in range(n):
            if arr.aux_peek(r * mx + c) == 1:
                cnt += 1
        for r in range(n):
            want = 1 if r >= n - cnt else 0
            if arr.aux_peek(r * mx + c) != want:
                arr.aux_set(r * mx + c, want)
    arr.msg("阶段三：读出每根杆上的珠子数，即得升序序列")
    for i in range(n):
        base = i * mx
        s = 0
        for c in range(mx):
            if arr.aux_peek(base + c) == 1:
                s += 1
        arr.set(i, s)
        arr.mark(i, ROLE_SORTED)
