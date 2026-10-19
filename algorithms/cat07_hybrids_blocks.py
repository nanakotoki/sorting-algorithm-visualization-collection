# -*- coding: utf-8 -*-
"""类别 07：现代工业级混合与 O(1) 块归并排序（#099 ~ #114，共 16 种）。

本模块收录工业标准库与竞赛实现里最常见的混合排序：

* **自适应归并系**：TimSort / Powersort / Peeksort / Vergesort
  —— 核心是「识别天然有序段 → 用栈或幂次决定归并顺序 → Galloping 跳跃搬运」。
* **内省快排系**：IntroSort / PDQSort
  —— 三数取中 + 递归深度熔断 + 小区间插入 + 坏分区洗牌。
* **多路归并系**：Quadsort / Fluxsort
  —— 四元素比较网络打底 + 四路同时归并 / 稳定三路分区。
* **原地块归并系**：GrailSort / SqrtSort / WikiSort / KotaSort
  —— 用 √N 块长、定长缓存与旋转（Gries-Mills 手摇）把额外空间压到 O(1) 或 O(√N)。
* **分布比较系**：Spreadsort / Ska Sort
  —— 先按数值高位分桶，桶内再退化到比较排序。
* **比较下界系**：Merge-Insertion Sort（Ford-Johnson）、Quick-Shell Hybrid。
"""

from __future__ import annotations

import random
from math import isqrt
from typing import List, Optional, Tuple

from core.protocol import (ROLE_BOUNDARY, ROLE_CURSOR, ROLE_MAX, ROLE_PIVOT,
                          ROLE_SORTED)
from core.registry import register_algo

from ._util import (AUX, MAIN, copy_aux_to_main, gaps_ciura, insertion_sort_range,
                   k_way_merge, lower_bound, rotate_merge, shell_sort_range,
                   sift_down_range, upper_bound)

CATEGORY = "07. 现代混合与块归并排序 (Hybrids & Block Merges)"

# ==========================================================================
# 公共脊架一：天然有序段识别 + 带 Galloping 的稳定归并
# ==========================================================================
_GALLOP = 7          # 同一侧连续取胜多少次后启动倍增跳跃
_MINRUN_MAX = 64     # TimSort minrun 的上界（下界为其一半）


def _minrun_length(n: int) -> int:
    """TimSort 的 minrun：保留 N 的高 6 位，使其落在 [32, 64]。"""
    r = 0
    while n >= _MINRUN_MAX:
        r |= n & 1
        n >>= 1
    return n + r


def _count_run(va, lo: int, hi: int) -> Tuple[int, bool]:
    """识别天然有序段，返回 ``(结束下标（开区间）, 是否严格递减)``。"""
    if hi - lo < 2:
        return hi, False
    if va.gt(lo, lo + 1):
        i = lo + 2
        while i < hi and va.gt(i - 1, i):
            i += 1
        return i, True
    i = lo + 2
    while i < hi and not va.gt(i - 1, i):
        i += 1
    return i, False


def _binary_insert_one(va, lo: int, pos: int) -> None:
    """把 ``arr[pos]`` 稳定地二分插入到已排序的 ``[lo, pos)``。"""
    v = va.get(pos)
    a, b = lo, pos
    while a < b:
        m = (a + b) >> 1
        if va.gt_val(m, v):
            b = m
        else:
            a = m + 1
    k = pos
    while k > a:
        va.swap(k - 1, k)
        k -= 1


def _make_run(va, lo: int, hi: int, minrun: int) -> int:
    """生成一个**保证有序**且长度 ≥ minrun 的段，返回其结束下标。"""
    run_end, desc = _count_run(va, lo, hi)
    if desc:
        va.flip(lo, run_end - 1)
    if run_end - lo < minrun:
        target = min(lo + minrun, hi)
        for p in range(run_end, target):
            _binary_insert_one(va, lo, p)
        run_end = target
    return run_end


def _first_aux_gt(va, lo: int, hi: int, val: int) -> int:
    """aux ``[lo, hi)`` 中第一个 ``> val`` 的下标（用于左侧 Galloping）。"""
    while lo < hi:
        m = (lo + hi) >> 1
        if va.aux_peek(m) > val:
            hi = m
        else:
            lo = m + 1
    return lo


def _first_aux_ge(va, lo: int, hi: int, val: int) -> int:
    while lo < hi:
        m = (lo + hi) >> 1
        if va.aux_peek(m) >= val:
            hi = m
        else:
            lo = m + 1
    return lo


def _merge_lo_gallop(va, lo: int, mid: int, hi: int) -> None:
    """把左段拷入 aux 后自左向右归并，某侧连胜 ≥ GALLOP 时成块搬运。"""
    n1 = mid - lo
    for t in range(n1):
        va.aux_set(t, va.get(lo + t))
    i, j, k = 0, mid, lo
    wl = wr = 0
    while i < n1 and j < hi:
        av = va.aux_peek(i)
        if va.cmp_val(j, av):                       # arr[j] < aux[i] → 取右段
            va.set(k, va.get(j))
            j += 1
            k += 1
            wr += 1
            wl = 0
            if wr >= _GALLOP:
                p = lower_bound(va, j, hi, va.aux_peek(i))   # 右段中首个 ≥ aux[i]
                while j < p:
                    va.set(k, va.get(j))
                    j += 1
                    k += 1
                wr = 0
        else:
            va.set(k, av)
            i += 1
            k += 1
            wl += 1
            wr = 0
            if wl >= _GALLOP:
                p = _first_aux_gt(va, i, n1, va.peek(j))     # aux 中首个 > arr[j]
                while i < p:
                    va.set(k, va.aux_peek(i))
                    i += 1
                    k += 1
                wl = 0
    while i < n1:
        va.set(k, va.aux_peek(i))
        i += 1
        k += 1
    while j < hi:
        va.set(k, va.get(j))
        j += 1
        k += 1


def _merge_hi_gallop(va, lo: int, mid: int, hi: int) -> None:
    """把右段拷入 aux 后自右向左归并（同样支持 Galloping 成块搬运）。"""
    n2 = hi - mid
    for t in range(n2):
        va.aux_set(t, va.get(mid + t))
    i, j, k = mid - 1, n2 - 1, hi - 1
    wl = wr = 0
    while i >= lo and j >= 0:
        av = va.aux_peek(j)
        if va.gt_val(i, av):                        # arr[i] > aux[j] → 取左段
            va.set(k, va.get(i))
            i -= 1
            k -= 1
            wl += 1
            wr = 0
            if wl >= _GALLOP:
                b = upper_bound(va, lo, i + 1, va.aux_peek(j))
                while i >= b:
                    va.set(k, va.get(i))
                    i -= 1
                    k -= 1
                wl = 0
        else:
            va.set(k, av)
            j -= 1
            k -= 1
            wr += 1
            wl = 0
            if wr >= _GALLOP:
                b = _first_aux_ge(va, 0, j + 1, va.peek(i))
                while j >= b:
                    va.set(k, va.aux_peek(j))
                    j -= 1
                    k -= 1
                wr = 0
    while j >= 0:
        va.set(k, va.aux_peek(j))
        j -= 1
        k -= 1
    while i >= lo:
        va.set(k, va.get(i))
        i -= 1
        k -= 1


def _timsort_merge(va, lo: int, mid: int, hi: int) -> None:
    """稳定归并两段（自动选择拷贝更短的一侧，天然有序则直接跳过）。"""
    if lo >= mid or mid >= hi:
        return
    if not va.gt(mid - 1, mid):
        return
    if mid - lo <= hi - mid:
        _merge_lo_gallop(va, lo, mid, hi)
    else:
        _merge_hi_gallop(va, lo, mid, hi)


# ==========================================================================
# 公共脊架二：快排分区 / 堆排序兜底 / 小区间处理
# ==========================================================================
def _sort3(va, a: int, b: int, c: int) -> None:
    """对三个位置排序（把中位数放到 b）。"""
    if va.gt(a, b):
        va.swap(a, b)
    if va.gt(b, c):
        va.swap(b, c)
    if va.gt(a, b):
        va.swap(a, b)


def _heapsort_range(va, lo: int, hi: int) -> None:
    """对闭区间 ``[lo, hi]`` 做原地大顶堆排序（内省排序的深度熔断兜底）。"""
    for i in range(lo + (hi - lo) // 2, lo - 1, -1):
        sift_down_range(va, i, lo, hi)
    for e in range(hi, lo, -1):
        va.swap(lo, e)
        sift_down_range(va, lo, lo, e - 1)


def _partition_mid(va, lo: int, hi: int) -> int:
    """三数取中 + Hoare 分区，返回 ``j``：``[lo, j] ≤ 枢轴 < [j+1, hi]``。"""
    mid = (lo + hi) >> 1
    _sort3(va, lo, mid, hi)
    pivot = va.peek(mid)
    va.mark(mid, ROLE_PIVOT)
    i, j = lo, hi
    while True:
        while va.cmp_val(i, pivot):
            i += 1
        while va.gt_val(j, pivot):
            j -= 1
        if i >= j:
            return max(lo, min(j, hi - 1))
        va.swap(i, j)
        i += 1
        j -= 1


def _buffered_merge(va, lo: int, mid: int, hi: int) -> None:
    """用有限缓冲归并：把**较短**的一段整体暂存到 ``aux``，另一段原地推进。

    与「小块循环搬砖」式归并不同，这里一次把较短段全部搬走，因此不会出现
    写指针追上读指针而覆盖未读数据的问题。
    """
    if lo >= mid or mid >= hi:
        return
    if not va.gt(mid - 1, mid):
        return
    if mid - lo <= hi - mid:
        n1 = mid - lo
        for t in range(n1):
            va.aux_set(t, va.get(lo + t))
        i, j, k = 0, mid, lo
        while i < n1 and j < hi:
            av = va.aux_peek(i)
            if va.cmp_val(j, av):
                va.set(k, va.get(j))
                j += 1
            else:
                va.set(k, av)
                i += 1
            k += 1
        while i < n1:
            va.set(k, va.aux_peek(i))
            i += 1
            k += 1
    else:
        n2 = hi - mid
        for t in range(n2):
            va.aux_set(t, va.get(mid + t))
        i, j, k = mid - 1, n2 - 1, hi - 1
        while i >= lo and j >= 0:
            av = va.aux_peek(j)
            if va.gt_val(i, av):
                va.set(k, va.get(i))
                i -= 1
            else:
                va.set(k, av)
                j -= 1
            k -= 1
        while j >= 0:
            va.set(k, va.aux_peek(j))
            j -= 1
            k -= 1


def _block_merge_pass(va, n: int, width: int, use_buffer: int) -> None:
    """自左向右把相邻两个长度 width 的有序段归并；``use_buffer`` 为可用缓冲格数。"""
    lo = 0
    while lo < n:
        mid = min(lo + width, n)
        hi = min(lo + 2 * width, n)
        if mid < hi:
            if min(mid - lo, hi - mid) <= use_buffer:
                _buffered_merge(va, lo, mid, hi)
            else:
                rotate_merge(va, lo, mid, hi)
        lo += 2 * width


def _initial_blocks(va, n: int, block: int) -> None:
    for lo in range(0, n, block):
        insertion_sort_range(va, lo, min(lo + block, n) - 1)


# ==========================================================================
# #099 TimSort
# ==========================================================================
@register_algo(
    algo_id="099_timsort",
    name_zh="TimSort（工业级自适应归并）",
    name_en="TimSort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="Python / Java 默认排序：按 minrun(32~64) 识别天然单调段并用二分插入补齐，"
         "再用「栈上相邻段必须满足长度不变量」的启发式决定归并顺序；当某一侧连续"
         "取胜达到 7 次时切换为倍增定位的 Galloping 成块搬运。",
)
def tim_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    minrun = _minrun_length(n)
    pending: List[List[int]] = []
    lo = 0
    while lo < n:
        end = _make_run(arr, lo, n, minrun)
        pending.append([lo, end - lo])
        lo = end
        while len(pending) > 1:
            k = len(pending) - 2
            L0 = pending[k - 1][1] if k > 0 else None
            L1 = pending[k][1]
            L2 = pending[k + 1][1]
            if L0 is not None and L0 <= L1 + L2:
                if L0 < L2:
                    k -= 1
            elif L1 > L2:
                break
            a = pending[k]
            b = pending[k + 1]
            _timsort_merge(arr, a[0], a[0] + a[1], b[0] + b[1])
            a[1] += b[1]
            del pending[k + 1]
    while len(pending) > 1:
        a = pending[-2]
        b = pending[-1]
        _timsort_merge(arr, a[0], a[0] + a[1], b[0] + b[1])
        a[1] += b[1]
        pending.pop()
    arr.msg("归并栈清空，数组完全有序")


# ==========================================================================
# #100 Powersort
# ==========================================================================
def _node_power(i: int, n1: int, n2: int) -> int:
    """Munro-Wild 节点幂次：两个 run 中点二进制表示中最高相异位的位序。

    ``i`` 为左段起点，``n1`` / ``n2`` 分别为左、右段长度。两段中点分别是
    ``i + n1/2`` 与 ``i + n1 + n2/2``（以 2 倍缩放做整数运算），它们的
    二进制最高相异位即位序 ``p``——``p`` 越大表示这两段在最近的某一层
    归并树上越靠下，代价越小。
    """
    a = 2 * i + n1
    b = 2 * i + 2 * n1 + n2
    x = a ^ b
    return x.bit_length() - 1 if x else 0


@register_algo(
    algo_id="100_powersort",
    name_zh="Powersort（近最优归并树）",
    name_en="Powersort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="Python 3.11+ 采用的新一代标准排序：用「节点幂次」——两段中点二进制最高"
         "相异位——衡量归并代价，据此构造与最优二叉归并树相差不超过 O(n) 比较的"
         "归并顺序，取代 TimSort 依赖经验常数的栈不变量规则。",
)
def powersort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    minrun = _minrun_length(n)
    stack: List[List[int]] = []          # [start, length, 与右邻的节点幂次]
    lo = 0
    while lo < n:
        length = _make_run(arr, lo, n, minrun) - lo
        cur_start, cur_len = lo, length
        if not stack:
            stack.append([cur_start, cur_len, 0])
        else:
            pw = _node_power(stack[-1][0], stack[-1][1], cur_len)
            while stack and stack[-1][2] >= pw:
                a = stack.pop()
                _timsort_merge(arr, a[0], cur_start, cur_start + cur_len)
                cur_start = a[0]
                cur_len += a[1]
                if stack:
                    pw = _node_power(stack[-1][0], stack[-1][1], cur_len)
            stack.append([cur_start, cur_len, pw])
        lo += length
    while len(stack) > 1:
        a = stack.pop()
        b = stack.pop()
        _timsort_merge(arr, b[0], a[0], a[0] + a[1])
        b[1] += a[1]
        stack.append([b[0], b[1], 0])
    arr.msg("按节点幂次构造的归并树执行完毕")


# ==========================================================================
# #101 Peeksort
# ==========================================================================
def _peeksort(va, lo: int, hi: int) -> None:
    if hi - lo < 2:
        return
    mid = (lo + hi) >> 1
    l = mid
    r = mid
    while r + 1 < hi and not va.gt(r, r + 1):
        r += 1
    while l > lo and not va.gt(l - 1, l):
        l -= 1
    if l == lo and r == hi - 1:
        va.msg("从中点向两侧窥探发现整段已天然有序，本层 O(n) 完成")
        return
    _peeksort(va, lo, l)
    _peeksort(va, r + 1, hi)
    _timsort_merge(va, lo, l, r + 1)
    _timsort_merge(va, lo, r + 1, hi)


@register_algo(
    algo_id="101_peeksort",
    name_zh="Peeksort（自适应窥探归并）",
    name_en="Peeksort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="自顶向下递归时并不急于分割，而是从中点向左右两端「窥探」扩展天然单调段；"
         "若窥探到的有序段恰好覆盖整个区间，则本层瞬间以 O(n) 比较完成，"
         "对近乎有序的数据极为友好。",
)
def peeksort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    _peeksort(arr, 0, n)


# ==========================================================================
# #102 IntroSort
# ==========================================================================
_INTRO_CUTOFF = 16


def _intro(va, lo: int, hi: int, depth: int) -> None:
    while hi - lo > _INTRO_CUTOFF - 1:
        if depth <= 0:
            va.msg("递归深度超过 2·log2(N)，切换为大顶堆排序防退化")
            _heapsort_range(va, lo, hi)
            return
        depth -= 1
        p = _partition_mid(va, lo, hi)
        if p - lo < hi - p:
            _intro(va, lo, p, depth)
            lo = p + 1
        else:
            _intro(va, p + 1, hi, depth)
            hi = p
    insertion_sort_range(va, lo, hi)


@register_algo(
    algo_id="102_introsort",
    name_zh="内省排序 IntroSort（Musser）",
    name_en="IntroSort (Musser)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(log n)", stable=False,
    desc="C++ std::sort 的经典策略：三数取中快排为主，递归深度一旦超过 2⌊log2 N⌋ "
         "就立刻改用大顶堆排序兜底（保证最坏 O(n log n)），长度 ≤ 16 的区间统一"
         "用插入排序收尾。",
)
def introsort(arr):
    n = arr.n
    if n < 2:
        return
    _intro(arr, 0, n - 1, 2 * max(1, n.bit_length() - 1))


# ==========================================================================
# #103 PDQSort
# ==========================================================================
_PDQ_INSERT = 24
_PARTIAL_LIMIT = 24


def _partial_insertion_sort(va, lo: int, hi: int) -> bool:
    """乐观插入探测：只允许少量搬移；搬移次数超限即返回 False 交回快排。"""
    if lo >= hi:
        return True
    limit = 0
    i = lo + 1
    while i <= hi:
        if va.gt(i - 1, i):
            if limit >= _PARTIAL_LIMIT:
                return False
            _binary_insert_one(va, lo, i)
            limit += 1
        i += 1
    return True


def _break_patterns(va, lo: int, hi: int) -> None:
    """坏分区检测命中时，伪随机交换三个位置以打破对抗性输入。"""
    n = hi - lo + 1
    rng = random.Random((n * 2654435761) & 0x7FFFFFFF)
    for _ in range(3):
        a = lo + rng.randrange(n)
        b = lo + rng.randrange(n)
        if a != b:
            va.swap(a, b)


def _pdq(va, lo: int, hi: int, depth: int, leftmost: bool) -> None:
    while hi - lo >= _PDQ_INSERT:
        if depth <= 0:
            _heapsort_range(va, lo, hi)
            return
        depth -= 1
        span = hi - lo + 1
        mid = (lo + hi) >> 1
        if span > 128:                       # 大区间用九数取中（Ninther）
            _sort3(va, lo, lo + span // 8, lo + span // 4)
            _sort3(va, mid - span // 8, mid, mid + span // 8)
            _sort3(va, hi - span // 4, hi - span // 8, hi)
        p = _partition_mid(va, lo, hi)
        if (p - lo + 1) * 8 < span or (hi - p) * 8 < span:
            va.msg("检测到坏分区，洗牌三个位置后重新分区")
            _break_patterns(va, lo, hi)
            _pdq(va, lo, hi, depth, leftmost)
            return
        if p - lo < hi - p:
            _pdq(va, lo, p, depth, leftmost)
            lo = p + 1
            leftmost = False
        else:
            _pdq(va, p + 1, hi, depth, False)
            hi = p
    if leftmost and _partial_insertion_sort(va, lo, hi):
        return
    insertion_sort_range(va, lo, hi)


@register_algo(
    algo_id="103_pdqsort",
    name_zh="PDQSort（模式击败快排）",
    name_en="PDQSort (Pattern-Defeating Quicksort)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(log n)", stable=False,
    desc="Rust 标准库的非稳定排序：在 IntroSort 之上增加「乐观插入探测」（最左侧"
         "区间先试探是否已基本有序）与「坏分区检测」（分区结果严重失衡时随机洗牌"
         "三个位置重来），并保留九数取中与堆排深度熔断。",
)
def pdqsort(arr):
    n = arr.n
    if n < 2:
        return
    _pdq(arr, 0, n - 1, 2 * max(1, n.bit_length() - 1), True)


# ==========================================================================
# #104 Quadsort
# ==========================================================================
def _sort4_network(va, i: int) -> None:
    """四元素比较网络：5 个比较器即可完全排序。"""
    if va.gt(i, i + 1):
        va.swap(i, i + 1)
    if va.gt(i + 2, i + 3):
        va.swap(i + 2, i + 3)
    if va.gt(i, i + 2):
        va.swap(i, i + 2)
    if va.gt(i + 1, i + 3):
        va.swap(i + 1, i + 3)
    if va.gt(i + 1, i + 2):
        va.swap(i + 1, i + 2)


@register_algo(
    algo_id="104_quadsort",
    name_zh="四路归并排序 Quadsort",
    name_en="Quadsort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="先用 4 元素比较网络（奇偶配对预处理）把数组切成有序四元组，随后在"
         "主数组与辅助数组之间乒乓，阶梯式执行「2 路 → 16 路 → 64 路 …」的"
         "**四路同时归并**（一次扫描在 4 个段的队首里取最小者），尾部不足四段"
         "时自动退化为成对归并。",
)
def quadsort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    i = 0
    while i + 4 <= n:
        _sort4_network(arr, i)
        i += 4
    if i < n:
        insertion_sort_range(arr, i, n - 1)
    src, dst = MAIN, AUX
    width = 4
    while width < n:
        fan = 4 if width >= 16 else 2
        step = width * fan
        lo = 0
        while lo < n:
            runs: List[Tuple[int, int]] = []
            for t in range(fan):
                a = lo + t * width
                if a >= n:
                    break
                runs.append((a, min(a + width, n)))
            if len(runs) == 1:
                a, b = runs[0]
                for t in range(a, b):
                    dst.write(arr, t, src.val(arr, t))
            else:
                k_way_merge(arr, src, dst, runs, lo)
            lo += step
        src, dst = dst, src
        width = step
    if src is AUX:
        copy_aux_to_main(arr, 0, n)


# ==========================================================================
# #105 Fluxsort
# ==========================================================================
_FLUX_SMALL = 32


def _flux(va, lo: int, hi: int) -> None:
    n = hi - lo
    if n < 2:
        return
    if n <= _FLUX_SMALL:
        insertion_sort_range(va, lo, hi - 1)
        return
    a = lo + n // 8
    b = lo + n // 2
    c = lo + 7 * n // 8
    pivot = sorted((va.peek(a), va.peek(b), va.peek(c)))[1]
    va.mark(b, ROLE_PIVOT)
    lt = eq = 0
    for t in range(lo, hi):
        if va.cmp_val(t, pivot):
            lt += 1
        elif not va.gt_val(t, pivot):
            eq += 1
    p1, p2, p3 = lo, lo + lt, lo + lt + eq
    for t in range(lo, hi):
        v = va.get(t)
        if v < pivot:
            va.aux_set(p1, v)
            p1 += 1
        elif v > pivot:
            va.aux_set(p3, v)
            p3 += 1
        else:
            va.aux_set(p2, v)
            p2 += 1
    copy_aux_to_main(va, lo, hi)
    _flux(va, lo, lo + lt)
    _flux(va, lo + lt + eq, hi)


@register_algo(
    algo_id="105_fluxsort",
    name_zh="通量排序 Fluxsort",
    name_en="Fluxsort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="现代**稳定**极速排序：先做一次稳定的三路分区（小于/等于/大于枢轴）"
         "并借助辅助区按桶序回写，重复键因此被一次性隔离；随后只对两侧严格"
         "缩小的子区间递归，等于区直接跳过——等价于「稳定三路快排 + 归并引擎」。",
)
def fluxsort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    _flux(arr, 0, n)


# ==========================================================================
# #106 GrailSort
# ==========================================================================
@register_algo(
    algo_id="106_grailsort",
    name_zh="圣杯原地块归并 GrailSort",
    name_en="GrailSort (Simplified Block Merge)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="无需任何外部内存的稳定块归并：先以 √N 为块长对每个块做插入排序，"
         "再把相邻等长块两两归并；归并完全依靠「块旋转」（Gries-Mills 三次翻转）"
         "完成，因此主存额外空间恒为 O(1)，代价是数据搬移常数较大。",
)
def grailsort(arr):
    n = arr.n
    if n < 2:
        return
    block = max(1, isqrt(n))
    arr.msg(f"以 √N ≈ {block} 为块长，逐块插入排序")
    _initial_blocks(arr, n, block)
    width = block
    while width < n:
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                rotate_merge(arr, lo, mid, hi)
            lo += 2 * width
        width *= 2
    arr.msg("块旋转归并逐层完成")


# ==========================================================================
# #107 SqrtSort
# ==========================================================================
@register_algo(
    algo_id="107_sqrtsort",
    name_zh="平方根缓冲块归并 SqrtSort",
    name_en="SqrtSort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(√n)", stable=True,
    desc="只分配 √N 长度的极小辅助数组：块长取 √N，块内插入排序后逐层归并——"
         "归并宽度不超过缓冲容量时把较短的一段整体搬进缓冲直接对撞，宽度超过"
         "缓冲时改用块旋转，从而把主存外部空间压到 O(√N)。",
)
def sqrtsort(arr):
    n = arr.n
    if n < 2:
        return
    b = max(2, isqrt(n))
    arr.aux_init(b)
    _initial_blocks(arr, n, b)
    width = b
    while width < n:
        _block_merge_pass(arr, n, width, b)
        width *= 2


# ==========================================================================
# #108 WikiSort
# ==========================================================================
_WIKI_CACHE = 16


@register_algo(
    algo_id="108_wikisort",
    name_zh="维基块缓存归并 WikiSort",
    name_en="WikiSort (Block Cache Merge)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="基于「小定长缓存（16）+ 内部键块交换」的原地稳定归并：先按缓存粒度"
         "分块插入排序，归并时若较短段能装进缓存就整体搬到缓存里做一次对撞，"
         "否则退化为块旋转（三次翻转）；全程不需要 O(N) 主存缓冲。",
)
def wikisort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(_WIKI_CACHE)
    _initial_blocks(arr, n, _WIKI_CACHE)
    width = _WIKI_CACHE
    while width < n:
        _block_merge_pass(arr, n, width, _WIKI_CACHE)
        width *= 2


# ==========================================================================
# #109 KotaSort
# ==========================================================================
_KOTA_CACHE = 32


def _kota_merge(va, lo: int, mid: int, hi: int) -> None:
    """标记块归并：短段走缓存对撞，长段走块旋转。"""
    if min(mid - lo, hi - mid) <= _KOTA_CACHE:
        _buffered_merge(va, lo, mid, hi)
    else:
        va.mark(lo, ROLE_BOUNDARY)
        va.mark(mid, ROLE_BOUNDARY)
        rotate_merge(va, lo, mid, hi)


@register_algo(
    algo_id="109_kotasort",
    name_zh="科塔原地块交换 KotaSort",
    name_en="KotaSort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="在块缓存归并基础上引入「动态标记块」与**交替归并方向**：偶数层自左向右"
         "扫描、奇数层自右向左扫描，使相邻层产生的小块在下一层入口处自然聚拢，"
         "显著减少块旋转的搬移量；短段仍走 32 格缓存对撞。",
)
def kotasort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(_KOTA_CACHE)
    _initial_blocks(arr, n, _KOTA_CACHE)
    width = _KOTA_CACHE
    level = 0
    while width < n:
        if level % 2 == 0:
            lo = 0
            while lo < n:
                mid = min(lo + width, n)
                hi = min(lo + 2 * width, n)
                if mid < hi:
                    _kota_merge(arr, lo, mid, hi)
                lo += 2 * width
        else:
            # 奇数层自右向左扫描：归并边界必须与偶数层一致（都对齐到 2·width
            # 的倍数），只是**访问次序**反过来，以模拟块缓存自右端命中的效果。
            pairs = []
            lo = 0
            while lo < n:
                mid = min(lo + width, n)
                hi = min(lo + 2 * width, n)
                if mid < hi:
                    pairs.append((lo, mid, hi))
                lo += 2 * width
            for lo, mid, hi in reversed(pairs):
                _kota_merge(arr, lo, mid, hi)
        level += 1
        width *= 2


# ==========================================================================
# #110 Vergesort
# ==========================================================================
@register_algo(
    algo_id="110_vergesort",
    name_zh="宏观趋势侦测 Vergesort",
    name_en="Vergesort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="以 N / log2(N) 为跨步跳跃采样，侦测宏观有序或逆序的大区块：逆序区块"
         "整体翻转成升序，宏观区块随后被确认为真实有序段（识别失败时由二分插入"
         "就地补齐，保证结果绝对正确）；零散乱序部分再交给天然段识别与归并。",
)
def vergesort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    logn = max(1, n.bit_length())
    step = max(1, n // logn)
    minrun = _minrun_length(n)
    runs: List[List[int]] = []
    lo = 0
    while lo < n:
        probe = lo + step
        if probe < n and arr.gt(lo, probe):
            j = lo
            while j + step < n and arr.gt(j, j + step):
                j += step
            end = min(j + step, n)
            if end - lo >= 2 * step:
                arr.msg("侦测到宏观逆序区块，整体翻转为升序")
                arr.flip(lo, end - 1)
        end = _make_run(arr, lo, n, minrun)
        runs.append([lo, end - lo])
        lo = end
    while len(runs) > 1:
        a = runs.pop(0)
        b = runs[0]
        _timsort_merge(arr, a[0], b[0], b[0] + b[1])
        b[0] = a[0]
        b[1] += a[1]


# ==========================================================================
# #111 Spreadsort
# ==========================================================================
_SPREAD_BUCKETS = 8
_SPREAD_SMALL = 32


def _spread(va, lo: int, hi: int, depth: int) -> None:
    n = hi - lo
    if n < 2:
        return
    if n <= _SPREAD_SMALL or depth > 24:
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
    b_count = _SPREAD_BUCKETS
    span = vmax - vmin + 1
    cnt = [0] * b_count
    for i in range(lo, hi):
        cnt[(va.peek(i) - vmin) * b_count // span] += 1
    if max(cnt) == n:                     # 理论上不会发生，作为安全兜底
        insertion_sort_range(va, lo, hi - 1)
        return
    start = [0] * b_count
    s = lo
    for b in range(b_count):
        start[b] = s
        s += cnt[b]
    cur = list(start)
    for i in range(lo, hi):
        v = va.get(i)
        b = (v - vmin) * b_count // span
        va.aux_set(cur[b], v)
        cur[b] += 1
    copy_aux_to_main(va, lo, hi)
    for b in range(b_count):
        if cnt[b] > 1:
            _spread(va, start[b], start[b] + cnt[b], depth + 1)


@register_algo(
    algo_id="111_spreadsort",
    name_zh="扩散排序 Spreadsort（Boost）",
    name_en="Spreadsort (Hybrid Distribution-Comparison)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="Boost 的混合分布比较排序：先按当前值域做等宽分桶（8 桶）把数据「扩散」"
         "到近似位置，桶内元素若仍超出阈值就递归细分；一旦区间元素数 ≤ 32 立即"
         "退化为插入排序，因此兼顾了数值分布的线性速度与比较排序的鲁棒性。",
)
def spreadsort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    _spread(arr, 0, n, 0)


# ==========================================================================
# #112 Ska Sort
# ==========================================================================
_SKA_SMALL = 32


def _ska_msd(va, lo: int, hi: int, shift: int) -> None:
    n = hi - lo
    if n < 2:
        return
    if n <= _SKA_SMALL or shift < 0:
        insertion_sort_range(va, lo, hi - 1)
        return
    cnt = [0] * 256
    for i in range(lo, hi):
        cnt[(va.peek(i) >> shift) & 0xFF] += 1
    start0 = [0] * 256
    s = lo
    for b in range(256):
        start0[b] = s
        s += cnt[b]
    end0 = [start0[b] + cnt[b] for b in range(256)]
    cur = list(start0)
    guard = 0
    for b in range(256):
        while cur[b] < end0[b]:
            guard += 1
            if guard > 4 * n + 64:              # 安全阀（正常永不触发）
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
            _ska_msd(va, start0[b], end0[b], shift - 8)


@register_algo(
    algo_id="112_ska_sort",
    name_zh="字节前缀原地分桶 Ska Sort",
    name_en="Ska Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="按字节（256 桶）统计前缀频次并计算各桶偏移边界，再通过**原地循环置换**"
         "把每个元素直接交换进它所属的桶槽（无需辅助数组）；桶内元素数 ≤ 32 时"
         "切换为插入排序收尾，从最高字节逐级下钻到最低字节。",
)
def ska_sort(arr):
    n = arr.n
    if n < 2:
        return
    maxv = max(arr.values())
    shift = ((maxv.bit_length() - 1) // 8) * 8 if maxv else 0
    _ska_msd(arr, 0, n, shift)


# ==========================================================================
# #113 Merge-Insertion Sort（Ford-Johnson）
# ==========================================================================
def _jacobsthal_order(length: int) -> List[int]:
    """标准 Ford-Johnson 插入顺序：0；然后按雅各布斯塔尔分组倒序插入。"""
    order = [0]
    prev = 1
    k = 3
    while prev < length:
        t = (2 ** k - (-1) ** k) // 3
        for i in range(min(t, length) - 1, prev - 1, -1):
            order.append(i)
        prev = t
        k += 1
    return order


def _fj_sort_indices(va, idx: List[int]) -> List[int]:
    """Ford-Johnson 递归：返回按值升序排列的**物理下标**列表（只发出比较指令）。"""
    m = len(idx)
    if m < 2:
        return list(idx)
    if m == 2:
        a, b = idx[0], idx[1]
        return [a, b] if va.cmp_val(a, va.peek(b)) else [b, a]
    pairs: List[Tuple[int, int]] = []          # (较大者, 较小者)
    for t in range(0, m - 1, 2):
        a, b = idx[t], idx[t + 1]
        if va.cmp_val(a, va.peek(b)):
            pairs.append((b, a))
        else:
            pairs.append((a, b))
    main_idx = [p[0] for p in pairs]
    sorted_main = _fj_sort_indices(va, main_idx)
    pos_of = {pi: k for k, pi in enumerate(main_idx)}
    pend_by_main = [p[1] for p in pairs]
    pend_seq = [pend_by_main[pos_of[si]] for si in sorted_main]
    if m % 2 == 1:
        pend_seq.append(idx[-1])
    result = list(sorted_main)
    for k in _jacobsthal_order(len(pend_seq)):
        if k >= len(pend_seq):
            continue
        a = pend_seq[k]
        if k < len(sorted_main):
            hi_bound = result.index(sorted_main[k])
        else:
            hi_bound = len(result) - 1
        lo2, hi2 = 0, hi_bound + 1
        while lo2 < hi2:
            mid = (lo2 + hi2) >> 1
            if va.gt_val(result[mid], va.peek(a)):
                hi2 = mid
            else:
                lo2 = mid + 1
        result.insert(lo2, a)
    return result


@register_algo(
    algo_id="113_merge_insertion_sort",
    name_zh="归并插入排序（Ford-Johnson）",
    name_en="Merge-Insertion Sort (Ford-Johnson)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="经典「最少比较」排序：先两两配对比较分成主链与副链，对主链递归同上处理，"
         "再严格按雅各布斯塔尔数分组、组内倒序把副链元素**二分插入**（每个副链元素"
         "已知小于其搭档，二分上界因此可以收窄），比较次数逼近信息论下界"
         "⌈log2(N!)⌉。本实现只发出比较与最终回写指令。",
)
def merge_insertion_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.msg("阶段一：两两配对比较，分离主链与副链")
    order = _fj_sort_indices(arr, list(range(n)))
    arr.msg("阶段二：按雅各布斯塔尔顺序二分插入副链元素")
    vals = arr.values()
    for k in range(n):
        arr.mark(k, ROLE_SORTED)
        arr.set(k, vals[order[k]])
    arr.clear_marks()


# ==========================================================================
# #114 Quick-Shell Hybrid Sort
# ==========================================================================
_QS_SHELL_CUTOFF = 96


def _quick_shell(va, lo: int, hi: int) -> None:
    while hi - lo > _QS_SHELL_CUTOFF:
        p = _partition_mid(va, lo, hi)
        if p - lo < hi - p:
            _quick_shell(va, lo, p)
            lo = p + 1
        else:
            _quick_shell(va, p + 1, hi)
            hi = p
    shell_sort_range(va, lo, hi, gaps_ciura(hi - lo + 1))


@register_algo(
    algo_id="114_quick_shell_hybrid",
    name_zh="快排 + 希尔混合排序",
    name_en="Quick-Shell Hybrid Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(log n)", stable=False,
    desc="快排递归到中等粒度区间（≤ 96）后不再往下切成小区间，而是整体切换为"
         "Ciura 步长序列的希尔排序收尾：既避免快排在小数组上的递归与分区常数"
         "开销，又利用希尔排序对「已被粗分区到近似位置」的数据的高效性。",
)
def quick_shell_hybrid_sort(arr):
    n = arr.n
    if n < 2:
        return
    _quick_shell(arr, 0, n - 1)
