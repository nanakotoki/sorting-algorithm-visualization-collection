# -*- coding: utf-8 -*-
"""类别 05 —— 快速排序全家族（#069 ~ #084，共 16 种）。

分区方案谱系（Lomuto / Hoare / 双左指针 / 荷兰国旗 / Bentley-McIlroy 三路 /
块缓冲无分支 / 稳定分区），基准选择谱系（随机 / 三数 / 五数 / Tukey 九数取中 /
比例分位），多轴谱系（Yaroslavskiy 双轴、三轴四路），以及显式栈非递归实现。
"""

from __future__ import annotations

import random

from core.protocol import ROLE_BOUNDARY, ROLE_CURSOR, ROLE_PIVOT, ROLE_SORTED
from core.registry import register_algo

from ._util import insertion_sort_range, rotate_blocks

CATEGORY = "05. 快速排序全家族 (Quick Sorts)"

#: 小区间阈值：低于该长度改用插入排序收尾（工业实现通行做法）
CUTOFF = 12


# ==========================================================================
# 共用工具：抽样取中 / 各分区方案
# ==========================================================================
def _sort3(arr, a: int, b: int, c: int) -> int:
    """就地排好三个位置的值，返回中间位置下标（即中位数所在位置）。"""
    if arr.gt(a, b):
        arr.swap(a, b)
    if arr.gt(b, c):
        arr.swap(b, c)
    if arr.gt(a, b):
        arr.swap(a, b)
    return b


def _lomuto(arr, lo: int, hi: int) -> int:
    """Lomuto 单路分区：基准必须已位于 ``hi``，返回基准最终位置。"""
    i = lo - 1
    for j in range(lo, hi):
        if arr.cmp(j, hi):
            i += 1
            arr.swap(i, j)
    arr.swap(i + 1, hi)
    return i + 1


def _pick_median3(arr, lo: int, hi: int) -> int:
    """三数取中：返回中位数所在下标（位置已被就地整理）。"""
    return _sort3(arr, lo, (lo + hi) >> 1, hi)


def _pick_median5(arr, lo: int, hi: int) -> int:
    """五数取中：取 5 个均匀采样点做局部冒泡排序，返回第 3 个（中位数）。"""
    idx = [lo + (hi - lo) * k // 4 for k in range(5)]
    for _ in range(4):
        for t in range(4):
            if arr.gt(idx[t], idx[t + 1]):
                arr.swap(idx[t], idx[t + 1])
    return idx[2]


def _pick_ninther(arr, lo: int, hi: int) -> int:
    """Tukey 九数取中：9 个采样点分 3 组各取中位数，再取这 3 个中位数的中位数。"""
    idx = [lo + (hi - lo) * k // 8 for k in range(9)]
    m1 = _sort3(arr, idx[0], idx[1], idx[2])
    m2 = _sort3(arr, idx[3], idx[4], idx[5])
    m3 = _sort3(arr, idx[6], idx[7], idx[8])
    return _sort3(arr, m1, m2, m3)


def _pivot_to_hi(arr, lo: int, hi: int, picker) -> None:
    """用给定选取器挑出基准并交换到 ``hi``，随后即可调用 Lomuto。"""
    m = picker(arr, lo, hi)
    if m != hi:
        arr.swap(m, hi)
    arr.mark(hi, ROLE_PIVOT)


def _qsort_with_partition(arr, lo: int, hi: int, picker, partition):
    """通用快排骨架：小区间插入排序 + 较短侧优先递归（尾递归消除）。"""
    while lo < hi:
        if hi - lo < CUTOFF:
            insertion_sort_range(arr, lo, hi)
            return
        _pivot_to_hi(arr, lo, hi, picker)
        p = partition(arr, lo, hi)
        arr.mark(p, ROLE_SORTED)
        if p - lo < hi - p:
            _qsort_with_partition(arr, lo, p - 1, picker, partition)
            lo = p + 1
        else:
            _qsort_with_partition(arr, p + 1, hi, picker, partition)
            hi = p - 1


def _picker_last(arr, lo: int, hi: int) -> int:
    return hi


# ==========================================================================
# 069 ~ 071  Lomuto / Hoare / 双左指针
# ==========================================================================
@register_algo(
    algo_id="069_quicksort_lomuto",
    name_zh="快速排序（Lomuto 单路分区）",
    name_en="Quick Sort (Lomuto Partition)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="最易理解的单路分区：单侧同向快慢指针扫描，把小于基准的元素依次换到左区。"
         "对已排序数据退化为 O(N^2)，仅作教学基线。",
)
def quicksort_lomuto(arr):
    n = arr.n
    if n > 1:
        _qsort_with_partition(arr, 0, n - 1, _picker_last, _lomuto)


@register_algo(
    algo_id="070_quicksort_hoare",
    name_zh="快速排序（Hoare 双指针分区）",
    name_en="Quick Sort (Hoare Partition)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="Hoare 1961 原始分区：左右两端相向扫描、遇逆序就交换，交换次数约为"
         "Lomuto 的三分之一，是各标准库快排的事实基础。",
)
def quicksort_hoare(arr):
    n = arr.n
    if n < 2:
        return

    def part(lo, hi):
        pivot = arr.peek(lo)
        arr.mark(lo, ROLE_PIVOT)
        i, j = lo - 1, hi + 1
        while True:
            i += 1
            while i < hi and arr.cmp_val(i, pivot):
                i += 1
            j -= 1
            while j > lo and arr.gt_val(j, pivot):
                j -= 1
            if i >= j:
                return j
            arr.swap(i, j)

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            p = part(lo, hi)
            p = min(max(p, lo), hi - 1)
            if p - lo < hi - p:
                rec(lo, p)
                lo = p + 1
            else:
                rec(p + 1, hi)
                hi = p

    rec(0, n - 1)


@register_algo(
    algo_id="071_quicksort_double_left_pointer",
    name_zh="快速排序（双左指针分区）",
    name_en="Quick Sort (Double Left Pointer)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="两个指针都从左端同向出发的镜像分区：先把大于基准的元素攒在左端，"
         "分区结束时用一次块旋转把两段对调，等于基准的元素全部落在基准右侧。",
)
def quicksort_double_left_pointer(arr):
    n = arr.n
    if n < 2:
        return

    def part(lo, hi):
        pivot = arr.peek(hi)
        arr.mark(hi, ROLE_PIVOT)
        i = lo
        j = lo
        while j < hi:
            if arr.gt_val(j, pivot):
                arr.swap(i, j)
                i += 1
            j += 1
        # [lo, i) 全是 > pivot，[i, hi) 全是 <= pivot → 旋转成 <= 在前
        rotate_blocks(arr, lo, i, hi + 1)
        return lo + (hi - i)

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            p = part(lo, hi)
            arr.mark(p, ROLE_SORTED)
            if p - lo < hi - p:
                rec(lo, p - 1)
                lo = p + 1
            else:
                rec(p + 1, hi)
                hi = p - 1

    rec(0, n - 1)


# ==========================================================================
# 072 ~ 075  基准选择谱系
# ==========================================================================
@register_algo(
    algo_id="072_quicksort_random_pivot",
    name_zh="快速排序（随机化基准）",
    name_en="Quick Sort (Random Pivot)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="每次在区间内随机挑一个位置作基准，使任意固定输入上的期望复杂度都落在"
         "O(N log N)，对抗逆序、管风琴等针对固定基准的构造性数据。",
)
def quicksort_random_pivot(arr):
    n = arr.n
    if n < 2:
        return

    def picker(arr, lo, hi):
        rng = random.Random(lo * 1000003 + hi)
        return rng.randint(lo, hi)

    _qsort_with_partition(arr, 0, n - 1, picker, _lomuto)


@register_algo(
    algo_id="073_quicksort_median_of_three",
    name_zh="快速排序（三数取中）",
    name_en="Quick Sort (Median-of-Three)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="取左、中、右三点中位数作基准，让已排序 / 逆序输入直接得到最优二分；"
         "配合较短区间优先递归把栈深压在 O(log N)。",
)
def quicksort_median_of_three(arr):
    n = arr.n
    if n > 1:
        _qsort_with_partition(arr, 0, n - 1, _pick_median3, _lomuto)


@register_algo(
    algo_id="074_quicksort_median_of_five",
    name_zh="快速排序（五数取中）",
    name_en="Quick Sort (Median-of-Five)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="采样 5 个均匀分布的位置并做局部排序取中位数作基准：比三数取中更抗"
         "构造性坏数据，额外的常数比较换来更均衡的期望划分。",
)
def quicksort_median_of_five(arr):
    n = arr.n
    if n > 1:
        _qsort_with_partition(arr, 0, n - 1, _pick_median5, _lomuto)


@register_algo(
    algo_id="075_quicksort_ninther",
    name_zh="快速排序（Tukey 九数取中）",
    name_en="Quick Sort (Tukey's Ninther)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="Tukey 提出的 Ninther：9 个采样点分 3 组各取中位数，再取这 3 个中位数的"
         "中位数作基准——极稳健的基准估计，被广泛用于高质量快排实现。",
)
def quicksort_ninther(arr):
    n = arr.n
    if n > 1:
        _qsort_with_partition(arr, 0, n - 1, _pick_ninther, _lomuto)


# ==========================================================================
# 076 ~ 077  多轴快排
# ==========================================================================
@register_algo(
    algo_id="076_dual_pivot_quicksort",
    name_zh="双轴快速排序（Yaroslavskiy）",
    name_en="Dual-Pivot Quick Sort (Yaroslavskiy)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="取 P1 ≤ P2 两个基准，一趟扫描切成 < P1、[P1, P2]、> P2 三段递归。"
         "JDK 7 起 java.util.Arrays.sort 的默认实现，缓存命中率显著优于单轴。",
)
def dual_pivot_quicksort(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        if lo >= hi:
            return
        if hi - lo < CUTOFF:
            insertion_sort_range(arr, lo, hi)
            return
        if arr.gt(lo, hi):
            arr.swap(lo, hi)
        p1 = arr.peek(lo)
        p2 = arr.peek(hi)
        arr.mark(lo, ROLE_PIVOT)
        arr.mark(hi, ROLE_PIVOT)
        l = lo + 1
        g = hi - 1
        k = l
        while k <= g:
            if arr.cmp_val(k, p1):
                arr.swap(k, l)
                l += 1
            elif arr.gt_val(k, p2):
                while k < g and arr.gt_val(g, p2):
                    g -= 1
                arr.swap(k, g)
                g -= 1
                if arr.cmp_val(k, p1):
                    arr.swap(k, l)
                    l += 1
            k += 1
        l -= 1
        g += 1
        arr.swap(lo, l)
        arr.swap(hi, g)
        arr.mark(l, ROLE_SORTED)
        arr.mark(g, ROLE_SORTED)
        rec(lo, l - 1)
        rec(l + 1, g - 1)
        rec(g + 1, hi)

    rec(0, n - 1)


@register_algo(
    algo_id="077_three_pivot_quicksort",
    name_zh="三轴四路快速排序",
    name_en="Multi-Pivot Quick Sort (3-Pivot 4-Way)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="采样 5 点排序后取中间三值作 P1 ≤ P2 ≤ P3，一趟统计把区间切成"
         "四段（< P1、[P1,P2)、[P2,P3)、≥ P3）后并行递归——每层比较次数更少，"
         "前三层的递归深度也更有优势。",
)
def three_pivot_quicksort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if lo >= hi:
            return
        if hi - lo < 24:
            insertion_sort_range(arr, lo, hi)
            return
        span = hi - lo
        samples = [arr.peek(lo + span * k // 4) for k in range(5)]
        samples.sort()
        p1, p2, p3 = samples[1], samples[2], samples[3]
        arr.mark(lo, ROLE_PIVOT)
        arr.mark(hi, ROLE_PIVOT)
        buckets = []
        cnt = [0, 0, 0, 0]
        for t in range(lo, hi + 1):
            if arr.cmp_val(t, p1):
                b = 0
            elif arr.cmp_val(t, p2):
                b = 1
            elif arr.cmp_val(t, p3):
                b = 2
            else:
                b = 3
            buckets.append(b)
            cnt[b] += 1
        cur = [lo, lo + cnt[0], lo + cnt[0] + cnt[1], lo + cnt[0] + cnt[1] + cnt[2]]
        if cnt[3] >= span + 1:
            # 三轴退化为「全部落在最后一个桶」（大量重复键的典型情形）：
            # 改用中位轴做荷兰国旗三路切分，保证等于区被排除、递归一定前进。
            arr.msg("三轴退化：改用荷兰国旗三路切分继续")
            pivot = p2
            lt, i2, gt = lo, lo, hi
            while i2 <= gt:
                if arr.cmp_val(i2, pivot):
                    arr.swap(lt, i2)
                    lt += 1
                    i2 += 1
                elif arr.gt_val(i2, pivot):
                    arr.swap(i2, gt)
                    gt -= 1
                else:
                    i2 += 1
            rec(lo, lt - 1)
            rec(gt + 1, hi)
            return
        for t in range(lo, hi + 1):
            v = arr.get(t)
            b = buckets[t - lo]
            arr.aux_set(cur[b], v)
            cur[b] += 1
        for t in range(lo, hi + 1):
            arr.set(t, arr.aux_peek(t))
        b0 = lo + cnt[0]
        b1 = b0 + cnt[1]
        b2 = b1 + cnt[2]
        rec(lo, b0 - 1)
        rec(b0, b1 - 1)
        rec(b1, b2 - 1)
        rec(b2, hi)

    rec(0, n - 1)


# ==========================================================================
# 078 ~ 079  三路切分谱系
# ==========================================================================
@register_algo(
    algo_id="078_quicksort_three_way_dnf",
    name_zh="快速排序（荷兰国旗三路切分）",
    name_en="Three-Way Quick Sort (Dutch National Flag)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="Dijkstra 荷兰国旗算法：一趟切成 < P、== P、> P 三段，等于区不再参与"
         "递归——面对大量重复键的数据直接退化为 O(N)。",
)
def quicksort_three_way_dnf(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            m = _pick_median3(arr, lo, hi)
            pivot = arr.peek(m)
            arr.mark(m, ROLE_PIVOT)
            lt, i, gt = lo, lo, hi
            while i <= gt:
                if arr.cmp_val(i, pivot):
                    arr.swap(lt, i)
                    lt += 1
                    i += 1
                elif arr.gt_val(i, pivot):
                    arr.swap(i, gt)
                    gt -= 1
                else:
                    i += 1
            for t in range(lt, gt + 1):
                arr.mark(t, ROLE_SORTED)
            if lt - lo < hi - gt:
                rec(lo, lt - 1)
                lo = gt + 1
            else:
                rec(gt + 1, hi)
                hi = lt - 1

    rec(0, n - 1)


@register_algo(
    algo_id="079_quicksort_bentley_mcilroy",
    name_zh="快速排序（Bentley-McIlroy 三路切分）",
    name_en="Bentley-McIlroy Three-Way Quick Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(log n)", stable=False,
    desc="扫描时先把等于基准的元素一路交换堆积到区间外端，切分结束后再用两次"
         "块旋转把它们整体翻转到中心；后续递归直接跳过等于区，"
         "在无重复元素时也不产生额外交换开销。",
)
def quicksort_bentley_mcilroy(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            m = _pick_median3(arr, lo, hi)
            arr.swap(lo, m)
            v = arr.peek(lo)
            arr.mark(lo, ROLE_PIVOT)
            # 阶段一：< v 留在左区，>= v 交换到右侧
            i, j = lo + 1, hi
            while i <= j:
                if arr.cmp_val(i, v):
                    i += 1
                else:
                    arr.swap(i, j)
                    j -= 1
            # 阶段二：在右侧 >= v 区里把 == v 继续推到最右端
            x, y = i, hi
            while x <= y:
                if arr.gt_val(x, v):
                    x += 1
                else:
                    arr.swap(x, y)
                    y -= 1
            # 阶段三：两次块旋转，把主元与等于区从两端翻转到中心
            rotate_blocks(arr, lo, lo + 1, i)
            rotate_blocks(arr, i, x, hi + 1)
            right = i + hi + 1 - x
            left_hi = i - 2
            for t in range(0, right - left_hi - 1):
                arr.mark(left_hi + 1 + t, ROLE_SORTED)
            if left_hi - lo < hi - right:
                rec(lo, left_hi)
                lo = right
            else:
                rec(right, hi)
                hi = left_hi

    rec(0, n - 1)


# ==========================================================================
# 080 ~ 084  工程实现变体
# ==========================================================================
@register_algo(
    algo_id="080_quicksort_iterative_stack",
    name_zh="快速排序（显式栈非递归）",
    name_en="Iterative Quick Sort (Explicit Stack)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="把待处理区间压进显式栈，彻底消除递归调用；栈中始终只保留 O(log N) 个"
         "区间（总是先压长区间、后处理短区间）。",
)
def quicksort_iterative_stack(arr):
    n = arr.n
    if n < 2:
        return
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                break
            arr.mark(lo, ROLE_BOUNDARY)
            arr.mark(hi, ROLE_BOUNDARY)
            _pivot_to_hi(arr, lo, hi, _pick_median3)
            p = _lomuto(arr, lo, hi)
            arr.mark(p, ROLE_SORTED)
            # 长区间压栈，短区间继续内层循环
            if p - lo > hi - p:
                if lo < p - 1:
                    stack.append((lo, p - 1))
                lo = p + 1
            else:
                if p + 1 < hi:
                    stack.append((p + 1, hi))
                hi = p - 1
        arr.clear_marks()
    arr.clear_marks()


@register_algo(
    algo_id="081_quicksort_stable_aux",
    name_zh="快速排序（外部辅助空间稳定版）",
    name_en="Stable Quick Sort (Auxiliary Buffer)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="分区时把元素按原相对顺序分别写进辅助数组的左半与右半，再整体拷回，"
         "得到稳定的 O(N log N) 排序；代价是需要 O(N) 额外空间。",
)
def quicksort_stable_aux(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo < CUTOFF:
            insertion_sort_range(arr, lo, hi - 1)
            return
        pivot = arr.peek(lo)
        arr.mark(lo, ROLE_PIVOT)
        cnt_small = 0
        for t in range(lo + 1, hi):
            if arr.cmp_val(t, pivot):
                cnt_small += 1
        pl = lo
        ph = lo + cnt_small + 1
        arr.aux_set(lo + cnt_small, pivot)
        for t in range(lo + 1, hi):
            v = arr.get(t)
            if arr.cmp_val(t, pivot):
                arr.aux_set(pl, v)
                pl += 1
            else:
                arr.aux_set(ph, v)
                ph += 1
        for t in range(lo, hi):
            arr.set(t, arr.aux_peek(t))
        mid = lo + cnt_small
        arr.mark(mid, ROLE_SORTED)
        rec(lo, mid)
        rec(mid + 1, hi)

    rec(0, n)


@register_algo(
    algo_id="082_quicksort_stable_inplace",
    name_zh="快速排序（原地旋转稳定版）",
    name_en="In-Place Stable Quick Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(log n)", stable=True,
    desc="不用辅助数组的稳定分区：以区间末元素为基准，遇到更小的元素就用区间翻转"
         "把它旋转到已处理前缀末尾——O(1) 额外空间换来更高常数。",
)
def quicksort_stable_inplace(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            pivot = arr.peek(hi)
            arr.mark(hi, ROLE_PIVOT)
            pos = lo
            for t in range(lo, hi):
                if arr.cmp_val(t, pivot):
                    k = t
                    while k > pos:
                        arr.swap(k - 1, k)
                        k -= 1
                    pos += 1
            # 把基准旋转到 pos
            k = hi
            while k > pos:
                arr.swap(k - 1, k)
                k -= 1
            arr.mark(pos, ROLE_SORTED)
            if pos - lo < hi - pos:
                rec(lo, pos - 1)
                lo = pos + 1
            else:
                rec(pos + 1, hi)
                hi = pos - 1

    rec(0, n - 1)


@register_algo(
    algo_id="083_block_quicksort",
    name_zh="块缓冲无分支快排（BlockQuicksort）",
    name_en="BlockQuicksort (Branchless Buffer)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="先把待交换的偏移量攒进两个定长小缓冲，缓冲装满再批量执行 SWAP，"
         "把难以预测的分支换成可预测的批处理——可视化上呈规律跳跃脉冲。",
)
def block_quicksort(arr):
    n = arr.n
    if n < 2:
        return
    B = 8

    def rec(lo, hi):
        while lo < hi:
            if hi - lo < CUTOFF:
                insertion_sort_range(arr, lo, hi)
                return
            _pivot_to_hi(arr, lo, hi, _pick_median3)
            pivot = arr.peek(hi)
            small = []
            big = []
            t = lo
            while t < hi:                       # 分块扫描，攒够一块就先记下来
                end = min(t + B, hi)
                for k in range(t, end):
                    if arr.cmp_val(k, pivot):
                        small.append(k)
                    else:
                        big.append(k)
                t = end
            p = lo + len(small)
            misplaced_big = [x for x in big if x < p]
            misplaced_small = [x for x in small if x >= p]
            for u in range(0, len(misplaced_big), B):
                batch = list(zip(misplaced_big[u:u + B], misplaced_small[u:u + B]))
                for a, b in batch:
                    arr.swap(a, b)
            arr.swap(p, hi)
            arr.mark(p, ROLE_SORTED)
            if p - lo < hi - p:
                rec(lo, p - 1)
                lo = p + 1
            else:
                rec(p + 1, hi)
                hi = p - 1

    rec(0, n - 1)


@register_algo(
    algo_id="084_proportion_split_quicksort",
    name_zh="比例分割快速排序",
    name_en="Proportion Split Quick Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(log n)", stable=False,
    desc="先抽 16 个均匀分布的样本并对样本做插入排序，再按固定分位数比例"
         "（本实现取样本中位数）锁定基准——用统计手段把基准钉在分布中部。",
)
def proportion_split_quicksort(arr):
    n = arr.n
    if n < 2:
        return
    S = 16

    def picker(arr, lo, hi):
        if hi - lo + 1 <= S:
            return hi
        idx = [lo + (hi - lo) * k // (S - 1) for k in range(S)]
        for a in range(1, S):
            b = a
            while b > 0 and arr.gt(idx[b - 1], idx[b]):
                arr.swap(idx[b - 1], idx[b])
                b -= 1
        return idx[S // 2]

    _qsort_with_partition(arr, 0, n - 1, picker, _lomuto)
