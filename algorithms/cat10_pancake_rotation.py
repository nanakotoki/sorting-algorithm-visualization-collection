# -*- coding: utf-8 -*-
"""类别 10：煎饼翻转与受限操作排序（#145 ~ #150，共 6 种）。

本类算法的共同特征是**操作受限**——只能使用某些特定的原子指令来完成排序：

* 前缀翻转（FLIP(0, k)）：煎饼排序家族
* 任意子区间翻转（FLIP(i, j)）：准煎饼排序
* 相邻块互换（由三次区间翻转复合而成）：相邻块互换排序
* 双栈倒腾（纯辅助栈 push/pop）：双栈模拟排序

由于操作受限，这些算法的时间复杂度普遍高于通用排序，但它们的**可视化价值**
极高：每一铲、每一次倒腾都能被清晰地画出来。
"""

from __future__ import annotations

from core.protocol import ROLE_CURSOR, ROLE_MAX, ROLE_MIN, ROLE_SORTED
from core.registry import register_algo

from ._util import rotate_blocks

CATEGORY = "10. 煎饼翻转与受限操作排序 (Pancake & Restricted-Ops Sorts)"


# ==========================================================================
# #145 Pancake Sort (Classic Max-Flip)
# ==========================================================================
@register_algo(
    algo_id="145_pancake_sort",
    name_zh="经典煎饼排序 Pancake Sort",
    name_en="Pancake Sort (Classic Max-Flip)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(1)", stable=False,
    desc="唯一允许的操作是「把最上面的 k+1 张饼整体翻个面」（前缀翻转 FLIP(0, k)）。"
         "每一轮先线性扫描找到未排序区的最大值，用一铲把它翻到最顶端，再一铲把它"
         "翻到未排序区最底端，如此往复至只剩一张。总翻转次数 ≤ 2n-3。",
)
def pancake_sort(arr):
    n = arr.n
    if n < 2:
        return
    for size in range(n, 1, -1):
        arr.clear_marks()
        arr.mark(size - 1, ROLE_CURSOR)
        mi = 0
        arr.mark(0, ROLE_MAX)
        for i in range(1, size):
            if arr.gt(i, mi):
                mi = i
                arr.clear_marks()
                arr.mark(mi, ROLE_MAX)
                arr.mark(size - 1, ROLE_CURSOR)
        if mi == size - 1:
            arr.mark(mi, ROLE_SORTED)
            arr.msg(f"未排序区最大值已在第 {size} 位，无需翻转")
            continue
        if mi != 0:
            arr.msg(f"第一铲：把最大值从位置 {mi} 翻到顶端")
            arr.flip(0, mi)
        arr.msg(f"第二铲：从顶端翻到未排序区底端（位置 {size - 1}）")
        arr.flip(0, size - 1)
        arr.mark(size - 1, ROLE_SORTED)
    arr.mark(0, ROLE_SORTED)
    arr.msg("全部就位：数组有序")


# ==========================================================================
# #146 Burnt Pancake Sort
# ==========================================================================
def _bp_flip(arr, up, k: int) -> None:
    """翻转前缀 ``[0, k]``：主数组真实翻转，朝向表同步翻转并逐张取反。"""
    arr.flip(0, k)
    i, j = 0, k
    while i < j:
        up[i], up[j] = not up[j], not up[i]
        i += 1
        j -= 1
    if i == j:
        up[i] = not up[i]
    for t in range(k + 1):
        arr.aux_set(t, 1 if up[t] else 0)


def _bp_flip_single(arr, up) -> None:
    """顶端单张翻面：只切换最上面一张饼的朝向（不改变排列顺序）。"""
    up[0] = not up[0]
    arr.aux_set(0, 1 if up[0] else 0)
    arr.msg("顶端单张翻面：仅切换焦面朝向，排列保持不变")


@register_algo(
    algo_id="146_burnt_pancake_sort",
    name_zh="烧焦煎饼排序 Burnt Pancake Sort",
    name_en="Burnt Pancake Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(n)", stable=False,
    desc="每张饼额外带一个「焦面朝上 / 朝下」的状态位，排序目标不仅是尺寸升序，"
         "还要求最终所有饼都焦面朝下。辅助缓冲用来记录每一张饼的朝向（1 表示焦面"
         "朝上），前缀翻转会同时把区间内所有饼的朝向取反。若最大值到顶后朝向不对，"
         "则先做一次「顶端单张翻面」（仅改朝向、不动顺序），再一铲送到底端。",
)
def burnt_pancake_sort(arr):
    n = arr.n
    if n < 2:
        if n == 1:
            arr.aux_init(1)
            arr.aux_set(0, arr.peek(0) & 1)
        return
    up = [bool(arr.peek(i) & 1) for i in range(n)]
    arr.aux_init(n)
    for i in range(n):
        arr.aux_set(i, 1 if up[i] else 0)
    arr.msg("初始化：按数值奇偶确定性赋予初始焦面朝向（1 = 焦面朝上）")

    for t in range(n - 1, -1, -1):
        arr.clear_marks()
        p = 0
        for i in range(1, t + 1):
            if arr.gt(i, p):
                p = i
        arr.mark(p, ROLE_MAX)
        if p != 0:
            arr.msg(f"把尺寸最大的饼从位置 {p} 翻到顶端")
            _bp_flip(arr, up, p)
        need = 1 if t >= 1 else 0
        if (1 if up[0] else 0) != need:
            _bp_flip_single(arr, up)
        if t >= 1:
            arr.msg(f"送入最终位置 {t}")
            _bp_flip(arr, up, t)
        arr.mark(t, ROLE_SORTED)
    arr.mark(0, ROLE_SORTED)
    bad = sum(1 for v in up if v)
    arr.msg(f"完成：尺寸升序，且焦面朝上的饼剩余 {bad} 张")


# ==========================================================================
# #147 Insertion Pancake Sort (Binary Flip)
# ==========================================================================
@register_algo(
    algo_id="147_insertion_pancake_sort",
    name_zh="二分翻转煎饼插入排序 Insertion Pancake Sort",
    name_en="Insertion Pancake Sort (Binary Flip)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(1)", stable=False,
    desc="不再寻找最大值，而是像插入排序那样逐个把新元素嵌进有序前缀：先用二分"
         "查找（真实发出 CMP_VAL 指令）在有序前缀中定位插入点 j，再借助常数次前缀"
         "翻转完成嵌入——先把前缀翻成降序、把新元素顶到最前，随后两次前缀翻转即可"
         "把它精确落到位置 j 并恢复前缀顺序。比较次数 O(n log n)，翻转次数 O(n²)。",
)
def insertion_pancake_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.mark(0, ROLE_SORTED)
    for k in range(1, n):
        x = arr.get(k)
        lo, hi = 0, k
        while lo < hi:
            mid = (lo + hi) >> 1
            if arr.gt_val(mid, x):
                hi = mid
            else:
                lo = mid + 1
        j = lo
        if j == k:
            arr.msg(f"第 {k} 个元素（值 {x}）已在正确位置，无需翻转")
            arr.mark(k, ROLE_SORTED)
            continue
        arr.msg(f"二分定位：值 {x} 应插入位置 {j}")
        arr.flip(0, k - 1)
        arr.flip(0, k)
        arr.flip(0, j)
        arr.flip(0, j - 1)
        arr.clear_marks()
        for t in range(k + 1):
            arr.mark(t, ROLE_SORTED)
    arr.msg("前缀已扩展至全长：数组有序")


# ==========================================================================
# #148 Quasi-Pancake Sort (Subarray Reversal)
# ==========================================================================
@register_algo(
    algo_id="148_quasi_pancake_sort",
    name_zh="准煎饼区间翻转排序 Quasi-Pancake Sort",
    name_en="Quasi-Pancake Sort (Subarray Reversal)",
    category=CATEGORY,
    time_best="O(n²)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(1)", stable=False,
    desc="把「只能用前缀翻转」放宽成「可用任意子区间翻转 FLIP(i, j)」。每次在未就位"
         "区找到最小值后用**两次**区间翻转实现一次「右旋一位」：先翻转 [i, p]，再"
         "翻转 [i+1, p]，等价于把 a[p] 搬到位置 i、其余元素整体右移一格，既不破坏"
         "已就位前缀，也不引入额外数据搬运。",
)
def quasi_pancake_sort(arr):
    n = arr.n
    if n < 2:
        return
    for i in range(n - 1):
        arr.clear_marks()
        arr.mark(i, ROLE_CURSOR)
        p = i
        arr.mark(p, ROLE_MIN)
        for j in range(i + 1, n):
            if arr.cmp(j, p):
                p = j
                arr.clear_marks()
                arr.mark(i, ROLE_CURSOR)
                arr.mark(p, ROLE_MIN)
        if p == i:
            arr.mark(i, ROLE_SORTED)
            arr.msg(f"位置 {i} 已是最小值，无需翻转")
            continue
        arr.msg(f"两次区间翻转实现右旋：把位置 {p} 的最小值搬到位置 {i}")
        arr.flip(i, p)
        arr.flip(i + 1, p)
        arr.clear_marks()
        arr.mark(i, ROLE_SORTED)
    arr.mark(n - 1, ROLE_SORTED)
    arr.msg("全部就位：数组有序")


# ==========================================================================
# #149 Adjacent Block Transpose Sort
# ==========================================================================
def _block_merge(arr, lo: int, mid: int, hi: int) -> None:
    """相邻块互换归并：只通过「交换相邻子块」把两段有序区并成一段。

    注意左段游标必须用**非严格**比较 ``a[i] <= a[j]`` 才前进：若写成严格小于，
    遇到相等元素时会走进 else 分支却切不出任何块（``k == j``），块长为 0 的
    「空交换」会让循环原地打转。改为非严格后，else 分支保证 ``a[i] > a[j]``，
    切块至少前进一格，同时相等元素留在右段也更符合稳定归并的语义。
    """
    i, j = lo, mid
    while i < j and j < hi:
        if not arr.gt(i, j):       # arr[i] <= arr[j] → i 就位（非严格，保证稳定）
            i += 1
        else:
            k = j
            while k < hi and arr.cmp(k, i):
                k += 1
            rotate_blocks(arr, i, j, k)    # 交换相邻块 [i, j) 与 [j, k)
            i += k - j
            j = k


@register_algo(
    algo_id="149_adjacent_block_transpose_sort",
    name_zh="相邻块互换排序 Adjacent Block Transpose Sort",
    name_en="Adjacent Block Transpose Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=True,
    desc="归并排序的受限操作版本：禁止逐元素搬运，只允许「把两个相邻子块整体互换"
         "位置」。实现上每次从右段切出一整段小于左段当前元素的连续块，用三次区间"
         "翻转（Gries-Mills 手摇算法）把这两个相邻块整体对调，然后继续推进。"
         "因为整块搬运不改变块内相对次序，所以归并是稳定的。",
)
def adjacent_block_transpose_sort(arr):
    n = arr.n
    if n < 2:
        return
    width = 1
    while width < n:
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                arr.msg(f"归并块：把相邻两段 [{lo}, {mid}) 与 [{mid}, {hi}) 整块互换归并")
                _block_merge(arr, lo, mid, hi)
            lo += 2 * width
        width <<= 1
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("自底向上归并完成：数组有序")


# ==========================================================================
# #150 Two-Stack Simulation Sort
# ==========================================================================
@register_algo(
    algo_id="150_two_stack_simulation_sort",
    name_zh="双栈模拟排序 Two-Stack Simulation Sort",
    name_en="Two-Stack Simulation Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(n)", stable=True,
    desc="用辅助缓冲模拟两个栈：左半区 [0, n) 作为「输入栈」，右半区 [n, 2n) 作为"
         "「有序栈」（栈底在 n，栈顶向高位生长）。反复从输入栈弹出一个元素，若有序"
         "栈顶比它大就把栈顶暂时倒回输入栈，直到找到插入位置；压入后把刚才倒出去的"
         "元素按原序压回。最后一个临时槽用来把待插入元素与栈顶做比较。",
)
def two_stack_simulation_sort(arr):
    n = arr.n
    if n < 2:
        return
    tmp = 2 * n
    arr.aux_init(2 * n + 1)
    arr.msg("把主数组整体压入「输入栈」（左半区）")
    for i in range(n):
        arr.aux_set(i, arr.get(i))

    sp_in = n          # 输入栈元素个数（栈顶 = sp_in - 1）
    sp_out = 0         # 有序栈元素个数（栈底 = n，栈顶 = n + sp_out - 1）
    while sp_in > 0:
        x = arr.aux_get(sp_in - 1)
        sp_in -= 1
        arr.aux_set(tmp, x)
        moved = 0
        while sp_out > 0 and arr.aux_cmp(tmp, n + sp_out - 1):
            v = arr.aux_get(n + sp_out - 1)
            sp_out -= 1
            arr.aux_set(sp_in, v)
            sp_in += 1
            moved += 1
        arr.aux_set(n + sp_out, x)
        sp_out += 1
        for _ in range(moved):
            sp_in -= 1
            v = arr.aux_get(sp_in)
            arr.aux_set(n + sp_out, v)
            sp_out += 1
        arr.msg(f"有序栈当前深度 {sp_out}")

    arr.msg("倒腾结束：把有序栈整体写回主数组")
    for i in range(n):
        arr.set(i, arr.aux_get(n + i))
    arr.aux_clear()
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("数组有序")
