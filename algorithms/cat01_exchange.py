# -*- coding: utf-8 -*-
"""类别 01 —— 交换类排序（#001 ~ #018，共 18 种）。

冒泡谱系、鸡尾酒谱系、地精谱系、梳排序全收缩因子谱系、圆圈排序，
以及比例扩展 / 推挤 / 推入 / 房间 / 斜率等交换类变体。
"""

from __future__ import annotations

from core.protocol import ROLE_CURSOR, ROLE_MAX, ROLE_PIVOT, ROLE_SORTED
from core.registry import register_algo

from ._util import insertion_sort_range

CATEGORY = "01. 交换类排序 (Exchange Sorts)"


# ==========================================================================
# 1 ~ 2  冒泡谱系
# ==========================================================================
@register_algo(
    algo_id="001_bubble_sort",
    name_zh="标准冒泡排序",
    name_en="Bubble Sort (Standard)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="基础相邻比较交换：每一趟把未排序区最大值冒泡到区间末尾。",
)
def bubble_sort(arr):
    n = arr.n
    for i in range(n - 1):
        arr.msg(f"第 {i + 1} 趟冒泡：目标位置 arr[{n - 1 - i}]")
        for j in range(n - 1 - i):
            if arr.gt(j, j + 1):
                arr.swap(j, j + 1)
        arr.mark(n - 1 - i, ROLE_SORTED)


@register_algo(
    algo_id="002_optimized_bubble_sort",
    name_zh="提前终止冒泡排序",
    name_en="Optimized Bubble Sort (Early Exit)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="带 swapped 标志与最后交换边界记忆：某一趟无交换即代表整体有序，"
         "同时收缩右边界跳过已有序区。",
)
def optimized_bubble_sort(arr):
    n = arr.n
    end = n - 1
    while end > 0:
        last_swap = 0
        swapped = False
        arr.msg(f"扫描区间 [0, {end}]")
        for j in range(end):
            if arr.gt(j, j + 1):
                arr.swap(j, j + 1)
                swapped = True
                last_swap = j
        for k in range(end, n):
            arr.mark(k, ROLE_SORTED)
        if not swapped:
            arr.msg("本趟无交换 → 提前终止")
            break
        end = last_swap


# ==========================================================================
# 3 ~ 4  鸡尾酒（双向冒泡）谱系
# ==========================================================================
@register_algo(
    algo_id="003_cocktail_shaker_sort",
    name_zh="鸡尾酒排序（双向冒泡）",
    name_en="Cocktail Shaker Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="左右交替双向扫描冒泡，解决标准冒泡中「小元素在末尾」的乌龟问题。",
)
def cocktail_shaker_sort(arr):
    n = arr.n
    lo, hi = 0, n - 1
    while lo < hi:
        arr.msg(f"向右扫描：[{lo}, {hi}]")
        for j in range(lo, hi):
            if arr.gt(j, j + 1):
                arr.swap(j, j + 1)
        arr.mark(hi, ROLE_SORTED)
        hi -= 1

        arr.msg(f"向左扫描：[{lo}, {hi}]")
        for j in range(hi, lo, -1):
            if arr.gt(j - 1, j):
                arr.swap(j - 1, j)
        arr.mark(lo, ROLE_SORTED)
        lo += 1


@register_algo(
    algo_id="004_optimized_cocktail_shaker_sort",
    name_zh="自适应边界鸡尾酒排序",
    name_en="Optimized Cocktail Shaker Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="记录左右两端最后一次交换的位置作为新边界，大幅跳过已经有序的区域。",
)
def optimized_cocktail_shaker_sort(arr):
    n = arr.n
    lo, hi = 0, n - 1
    while lo < hi:
        new_lo, new_hi = hi, lo
        arr.msg(f"向右扫描：[{lo}, {hi}]")
        for j in range(lo, hi):
            if arr.gt(j, j + 1):
                arr.swap(j, j + 1)
                new_hi = j
        hi = new_hi
        if lo >= hi:
            break
        arr.msg(f"向左扫描：[{lo}, {hi}]")
        for j in range(hi, lo, -1):
            if arr.gt(j - 1, j):
                arr.swap(j - 1, j)
                new_lo = j
        lo = new_lo
    arr.msg("排序完成")


# ==========================================================================
# 5  奇偶砖块排序
# ==========================================================================
@register_algo(
    algo_id="005_odd_even_sort",
    name_zh="奇偶砖块排序",
    name_en="Odd-Even Sort (Brick Sort)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="奇数对与偶数对交替并行比较交换，是排序网络在串行机器上的经典映射，"
         "无交换的一整轮即代表有序。",
)
def odd_even_sort(arr):
    n = arr.n
    if n < 2:
        return
    round_no = 0
    while True:
        round_no += 1
        swapped = False
        # 奇数对 + 偶数对 各扫一遍才算完整一轮
        for start in (1, 0):
            arr.msg(f"第 {round_no} 轮：{'奇' if start else '偶'}数对扫描")
            for i in range(start, n - 1, 2):
                if arr.gt(i, i + 1):
                    arr.swap(i, i + 1)
                    swapped = True
        if not swapped:
            break


# ==========================================================================
# 6 ~ 7  地精谱系
# ==========================================================================
@register_algo(
    algo_id="006_gnome_sort",
    name_zh="标准地精排序",
    name_en="Gnome Sort (Stupid Sort)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="单个指针向前扫描，一旦发现逆序就一路交换回退到合适位置再继续前进。",
)
def gnome_sort(arr):
    n = arr.n
    i = 0
    while i < n:
        # 只要 arr[i-1] <= arr[i] 就向前走（相等时不交换，避免原地打转）
        if i == 0 or not arr.gt(i - 1, i):
            i += 1
        else:
            arr.mark(i, ROLE_CURSOR)
            arr.swap(i - 1, i)
            i -= 1
    arr.clear_marks()


@register_algo(
    algo_id="007_optimized_gnome_sort",
    name_zh="跳跃记忆地精排序",
    name_en="Optimized Gnome Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="回退交换前记录原位置，元素插好后直接跳回原处，而不必一步步重新走回来。",
)
def optimized_gnome_sort(arr):
    n = arr.n
    i = 1
    while i < n:
        if arr.cmp(i - 1, i):
            i += 1
            continue
        origin = i
        j = i
        while j > 0 and arr.gt(j - 1, j):
            arr.swap(j - 1, j)
            j -= 1
        arr.mark(origin, ROLE_CURSOR)
        i = origin + 1
    arr.clear_marks()


# ==========================================================================
# 8 ~ 11  梳排序全收缩因子谱系
# ==========================================================================
def _comb_sort_impl(arr, shrink: float, fix_gap_11: bool = False,
                    switch_to_insertion_at: int = 0) -> None:
    n = arr.n
    if n < 2:
        return
    gap = n
    swapped = True
    phase = 0
    while gap > 1 or swapped:
        gap = int(gap / shrink)
        if gap < 1:
            gap = 1
        if fix_gap_11 and gap in (9, 10):
            gap = 11
        if switch_to_insertion_at and gap <= switch_to_insertion_at:
            arr.msg(f"间距收缩至 {gap} ≤ {switch_to_insertion_at} → 切换插入排序收尾")
            insertion_sort_range(arr, 0, n - 1, 1)
            return
        swapped = False
        phase += 1
        arr.msg(f"第 {phase} 轮：间距 gap = {gap}")
        for i in range(n - gap):
            if arr.gt(i, i + gap):
                arr.swap(i, i + gap)
                swapped = True


@register_algo(
    algo_id="008_comb_sort_shrink13",
    name_zh="标准梳排序（收缩因子 1.3）",
    name_en="Comb Sort (Shrink 1.3)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2/2^p)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="以 1.3 收缩间距，用大跨度比较消除冒泡排序尾部「乌龟（小元素在末尾）」问题。",
)
def comb_sort(arr):
    _comb_sort_impl(arr, 1.3)


@register_algo(
    algo_id="009_comb_sort_golden",
    name_zh="黄金经验因子梳排序",
    name_en="Comb Sort (Shrink 1.2473)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2/2^p)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="采用 1/(1-e^{-φ}) ≈ 1.24733 的黄金收缩因子，经验上收敛轮数最少。",
)
def comb_sort_golden(arr):
    _comb_sort_impl(arr, 1.24733)


@register_algo(
    algo_id="010_comb_sort_11",
    name_zh="梳排序 11 变体",
    name_en="Comb Sort 11",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2/2^p)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="间距序列中若出现 9 或 10 则强制修正为 11，避免最后几轮的低效间距。",
)
def comb_sort_11(arr):
    _comb_sort_impl(arr, 1.3, fix_gap_11=True)


@register_algo(
    algo_id="011_hybrid_comb_insertion_sort",
    name_zh="梳排序+插入混合排序",
    name_en="Hybrid Comb-Insertion Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2/2^p)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="先大间距梳扫打散逆序对，当间距缩小至 ≤ 8 时切换为直接插入排序收尾，"
         "兼顾远距离搬运与局部有序性。",
)
def hybrid_comb_insertion_sort(arr):
    _comb_sort_impl(arr, 1.3, switch_to_insertion_at=8)


# ==========================================================================
# 12 ~ 13  圆圈排序
# ==========================================================================
def _circle_inner(arr, lo: int, hi: int) -> bool:
    """同心圆配对比较。

    区间首尾对称位置两两配对比较交换；当区间长度为奇数时，中间那个
    "落单"元素与它的右邻居比较，让跨半区的逆序对有机会被发现。
    """
    if lo >= hi:
        return False
    l, r = lo, hi
    swapped = False
    while l < r:
        if arr.gt(l, r):
            arr.swap(l, r)
            swapped = True
        l += 1
        r -= 1
    if l == r and l + 1 <= hi and arr.gt(l, l + 1):
        arr.swap(l, l + 1)
        swapped = True
    return swapped


@register_algo(
    algo_id="012_circle_sort_recursive",
    name_zh="递归圆圈排序",
    name_en="Circle Sort (Recursive)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log^2 n)",
    space="O(log n)", stable=False,
    desc="把区间首尾对称位置配对比较交换（像画同心圆），再递归处理左右两半，"
         "反复进行直到某一轮完全没有交换。",
)
def circle_sort_recursive(arr):
    n = arr.n
    if n < 2:
        return
    rounds = 0

    def rec(lo: int, hi: int) -> bool:
        if lo >= hi:
            return False
        sw = _circle_inner(arr, lo, hi)
        mid = (hi - lo) // 2
        if mid == 0:
            return sw
        a = rec(lo, lo + mid)
        b = rec(lo + mid + 1, hi)
        return sw or a or b

    while True:
        rounds += 1
        arr.msg(f"第 {rounds} 轮同心圆扫描")
        if not rec(0, n - 1):
            break
    arr.msg("本轮无交换 → 排序完成")


@register_algo(
    algo_id="013_circle_sort_iterative",
    name_zh="非递归圆圈排序",
    name_en="Circle Sort (Iterative)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log^2 n)",
    space="O(log n)", stable=False,
    desc="用显式栈替代递归调用，循环迭代地展开同心圆比较排序，避免栈深增长。",
)
def circle_sort_iterative(arr):
    n = arr.n
    if n < 2:
        return
    rounds = 0
    while True:
        rounds += 1
        arr.msg(f"第 {rounds} 轮：显式栈展开")
        any_swap = False
        stack = [(0, n - 1)]
        while stack:
            lo, hi = stack.pop()
            if lo >= hi:
                continue
            if _circle_inner(arr, lo, hi):
                any_swap = True
            mid = (hi - lo) // 2
            if mid == 0:
                continue
            stack.append((lo + mid + 1, hi))
            stack.append((lo, lo + mid))
        if not any_swap:
            break


# ==========================================================================
# 14  比例扩展排序
# ==========================================================================
@register_algo(
    algo_id="014_proportion_extend_sort",
    name_zh="比例扩展交换排序",
    name_en="Proportion Extend Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="有序前缀按几何比例（1 → 2 → 4 → 7 …）成块扩张，每扩张一批就把新加入的"
         "元素通过相邻交换插入到已有有序前缀中，块边界逐级外推。",
)
def proportion_extend_sort(arr):
    n = arr.n
    if n < 2:
        return
    span = 1
    while span < n:
        nxt = min(n, max(span + 1, int(span * 1.5) + 1))
        arr.msg(f"有序前缀 {span} → {nxt}")
        for k in range(span, nxt):
            j = k
            while j > 0 and arr.gt(j - 1, j):
                arr.swap(j - 1, j)
                j -= 1
        for k in range(nxt):
            arr.mark(k, ROLE_SORTED)
        span = nxt


# ==========================================================================
# 15  推挤排序
# ==========================================================================
@register_algo(
    algo_id="015_shove_sort",
    name_zh="推挤排序",
    name_en="Shove Sort (Chinotto Sort)",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="每一趟先用一次线性扫描锁定未排序区的最大值，再用相邻交换把它「一路推挤」"
         "到当前未排序区的最右端，推的过程像把大石头挤到墙角。",
)
def shove_sort(arr):
    n = arr.n
    for end in range(n - 1, 0, -1):
        m = 0
        for j in range(1, end + 1):
            if arr.cmp(m, j):
                m = j
        arr.mark(m, ROLE_MAX)
        arr.msg(f"把 arr[{m}] 推挤到 arr[{end}]")
        for j in range(m, end):
            arr.swap(j, j + 1)
        arr.clear_marks()
        arr.mark(end, ROLE_SORTED)


# ==========================================================================
# 16  推入排序
# ==========================================================================
@register_algo(
    algo_id="016_push_sort",
    name_zh="推入交换排序",
    name_en="Push Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="从右向左推进：已有序的后缀逐步扩张，每个新元素沿相邻交换向后「推入」"
         "到它在有序后缀中的正确位置。",
)
def push_sort(arr):
    n = arr.n
    if n < 2:
        return
    for i in range(n - 2, -1, -1):
        arr.msg(f"把 arr[{i}] 推入已排序后缀 [{i + 1}, {n - 1}]")
        j = i
        while j + 1 < n and arr.gt(j, j + 1):
            arr.swap(j, j + 1)
            j += 1
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 17  房间排序
# ==========================================================================
@register_algo(
    algo_id="017_room_sort",
    name_zh="房间局部块交换排序",
    name_en="Room Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n sqrt n)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="把数组切分为若干「房间（Room）」块，每一轮先在房间内部做相邻比较交换，"
         "再统一处理房间之间的边界元素，直到整轮没有任何交换为止。",
)
def room_sort(arr):
    n = arr.n
    if n < 2:
        return
    w = max(2, int(n ** 0.5))
    arr.msg(f"房间宽度 w = {w}")
    rounds = 0
    while True:
        rounds += 1
        moved = False
        # 房间内部
        for r in range(0, n - 1, w):
            for j in range(r, min(r + w - 1, n - 1)):
                if arr.gt(j, j + 1):
                    arr.swap(j, j + 1)
                    moved = True
        # 房间边界
        for j in range(w - 1, n - 1, w):
            if arr.gt(j, j + 1):
                arr.swap(j, j + 1)
                moved = True
        if not moved:
            arr.msg(f"第 {rounds} 轮无交换 → 房间全部对齐")
            break


# ==========================================================================
# 18  斜率下降排序
# ==========================================================================
@register_algo(
    algo_id="018_slope_sort",
    name_zh="斜率下降交换排序",
    name_en="Slope Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.3)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="间距按陡峭的「斜率」阶梯式下滑（gap → gap - gap/3），每一级按该间距做"
         "带间隔的插入式交换，越靠近结尾斜率越平缓、交换越精细。",
)
def slope_sort(arr):
    n = arr.n
    if n < 2:
        return
    gaps = []
    g = n // 2
    while g >= 1:
        gaps.append(g)
        if g == 1:
            break
        g = max(1, g - max(1, g // 3))
    for idx, gap in enumerate(gaps):
        arr.msg(f"斜率阶梯 {idx + 1}/{len(gaps)}：gap = {gap}")
        for i in range(gap, n):
            j = i
            while j - gap >= 0 and arr.gt(j - gap, j):
                arr.swap(j - gap, j)
                j -= gap
