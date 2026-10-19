# -*- coding: utf-8 -*-
"""类别 04 —— 插入与希尔排序全家族（#049 ~ #068，共 20 种）。

前半部分是插入排序的六种工程变体（标准 / 二分 / 指数倍增 / 成对 / 针式 / 无哨兵），
中间是希尔排序从 1959 到 2001 的十二条经典步长序列（Shell、Frank-Lazarus、
Hibbard、Papernov-Stasevich、Pratt、Knuth、Sedgewick 1982、Incerpi-Sedgewick
1985、Sedgewick 1986、Gonnet-Baeza-Yates、Tokuda、Ciura），
最后是图书馆排序（带间隙的二分插入）与耐心排序（纸牌接龙 + 最小堆多路归并）。
"""

from __future__ import annotations

from core.protocol import ROLE_CURSOR, ROLE_MIN, ROLE_PIVOT, ROLE_SORTED
from core.registry import register_algo

from ._util import (
    binary_insert_pos, gaps_ciura, gaps_frank_lazarus, gaps_gonnet, gaps_hibbard,
    gaps_incerpi_sedgewick, gaps_knuth, gaps_papernov, gaps_pratt, gaps_sedgewick82,
    gaps_sedgewick86, gaps_shell, gaps_tokuda, shell_sort_gaps, upper_bound,
)

CATEGORY = "04. 插入与希尔排序 (Insertion & Shell Sorts)"


# ==========================================================================
# 049 ~ 054  插入排序工程变体
# ==========================================================================
@register_algo(
    algo_id="049_insertion_sort",
    name_zh="标准直接插入排序",
    name_en="Insertion Sort (Standard)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="从左向右逐个把元素向已排序前缀中平移插入：近乎有序时接近 O(N)，"
         "是 TimSort / 内省排序等工业级算法的收尾子程序。",
)
def insertion_sort(arr):
    n = arr.n
    for i in range(1, n):
        j = i
        arr.mark(i, ROLE_CURSOR)
        while j > 0 and arr.gt(j - 1, j):
            arr.swap(j - 1, j)
            j -= 1
    arr.clear_marks()


@register_algo(
    algo_id="050_binary_insertion_sort",
    name_zh="二分查找插入排序",
    name_en="Binary Insertion Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="用二分搜索在已排序前缀中定位插入点，把比较次数降到 O(N log N)；"
         "数据搬移次数仍为 O(N^2)，采用 upper_bound 保证相等元素相对次序不变。",
)
def binary_insertion_sort(arr):
    n = arr.n
    for i in range(1, n):
        val = arr.get(i)
        pos = upper_bound(arr, 0, i, val)
        j = i
        while j > pos:
            arr.swap(j - 1, j)
            j -= 1
    arr.msg("全部元素已通过二分定位插入完成")


@register_algo(
    algo_id="051_exponential_binary_insertion_sort",
    name_zh="指数倍增二分插入排序",
    name_en="Exponential Binary Insertion Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="先从已排序区末尾按 1、2、4、8 的倍增步长向左探测边界，锁定了很小的"
         "候选区间后再二分——近乎有序数组上探测一步即命中，达到 O(N)。",
)
def exponential_binary_insertion_sort(arr):
    n = arr.n
    for i in range(1, n):
        val = arr.get(i)
        # 指数倍增探测：从 i-1 向左按 1、2、4、8 的步长找边界，
        # 锁定 [lo, hi) 后区间内元素个数最多为上次探测跨度。
        lo, hi = 0, i
        k = 0
        while True:
            probe = i - (1 << k)
            if probe < 0:
                lo = 0
                break
            if not arr.gt_val(probe, val):     # arr[probe] <= val
                lo = probe + 1
                break
            hi = probe                          # arr[probe] > val → 收缩上界
            if probe == 0:
                lo = 0
                break
            k += 1
        while lo < hi:
            mid = (lo + hi) >> 1
            if arr.gt_val(mid, val):
                hi = mid
            else:
                lo = mid + 1
        j = i
        while j > lo:
            arr.swap(j - 1, j)
            j -= 1


@register_algo(
    algo_id="052_pair_insertion_sort",
    name_zh="成对双元素插入排序",
    name_en="Pair Insertion Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="每次同时取出相邻两个元素，先比较排好二者次序，再先后嵌入已排序区。"
         "这是 JDK DualPivotQuicksort 在小区间上使用的底层收尾技术。",
)
def pair_insertion_sort(arr):
    n = arr.n
    i = 1
    while i < n:
        if i + 1 < n:
            if arr.gt(i, i + 1):
                arr.swap(i, i + 1)
            arr.mark(i, ROLE_CURSOR)
            j = i
            while j > 0 and arr.gt(j - 1, j):
                arr.swap(j - 1, j)
                j -= 1
            arr.mark(i + 1, ROLE_CURSOR)
            j = i + 1
            while j > 0 and arr.gt(j - 1, j):
                arr.swap(j - 1, j)
                j -= 1
            i += 2
        else:
            arr.mark(i, ROLE_CURSOR)
            j = i
            while j > 0 and arr.gt(j - 1, j):
                arr.swap(j - 1, j)
                j -= 1
            i += 1
    arr.clear_marks()


@register_algo(
    algo_id="053_pin_insertion_sort",
    name_zh="针式双端插入排序",
    name_en="Pin Insertion Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="以已排序前缀的中间值为锚点：新元素比锚点小就从最左端向右扫描插入点，"
         "比锚点大就从中点向右扫描——把平均扫描距离缩短约一半。",
)
def pin_insertion_sort(arr):
    n = arr.n
    if n < 2:
        return
    for i in range(1, n):
        val = arr.peek(i)
        mid = i >> 1
        if i >= 2 and arr.cmp_val(mid, val):
            p = mid
            arr.mark(mid, ROLE_PIVOT)
            while p < i and not arr.gt_val(p, val):
                p += 1
        else:
            p = 0
            while p < i and not arr.gt_val(p, val):
                p += 1
        j = i
        while j > p:
            arr.swap(j - 1, j)
            j -= 1
    arr.clear_marks()


@register_algo(
    algo_id="054_unguarded_insertion_sort",
    name_zh="无哨兵边界插入排序",
    name_en="Unguarded Insertion Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="先把全局最小值交换到 arr[0] 充当哨兵，内层循环因此可以彻底删掉 j >= 0 "
         "的边界判断，是 Java / C++ 标准库插入排序的标准写法。",
)
def unguarded_insertion_sort(arr):
    n = arr.n
    if n < 2:
        return
    m = 0
    for i in range(1, n):
        if arr.cmp(i, m):
            m = i
    if m != 0:
        arr.swap(0, m)
    arr.mark(0, ROLE_MIN)
    arr.msg("哨兵 arr[0] 已就位，内层循环可以去掉边界判断")
    for i in range(1, n):
        j = i
        while arr.gt(j - 1, j):        # 无需 j > 0 检查：arr[0] 是全局最小值
            arr.swap(j - 1, j)
            j -= 1
    arr.clear_marks()


# ==========================================================================
# 055 ~ 066  希尔排序的十二条步长序列
# ==========================================================================
@register_algo(
    algo_id="055_shell_sort_original",
    name_zh="希尔排序（Shell 1959 原始序列）",
    name_en="Shell Sort (Original Shell 1959)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.5)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="最早的希尔排序：步长 h_k = ⌊N / 2^k⌋ 折半收缩。实现简单，"
         "但偶步长会让奇偶下标完全隔离，最坏情况下仍会退化到 O(N^2)。",
)
def shell_sort_original(arr):
    shell_sort_gaps(arr, gaps_shell(arr.n))


@register_algo(
    algo_id="056_shell_sort_frank_lazarus",
    name_zh="希尔排序（Frank & Lazarus 1960）",
    name_en="Shell Sort (Frank & Lazarus 1960)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.3)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="把原始序列强制奇化：h_k = 2⌊N / 2^{k+1}⌋ + 1，保证每一步都是奇数，"
         "打破偶下标隔离，最坏复杂度改善到 O(N^{3/2}) 量级。",
)
def shell_sort_frank_lazarus(arr):
    shell_sort_gaps(arr, gaps_frank_lazarus(arr.n))


@register_algo(
    algo_id="057_shell_sort_hibbard",
    name_zh="希尔排序（Hibbard 1963）",
    name_en="Shell Sort (Hibbard 1963)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.25)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="Hibbard 序列 h_k = 2^k - 1（1, 3, 7, 15, 31, 63 …）：相邻步长互质，"
         "给出可证明的最坏复杂度 O(N^{3/2})。",
)
def shell_sort_hibbard(arr):
    shell_sort_gaps(arr, gaps_hibbard(arr.n))


@register_algo(
    algo_id="058_shell_sort_papernov_stasevich",
    name_zh="希尔排序（Papernov & Stasevich 1965）",
    name_en="Shell Sort (Papernov & Stasevich 1965)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.25)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="Papernov-Stasevich 序列 h_k = 2^k + 1（1, 3, 5, 9, 17, 33 …）："
         "与 Hibbard 同阶，但首项补 1 后收缩更平滑，实测略快。",
)
def shell_sort_papernov_stasevich(arr):
    shell_sort_gaps(arr, gaps_papernov(arr.n))


@register_algo(
    algo_id="059_shell_sort_pratt",
    name_zh="希尔排序（Pratt 1971 3-光滑数序列）",
    name_en="Shell Sort (Pratt 1971 Smooth Numbers)",
    category=CATEGORY,
    time_best="O(n log^2 n)", time_avg="O(n log^2 n)", time_worst="O(n log^2 n)",
    space="O(1)", stable=False,
    desc="Pratt 序列取全部 2^p·3^q 型 3-光滑数，理论上达到最优最坏复杂度 "
         "O(N log^2 N)；代价是步长个数为 O(log^2 N)，一趟趟偏多。",
)
def shell_sort_pratt(arr):
    shell_sort_gaps(arr, gaps_pratt(arr.n))


@register_algo(
    algo_id="060_shell_sort_knuth",
    name_zh="希尔排序（Knuth 1973 序列）",
    name_en="Shell Sort (Knuth 1973)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.25)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="Knuth 序列 h_k = (3^k - 1) / 2（1, 4, 13, 40, 121, 364 …）："
         "以 3 为底的经典递推，工程上易于预计算，是最常用的教科书序列。",
)
def shell_sort_knuth(arr):
    shell_sort_gaps(arr, gaps_knuth(arr.n))


@register_algo(
    algo_id="061_shell_sort_sedgewick_1982",
    name_zh="希尔排序（Sedgewick 1982 序列）",
    name_en="Shell Sort (Sedgewick 1982)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.16)", time_worst="O(n^1.3333)",
    space="O(1)", stable=False,
    desc="Sedgewick 1982 序列 h_k = 4^k + 3·2^{k-1} + 1（1, 8, 23, 77, 281 …），"
         "通过混合 4^k 与 2^k 两种尺度把最坏复杂度压到 O(N^{4/3})。",
)
def shell_sort_sedgewick_1982(arr):
    shell_sort_gaps(arr, gaps_sedgewick82(arr.n))


@register_algo(
    algo_id="062_shell_sort_incerpi_sedgewick",
    name_zh="希尔排序（Incerpi & Sedgewick 1985 互质表）",
    name_en="Shell Sort (Incerpi & Sedgewick 1985)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.15)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="按论文发表的互质乘积序列表（1, 3, 5, 9, 17, 29, 51, 91, 157, 271 …）"
         "取步长：项与项互质且比值接近 2，长程移动与局部整理兼顾。",
)
def shell_sort_incerpi_sedgewick(arr):
    shell_sort_gaps(arr, gaps_incerpi_sedgewick(arr.n))


@register_algo(
    algo_id="063_shell_sort_sedgewick_1986",
    name_zh="希尔排序（Sedgewick 1986 交错序列）",
    name_en="Shell Sort (Sedgewick 1986 Interleaved)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.15)", time_worst="O(n^1.3333)",
    space="O(1)", stable=False,
    desc="奇偶项交替采用 9(2^k - 2^{k/2}) + 1 与 8·2^k - 6·2^{(k+1)/2} + 1，"
         "得到 1, 5, 19, 41, 109, 209, 505 … 交错序列。",
)
def shell_sort_sedgewick_1986(arr):
    shell_sort_gaps(arr, gaps_sedgewick86(arr.n))


@register_algo(
    algo_id="064_shell_sort_gonnet_baeza_yates",
    name_zh="希尔排序（Gonnet & Baeza-Yates 1991）",
    name_en="Shell Sort (Gonnet & Baeza-Yates 1991)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.2)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="递推序列 h_k = max(⌊5·h_{k-1} / 11⌋, 1)，相邻步长之比恒为约 2.2，"
         "无需预计算表格，随手即可生成质量稳定的收缩序列。",
)
def shell_sort_gonnet_baeza_yates(arr):
    shell_sort_gaps(arr, gaps_gonnet(arr.n))


@register_algo(
    algo_id="065_shell_sort_tokuda",
    name_zh="希尔排序（Tokuda 1992 德田序列）",
    name_en="Shell Sort (Tokuda 1992)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.15)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="德田序列 h_k = ⌈(9·(9/4)^{k-1} - 4) / 5⌉（1, 4, 9, 20, 46, 103, 233 …）："
         "与 Ciura 同阶，但可由公式精确生成，不依赖经验表格。",
)
def shell_sort_tokuda(arr):
    shell_sort_gaps(arr, gaps_tokuda(arr.n))


@register_algo(
    algo_id="066_shell_sort_ciura",
    name_zh="希尔排序（Ciura 2001 经验最优序列）",
    name_en="Shell Sort (Ciura 2001 Empirical)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^1.12)", time_worst="O(n^1.5)",
    space="O(1)", stable=False,
    desc="Ciura 通过海量实验得出的最佳序列 1, 4, 10, 23, 57, 132, 301, 701, 1750，"
         "其后按 ⌊2.25h⌋ 扩展——实测平均比较次数最少，是工业实现的首选。",
)
def shell_sort_ciura(arr):
    shell_sort_gaps(arr, gaps_ciura(arr.n))


# ==========================================================================
# 067  图书馆排序
# ==========================================================================
@register_algo(
    algo_id="067_library_sort",
    name_zh="图书馆排序（带间隙插入）",
    name_en="Library Sort (Gapped Insertion)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(n)", stable=True,
    desc="借图书馆上架之意：在辅助区里预留大量空白书格，新元素用二分查找定位后"
         "直接插进空格而不必搬动邻居；一旦某个间隙被填满，就把全部书均匀重铺一次。"
         "期望复杂度 O(N log N)。",
)
def library_sort(arr):
    n = arr.n
    if n < 2:
        return
    cap = 2 * n + 4
    arr.aux_init(cap)
    positions = []

    def respread():
        m = len(positions)
        gap = cap / (m + 1)
        newp = [int(round((j + 1) * gap)) for j in range(m)]
        for j in range(1, m):
            if newp[j] <= newp[j - 1]:
                newp[j] = newp[j - 1] + 1
        old = [arr.aux_peek(p) for p in positions]
        for p in positions:
            arr.aux_set(p, 0)
        arr.msg("书格已满 → 把所有书均匀重铺，腾出新的间隙")
        positions[:] = newp
        for j, p in enumerate(positions):
            arr.aux_set(p, old[j])

    def slot(k):
        if not positions:
            return cap // 2
        left = positions[k - 1] if k > 0 else -1
        right = positions[k] if k < len(positions) else cap
        if right - left < 2:
            return None
        return (left + right) // 2

    for i in range(n):
        v = arr.get(i)
        lo, hi = 0, len(positions)
        while lo < hi:
            mid = (lo + hi) >> 1
            if arr.aux_get(positions[mid]) < v:
                lo = mid + 1
            else:
                hi = mid
        k = lo
        p = slot(k)
        if p is None:
            respread()
            p = slot(k)
            if p is None:
                p = cap // 2
        arr.aux_set(p, v)
        positions.insert(k, p)
    arr.msg(f"全部 {n} 本书已上架，按书格顺序读回主数组")
    for j, p in enumerate(positions):
        arr.set(j, arr.aux_peek(p))


# ==========================================================================
# 068  耐心排序
# ==========================================================================
@register_algo(
    algo_id="068_patience_sort",
    name_zh="耐心排序（纸牌接龙）",
    name_en="Patience Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="模拟纸牌接龙：把每张牌放到最左侧可压住的牌堆顶上（堆顶二分查找），"
         "再用最小堆对全部牌堆顶做多路归并写回主数组。牌堆整体存于辅助区展示。",
)
def patience_sort(arr):
    n = arr.n
    if n < 2:
        return
    # 辅助区布局：每个牌堆占一格，存放它当前的堆顶（最小牌）；最后多留一格做比较暂存
    arr.aux_init(n + 1)
    scratch = n
    piles = []           # piles[k] = 第 k 个牌堆的全部牌（堆顶在末尾）

    arr.msg("阶段一：逐张发牌，放到最左侧可压住的牌堆顶上")
    for i in range(n):
        v = arr.get(i)
        arr.aux_set(scratch, v)
        lo, hi = 0, len(piles)
        while lo < hi:
            mid = (lo + hi) >> 1
            if arr.aux_cmp(mid, scratch):        # 该堆顶 < v → 往右找
                lo = mid + 1
            else:
                hi = mid
        if lo == len(piles):
            piles.append([v])
        else:
            piles[lo].append(v)
        arr.aux_set(lo, v)                       # 更新该牌堆的堆顶
        arr.mark(i, ROLE_CURSOR)
    arr.clear_marks()
    arr.msg(f"阶段一完成：共产生 {len(piles)} 个牌堆，转入最小堆多路归并")

    # ---- 阶段二：以堆顶建最小堆，反复取出全局最小值 ----
    heap = list(range(len(piles)))

    def sift_down(idx):
        m = len(heap)
        while True:
            c = 2 * idx + 1
            if c >= m:
                return
            if c + 1 < m and arr.aux_cmp(heap[c + 1], heap[c]):
                c += 1
            if arr.aux_cmp(heap[c], heap[idx]):
                heap[idx], heap[c] = heap[c], heap[idx]
                idx = c
            else:
                return

    for idx in range(len(heap) - 1, -1, -1):
        sift_down(idx)

    out = 0
    while heap:
        pi = heap[0]
        arr.set(out, arr.aux_peek(pi))
        out += 1
        piles[pi].pop()
        if piles[pi]:
            arr.aux_set(pi, piles[pi][-1])       # 露出下一张牌成为新堆顶
            sift_down(0)
        else:
            heap[0] = heap[-1]
            heap.pop()
            if heap:
                sift_down(0)
    arr.msg("多路归并完成，主数组已完全有序")
