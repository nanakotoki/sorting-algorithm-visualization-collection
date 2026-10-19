# -*- coding: utf-8 -*-
"""类别 06 —— 归并排序全家族（#085 ~ #098，共 14 种）。

标准归并谱系（自顶向下 / 自底向上 / 三路 / 四路 / 乒乓双缓冲 / 自然归并），
原地归并谱系（平移插入 / 手摇块旋转 / SymMerge 对称旋转 / Rotate Merge / 交织），
以及三种面向特殊场景的写法（抽丝排序、丢弃归并、TwinSort 成对块归并）。
"""

from __future__ import annotations

from core.protocol import ROLE_CURSOR, ROLE_SORTED
from core.registry import register_algo

from ._util import (
    aux_merge_sort, copy_aux_to_main, copy_main_to_aux, inplace_merge_shift,
    insertion_sort_range, merge_aux_runs_to_main, merge_aux_two_runs,
    merge_main_to_aux, rotate_merge, sym_merge, weave_merge,
)

CATEGORY = "06. 归并排序家族 (Merge Sorts)"


def _merge_k_to_aux(arr, bounds, w0: int) -> None:
    """k 路归并：把 ``bounds`` 中若干有序区间合并写入 ``aux``（从 ``w0`` 起）。"""
    idx = [b[0] for b in bounds]
    w = w0
    while True:
        best = -1
        for t, (_, end) in enumerate(bounds):
            if idx[t] < end:
                if best < 0 or arr.cmp(idx[t], idx[best]):
                    best = t
        if best < 0:
            return
        arr.aux_set(w, arr.peek(idx[best]))
        w += 1
        idx[best] += 1


# ==========================================================================
# 085 ~ 089  标准归并谱系
# ==========================================================================
@register_algo(
    algo_id="085_merge_sort_topdown",
    name_zh="归并排序（自顶向下递归）",
    name_en="Merge Sort (Top-Down Recursive)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="经典分治：递归对半切分到单元素，再自底向上两两归并。归并过程把结果"
         "写进辅助数组后整体回写，是理解分治与稳定性的最佳范本。",
)
def merge_sort_topdown(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if hi - lo < 2:
            return
        mid = (lo + hi) >> 1
        rec(lo, mid)
        rec(mid, hi)
        merge_main_to_aux(arr, lo, mid, hi)
        copy_aux_to_main(arr, lo, hi)

    rec(0, n)
    arr.msg("自顶向下分治归并完成")


@register_algo(
    algo_id="086_merge_sort_bottomup",
    name_zh="归并排序（自底向上迭代）",
    name_en="Merge Sort (Bottom-Up Iterative)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="按步长 1, 2, 4, 8 … 逐趟迭代归并，完全没有递归调用；"
         "趟数固定为 ⌈log2 N⌉，缓存行为比递归版更可预测。",
)
def merge_sort_bottomup(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    width = 1
    while width < n:
        arr.msg(f"步长 {width}：合并相邻的 {width} 元素块")
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                merge_main_to_aux(arr, lo, mid, hi)
                copy_aux_to_main(arr, lo, hi)
            lo += 2 * width
        width <<= 1


@register_algo(
    algo_id="087_merge_sort_three_way",
    name_zh="三路归并排序",
    name_en="3-Way Merge Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="每次把区间平分成三段递归，再用三个指针同时比较取最小者归并——"
         "递归树高度降为 log3 N，每层需要 2 次比较定位最小段。",
)
def merge_sort_three_way(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo < 8:
            insertion_sort_range(arr, lo, hi - 1)
            return
        third = (hi - lo) // 3
        m1 = lo + third
        m2 = hi - third
        m1 = min(max(m1, lo + 1), hi - 2)
        m2 = min(max(m2, m1 + 1), hi - 1)
        rec(lo, m1)
        rec(m1, m2)
        rec(m2, hi)
        _merge_k_to_aux(arr, [(lo, m1), (m1, m2), (m2, hi)], lo)
        copy_aux_to_main(arr, lo, hi)

    rec(0, n)


@register_algo(
    algo_id="088_merge_sort_four_way",
    name_zh="四路归并排序",
    name_en="4-Way Merge Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="四分治归并：递归树高度降为 log4 N，四指针同取最小者写出；"
         "现代硬件的四路比较分支预测友好，实测常数优于二路。",
)
def merge_sort_four_way(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo < 8:
            insertion_sort_range(arr, lo, hi - 1)
            return
        q = (hi - lo) // 4
        b1 = lo + q
        b2 = lo + 2 * q
        b3 = lo + 3 * q
        b1 = min(max(b1, lo + 1), hi - 3)
        b2 = min(max(b2, b1 + 1), hi - 2)
        b3 = min(max(b3, b2 + 1), hi - 1)
        rec(lo, b1)
        rec(b1, b2)
        rec(b2, b3)
        rec(b3, hi)
        _merge_k_to_aux(arr, [(lo, b1), (b1, b2), (b2, b3), (b3, hi)], lo)
        copy_aux_to_main(arr, lo, hi)

    rec(0, n)


@register_algo(
    algo_id="089_merge_sort_pingpong",
    name_zh="乒乓双向交替归并排序",
    name_en="Ping-Pong Merge Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="奇数趟把数据从主数组归并到辅助数组，偶数趟直接从辅助数组归并回主数组，"
         "省掉传统实现里每趟 100% 的纯复制回写开销。",
)
def merge_sort_pingpong(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    width = 1
    in_aux = False
    while width < n:
        arr.msg(f"步长 {width}：{'辅助 → 主' if in_aux else '主 → 辅助'} 方向归并")
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                if in_aux:
                    merge_aux_runs_to_main(arr, lo, mid, hi)
                else:
                    merge_main_to_aux(arr, lo, mid, hi)
            elif in_aux:
                copy_aux_to_main(arr, lo, hi)
            else:
                copy_main_to_aux(arr, lo, hi)
            lo += 2 * width
        in_aux = not in_aux
        width <<= 1
    if in_aux:
        copy_aux_to_main(arr, 0, n)


# ==========================================================================
# 090  自然归并
# ==========================================================================
@register_algo(
    algo_id="090_merge_sort_natural",
    name_zh="自然归并排序",
    name_en="Natural Merge Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="先线性扫描识别数据中天然存在的递增段与递减段（递减段原地翻转成递增），"
         "再对自然有序段两两归并；近乎有序时一趟即完成，达到 O(N)。",
)
def merge_sort_natural(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    passes = 0
    while True:
        runs = []
        i = 0
        while i < n:
            j = i + 1
            if j < n and arr.gt(i, j):                 # 递减段 → 原地翻转
                while j < n and arr.gt(j - 1, j):
                    j += 1
                arr.flip(i, j - 1)
            else:
                while j < n and not arr.gt(j - 1, j):
                    j += 1
            runs.append((i, j))
            i = j
        passes += 1
        arr.msg(f"第 {passes} 趟：识别出 {len(runs)} 条自然有序段")
        if len(runs) <= 1:
            break
        for t in range(0, len(runs), 2):
            lo, mid = runs[t]
            if t + 1 < len(runs):
                merge_main_to_aux(arr, lo, mid, runs[t + 1][1])
            else:
                copy_main_to_aux(arr, lo, mid)
        copy_aux_to_main(arr, 0, n)
    arr.msg(f"自然段已全部合并，共 {passes} 趟")


# ==========================================================================
# 091 ~ 095  原地归并谱系
# ==========================================================================
@register_algo(
    algo_id="091_merge_sort_inplace_shift",
    name_zh="原地归并排序（平移插入）",
    name_en="In-Place Merge Sort (Insertion Shifting)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(log n)", stable=True,
    desc="不使用辅助数组的归并：右半区元素较小时，把左半区当前元素起的整块向右"
         "平移一格再插入——O(1) 额外空间，代价是搬移次数升到 O(N^2)。",
)
def merge_sort_inplace_shift(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo <= 16:
            insertion_sort_range(arr, lo, hi - 1)
            return
        mid = (lo + hi) >> 1
        rec(lo, mid)
        rec(mid, hi)
        inplace_merge_shift(arr, lo, mid, hi)

    rec(0, n)


@register_algo(
    algo_id="092_merge_sort_block_rotation",
    name_zh="原地归并排序（手摇块旋转）",
    name_en="In-Place Merge Sort (Block Rotation)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="自底向上迭代归并，每层归并都用二分查找定位分割点，再通过三次区间翻转"
         "（Gries-Mills 手摇算法）在 O(1) 额外空间内完成整段交换。",
)
def merge_sort_block_rotation(arr):
    n = arr.n
    if n < 2:
        return
    width = 1
    while width < n:
        arr.msg(f"步长 {width}：以块旋转方式原地归并")
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                rotate_merge(arr, lo, mid, hi)
            lo += 2 * width
        width <<= 1


@register_algo(
    algo_id="093_merge_sort_symmerge",
    name_zh="对称旋转原地稳定归并（SymMerge）",
    name_en="SymMerge (Symmetric In-Place Merge)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=True,
    desc="Kim 的 SymMerge：取两段合并区间的中点做对称二分搜索，配合块旋转把问题"
         "拆成两个互不相交的子问题递归——只做 O(N log N) 次比较、"
         "O(N log^2 N) 次移动，是原地稳定归并的最优比较次数方案。",
)
def merge_sort_symmerge(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo <= 16:
            insertion_sort_range(arr, lo, hi - 1)
            return
        mid = (lo + hi) >> 1
        rec(lo, mid)
        rec(mid, hi)
        sym_merge(arr, lo, mid, hi)

    rec(0, n)


@register_algo(
    algo_id="094_merge_sort_weave",
    name_zh="奇偶交织归并排序",
    name_en="Weave Merge Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="递归排好左右两半后，把两半像洗牌一样奇偶交错穿插（Weave）在一起，"
         "此时每个元素离它的最终位置至多一步，再跑一遍极速插入排序收尾——"
         "可视化上呈极具韵律感的交错波浪。",
)
def merge_sort_weave(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo <= 16:
            insertion_sort_range(arr, lo, hi - 1)
            return
        mid = (lo + hi) >> 1
        rec(lo, mid)
        rec(mid, hi)
        weave_merge(arr, lo, mid, hi)

    rec(0, n)


@register_algo(
    algo_id="095_merge_sort_rotate",
    name_zh="纯旋转分治归并排序",
    name_en="Rotate Merge Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(log n)", stable=True,
    desc="全程只依赖区间翻转与二分查找的稳定原地排序：总取较长子段的中点，"
         "在另一段中二分定位切分点并旋转对齐，再对两个独立子问题递归。",
)
def merge_sort_rotate(arr):
    n = arr.n
    if n < 2:
        return

    def rec(lo, hi):
        if hi - lo < 2:
            return
        if hi - lo <= 24:
            insertion_sort_range(arr, lo, hi - 1)
            return
        mid = (lo + hi) >> 1
        rec(lo, mid)
        rec(mid, hi)
        rotate_merge(arr, lo, mid, hi)

    rec(0, n)


# ==========================================================================
# 096 ~ 098  特殊场景归并
# ==========================================================================
@register_algo(
    algo_id="096_strand_sort",
    name_zh="抽丝排序",
    name_en="Strand Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(n)", stable=False,
    desc="反复从剩余乱序区线性抽出一条单调递增子序列（Strand），并把它归并进"
         "已有结果区；对随机数据退化到 O(N^2)，但设计思想与耐心排序同源。",
)
def strand_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(2 * n)
    remaining = list(arr.values())
    result = []
    arr.msg("阶段一：反复从剩余区抽出一条单调递增的丝并归并进结果区")
    while remaining:
        strand = [remaining[0]]
        rest = []
        for x in remaining[1:]:
            if x >= strand[-1]:
                strand.append(x)
            else:
                rest.append(x)
        remaining = rest
        if not result:
            result = strand
            continue
        m, s = len(result), len(strand)
        for t in range(m):
            arr.aux_set(t, result[t])
        for t in range(s):
            arr.aux_set(m + t, strand[t])
        merge_aux_runs_to_main(arr, 0, m, m + s)
        result = [arr.peek(t) for t in range(m + s)]
    arr.msg("阶段二：把抽丝归并结果写回主数组")
    for t in range(n):
        arr.set(t, result[t])


@register_algo(
    algo_id="097_drop_merge_sort",
    name_zh="丢弃归并排序",
    name_en="Drop-Merge Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="针对近乎有序数据：线性扫描保留递增主干（Main Line），把破坏单调性的"
         "少量乱序元素丢进辅助区排序后再一把归并回来——主干越长越快；"
         "丢弃区本身用辅助区内归并排序，因此即便数据完全乱序也不会退化。",
)
def drop_merge_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(2 * n)                 # 前半段放丢弃区，后半段放主干与临时区
    line = []
    dropped = []
    last = None
    for i in range(n):
        v = arr.get(i)
        if last is None or v >= last:
            line.append(v)
            last = v
        else:
            dropped.append(v)
            arr.mark(i, ROLE_CURSOR)
    d, m = len(dropped), len(line)
    arr.msg(f"主干保留 {m} 个元素，丢弃 {d} 个乱序元素进入辅助区")
    for t in range(d):
        arr.aux_set(t, dropped[t])
    if d > 1:
        aux_merge_sort(arr, 0, d, n)    # 丢弃区在辅助区内部归并排序
    for t in range(m):
        arr.aux_set(n + t, line[t])
    arr.msg("丢弃区排好序后与主干一把归并写回主数组")
    merge_aux_two_runs(arr, 0, d, n, n + m, 0)
    arr.clear_marks()


@register_algo(
    algo_id="098_twinsort",
    name_zh="成对迭代块归并排序",
    name_en="TwinSort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="先扫描把相邻两个元素排成有序对（Twins），随后从宽度 2 起步做迭代块归并，"
         "省掉了宽度 1 那一整趟比较；是缓存友好型归并的轻量改良。",
)
def twin_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    i = 0
    while i + 1 < n:
        if arr.gt(i, i + 1):
            arr.swap(i, i + 1)
        arr.mark(i, ROLE_SORTED)
        arr.mark(i + 1, ROLE_SORTED)
        i += 2
    arr.msg("阶段一完成：相邻元素已成有序对（Twins）")
    width = 2
    while width < n:
        arr.msg(f"步长 {width}：成对块迭代归并")
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                merge_main_to_aux(arr, lo, mid, hi)
                copy_aux_to_main(arr, lo, hi)
            lo += 2 * width
        width <<= 1
    arr.clear_marks()
