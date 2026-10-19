# -*- coding: utf-8 -*-
"""类别 03 —— 堆与树结构排序全家族（#031 ~ #048，共 18 种）。

大顶/小顶堆、Wegener 自底向上堆、多叉堆（三/四/八叉）、弱堆、平滑排序、
白杨堆、二项堆、斐波那契堆、配对堆、斜堆，以及 BST / AVL / Treap 树排序。
"""

from __future__ import annotations

import random

from core.protocol import ROLE_CURSOR, ROLE_HEAP_ROOT, ROLE_SORTED
from core.registry import register_algo

from ._util import (
    forest_sort,
    heap_sort_dary,
    insertion_sort_range,
    make_leonardo_spec,
    make_poplar_spec,
    make_ternary_forest_spec,
    sift_down,
    sift_up,
)

CATEGORY = "03. 堆与树结构排序 (Heaps & Tree-based Sorts)"


# ==========================================================================
# 公共小工具
# ==========================================================================
def _read_all(arr):
    """把所有元素读入「寄存器层」（此时主数组可安全被覆写）。"""
    return [arr.get(i) for i in range(arr.n)]


def _emit_sorted(arr, values, label="按序遍历写回"):
    n = len(values)
    stride = max(1, n // 12)
    for i, v in enumerate(values):
        arr.set(i, v)
        arr.mark(i, ROLE_SORTED)
        if n > 24 and i % stride == 0:
            arr.msg(f"{label}：{i + 1}/{n}")


def _sift_down_min(arr, start: int, end: int) -> None:
    """小顶堆下沉。"""
    root = start
    while True:
        c = 2 * root + 1
        if c > end:
            return
        if c + 1 <= end and arr.cmp(c + 1, c):
            c += 1
        if arr.cmp(c, root):          # 孩子比父节点更小 → 交换
            arr.swap(root, c)
            root = c
        else:
            return


# ==========================================================================
# 1 ~ 2  大顶堆（Floyd 下沉建堆 / Williams 上浮建堆）
# ==========================================================================
@register_algo(
    algo_id="031_max_heap_sort_floyd",
    name_zh="标准大顶堆排序（Floyd 建堆）",
    name_en="Max-Heap Sort (Floyd Sift-Down)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="使用 O(N) 的 Floyd 自底向上「筛选下沉」建堆，再反复把堆顶与堆尾交换后"
         "收缩堆，是教科书标准堆排序。",
)
def max_heap_sort_floyd(arr):
    arr.msg("Floyd 自底向上建堆（从最后一个非叶节点开始下沉）")
    heap_sort_dary(arr, 2)
    for i in range(arr.n):
        arr.mark(i, ROLE_SORTED)


@register_algo(
    algo_id="032_max_heap_sort_williams",
    name_zh="自顶向下建堆排序（Williams）",
    name_en="Max-Heap Sort (Williams Sift-Up)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="使用 Williams 的逐个元素「上浮插入」方式建堆（共 O(N log N) 次比较），"
         "再逐个弹出堆顶，可清晰对比两种建堆方式的比较次数差异。",
)
def max_heap_sort_williams(arr):
    arr.msg("Williams 逐个上浮插入建堆")
    heap_sort_dary(arr, 2, build_with_sift_up=True)
    for i in range(arr.n):
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 3  小顶堆排序
# ==========================================================================
@register_algo(
    algo_id="033_min_heap_sort",
    name_zh="小顶堆排序",
    name_en="Min-Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="建立小顶堆后逐个把堆顶（最小值）交换到堆尾，得到降序序列，"
         "最后用一次 FLIP 区间翻转成升序。",
)
def min_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.msg("建立小顶堆")
    for i in range((n - 2) // 2, -1, -1):
        _sift_down_min(arr, i, n - 1)
    for end in range(n - 1, 0, -1):
        arr.swap(0, end)
        _sift_down_min(arr, 0, end - 1)
        arr.mark(end, ROLE_SORTED)
    arr.msg("降序已就位 → 一次性 FLIP 翻转为升序")
    arr.flip(0, n - 1)


# ==========================================================================
# 4  Wegener 自底向上堆排序
# ==========================================================================
def _bottom_up_sift(arr, root: int, end: int) -> None:
    """Wegener 自底向上筛选。

    第一步沿「两个子节点中较大者」的路径一路直下到叶，这一段只比较子节点、
    不比较待插入值；第二步从根向下定位待插入值的落点，把路径上的值整体上移。
    这样把"边下沉边比较"的 2 次/层压缩到约 1.5 次/层。
    """
    path = [root]
    i = root
    while 2 * i + 1 <= end:
        c = 2 * i + 1
        if c + 1 <= end and arr.cmp(c, c + 1):
            c += 1
        path.append(c)
        i = c
    val = arr.peek(root)
    j = 1
    while j < len(path) and arr.gt_val(path[j], val):
        arr.set(path[j - 1], arr.peek(path[j]))
        j += 1
    arr.set(path[j - 1], val)


@register_algo(
    algo_id="034_bottom_up_heap_sort",
    name_zh="自底向上堆排序（Wegener）",
    name_en="Bottom-Up Heap Sort (Wegener)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="堆顶移走后不再逐层比较，而是先沿着「两个子节点中较大者」一路无比较地"
         "下沉到叶节点，再自下而上回溯寻找插入位置，把比较次数压到约 1.5N·log N。",
)
def bottom_up_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.msg("先常规建堆")
    for i in range((n - 2) // 2, -1, -1):
        sift_down(arr, i, n - 1, 2)
    for end in range(n - 1, 0, -1):
        arr.swap(0, end)
        _bottom_up_sift(arr, 0, end - 1)
        arr.mark(end, ROLE_SORTED)


# ==========================================================================
# 5 ~ 7  多叉堆（三叉 / 四叉 / 八叉）
# ==========================================================================
@register_algo(
    algo_id="035_ternary_heap_sort",
    name_zh="三叉堆排序（3-ary Heap）",
    name_en="Ternary Heap Sort (3-ary Heap)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="每个节点拥有 3 个子节点，树高降为 log_3 n；下沉时一次比较 3 个孩子，"
         "比较次数略增但层数更少，缓存表现更好。",
)
def ternary_heap_sort(arr):
    arr.msg("构建三叉大顶堆（扇出度 3）")
    heap_sort_dary(arr, 3)
    for i in range(arr.n):
        arr.mark(i, ROLE_SORTED)


@register_algo(
    algo_id="036_quaternary_heap_sort",
    name_zh="四叉堆排序（4-ary Heap）",
    name_en="Quaternary Heap Sort (4-ary Heap)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="扇出度为 4 的宽扁堆，树高进一步减半；每层需 3 次比较选出最大孩子，"
         "是现代缓存体系下常见的最优扇出度之一。",
)
def quaternary_heap_sort(arr):
    arr.msg("构建四叉大顶堆（扇出度 4）")
    heap_sort_dary(arr, 4)
    for i in range(arr.n):
        arr.mark(i, ROLE_SORTED)


@register_algo(
    algo_id="037_octonary_heap_sort",
    name_zh="八叉堆排序（8-ary Heap）",
    name_en="Octonary Heap Sort (8-ary Heap)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="扇出度为 8 的极扁堆结构，把一个缓存行内的全部子节点一次载入比较，"
         "用更多比较换取极少的层数遍历。",
)
def octonary_heap_sort(arr):
    arr.msg("构建八叉大顶堆（扇出度 8）")
    heap_sort_dary(arr, 8)
    for i in range(arr.n):
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 8  弱堆排序
# ==========================================================================
def _weak_child(arr, k: int, end: int, rev) -> int:
    """返回节点 k 的"受宠孩子"（两个孩子中的较大者），并把角色写入反向位数组。

    反向位 rev[k]==0 表示左孩子(2k+1)是受宠孩子，==1 表示右孩子(2k+2)。
    这正是弱堆（Weak Heap）用一位信息替代"每次重新比较两个孩子"的核心技巧。
    """
    c = 2 * k + 1
    if c + 1 <= end and arr.gt(c + 1, c):      # 右孩子更大
        rev[k] = 1
        return c + 1
    rev[k] = 0
    return c


def _weak_sift_down(arr, root: int, end: int, rev, remember: bool) -> None:
    """弱堆式单路径筛选。

    ``remember=True``（建堆阶段）时重新比较两个孩子并刷新反向位；
    ``remember=False``（提取阶段）时直接沿用已记录的反向位，只需 1 次比较/层
    把待插入值放到剪影路径上的正确位置（Wegener 自底向上回插）。
    """
    path = [root]
    k = root
    while 2 * k + 1 <= end:
        if remember:
            c = _weak_child(arr, k, end, rev)
        else:
            c = 2 * k + 1 + rev[k]
            if c > end:                      # 反向位指向的孩子已被移除 → 退回左孩子
                rev[k] = 0
                c = 2 * k + 1
        path.append(c)
        k = c
    val = arr.peek(root)
    j = 1
    while j < len(path) and arr.gt_val(path[j], val):
        arr.set(path[j - 1], arr.peek(path[j]))
        j += 1
    arr.set(path[j - 1], val)


@register_algo(
    algo_id="038_weak_heap_sort",
    name_zh="弱堆排序（Dutton）",
    name_en="Weak Heap Sort (Dutton)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="弱堆用一个「翻转位」记录每个节点的「受宠孩子」（两个孩子中的较大者），"
         "并沿受宠孩子构成的剪影路径单路径下沉；配合自底向上的回插，"
         "整个下沉过程不需要回溯整棵树，是 Dutton 设计的省比较堆结构。",
)
def weak_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    rev = [0] * n
    arr.msg("阶段一：自底向上建堆，并逐个节点确定反向位（受宠孩子）")
    for i in range((n - 2) // 2, -1, -1):
        _weak_sift_down(arr, i, n - 1, rev, remember=True)
    arr.msg("阶段二：逐个取出根（全局最大值），沿受宠孩子剪影路径回插")
    for i in range(n - 1, 0, -1):
        arr.swap(0, i)
        arr.mark(i, ROLE_SORTED)
        _weak_sift_down(arr, 0, i - 1, rev, remember=True)


# ==========================================================================
# 9 ~ 11  森林堆家族：平滑排序 / 白杨堆 / 三叉平滑堆
# ==========================================================================
@register_algo(
    algo_id="039_smoothsort",
    name_zh="平滑排序（Dijkstra）",
    name_en="Smoothsort (Dijkstra)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="基于莱昂纳多数 L(k)=L(k-1)+L(k-2)+1 构建「森林堆」的自适应堆排序："
         "数据基本有序时比较次数退化为 O(N)，是 Dijkstra 的经典之作。",
)
def smoothsort(arr):
    forest_sort(arr, make_leonardo_spec())


@register_algo(
    algo_id="040_poplar_sort",
    name_zh="白杨堆排序",
    name_en="Poplar Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="维护一片大小呈「二次幂减一」的完美二叉堆（白杨树）森林，无需莱昂纳多数"
         "查表即可原地堆化，实现上比平滑排序更简洁。",
)
def poplar_sort(arr):
    forest_sort(arr, make_poplar_spec())


@register_algo(
    algo_id="041_ternary_smoothsort_variant",
    name_zh="三叉平滑堆变体",
    name_en="Ternary Smoothsort Variant",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="把平滑堆的「两棵相邻莱昂纳多树合并」扩展为「三棵同阶子树 + 新根」的"
         "合并规则（大小递推 T(k)=3T(k-1)+1），森林树高更低、合并更粗粒度。",
)
def ternary_smoothsort_variant(arr):
    forest_sort(arr, make_ternary_forest_spec())


# ==========================================================================
# 12 ~ 15  指针式堆结构：二项堆 / 斐波那契堆 / 配对堆 / 斜堆
# ==========================================================================
class _HNode:
    """通用多路树节点（二项堆 / 斐波那契堆使用）。"""

    __slots__ = ("v", "children", "degree")

    def __init__(self, v: int) -> None:
        self.v = v
        self.children = []
        self.degree = 0


def _link_equal_degree(a: _HNode, b: _HNode) -> _HNode:
    if a.v <= b.v:
        a.children.append(b)
        a.degree += 1
        return a
    b.children.append(a)
    b.degree += 1
    return b


def _fib_consolidate(roots):
    table = {}
    for node in roots:
        x = node
        while x.degree in table:
            y = table.pop(x.degree)
            x = _link_equal_degree(x, y)
        table[x.degree] = x
    return list(table.values())


def _heap_extract_min(roots, consolidate: bool):
    mi = 0
    for i in range(1, len(roots)):
        if roots[i].v < roots[mi].v:
            mi = i
    node = roots.pop(mi)
    roots.extend(node.children)
    node.children = []
    if consolidate:
        roots = _fib_consolidate(roots)
    return node.v, roots


@register_algo(
    algo_id="042_binomial_heap_sort",
    name_zh="二项堆排序",
    name_en="Binomial Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="在辅助空间模拟二项树（度为 k 的树恰有 2^k 个节点）的合并过程："
         "同级二项树两两 Link 合并，提取最小根后再把其子树反序倒回森林。",
)
def binomial_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    roots = []
    arr.msg("阶段一：逐个插入并做同级二项树合并（Link）")
    for k, v in enumerate(values):
        node = _HNode(v)
        x = node
        while any(r.degree == x.degree for r in roots):
            same = next(r for r in roots if r.degree == x.degree)
            roots.remove(same)
            x = _link_equal_degree(x, same)
        roots.append(x)
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}，当前森林 {len(roots)} 棵树")
    arr.msg("阶段二：反复提取最小根并写回主数组")
    out = []
    while roots:
        v, roots = _heap_extract_min(roots, consolidate=False)
        roots.sort(key=lambda r: r.degree)
        out.append(v)
    _emit_sorted(arr, out, "二项堆按序写回")


@register_algo(
    algo_id="043_fibonacci_heap_sort",
    name_zh="斐波那契堆排序",
    name_en="Fibonacci Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="插入完全不整理结构（O(1) 惰性入根表），只在提取最小值时执行一次"
         "按度数归并 Consolidate，展示延迟合并这一摊销分析经典技巧。",
)
def fibonacci_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    roots = [_HNode(v) for v in values]
    arr.msg(f"惰性插入完成：根表共有 {len(roots)} 棵单节点树")
    out = []
    round_no = 0
    while roots:
        round_no += 1
        v, roots = _heap_extract_min(roots, consolidate=True)
        out.append(v)
        if round_no % max(1, n // 8) == 0:
            arr.msg(f"第 {round_no} 次 Consolidate：根表收敛为 {len(roots)} 棵")
    _emit_sorted(arr, out, "斐波那契堆按序写回")


class _PNode:
    __slots__ = ("v", "child", "sibling")

    def __init__(self, v: int) -> None:
        self.v = v
        self.child = None
        self.sibling = None


def _pair_meld(a: _PNode, b: _PNode):
    if a is None:
        return b
    if b is None:
        return a
    if a.v <= b.v:
        b.sibling = a.child
        a.child = b
        return a
    a.sibling = b.child
    b.child = a
    return b


def _pair_delete_min(root: _PNode):
    """两趟配对：兄弟两两配对合并，再从右向左归并。"""
    children = []
    c = root.child
    while c is not None:
        nxt = c.sibling
        c.sibling = None
        children.append(c)
        c = nxt
    paired = []
    i = 0
    while i + 1 < len(children):
        paired.append(_pair_meld(children[i], children[i + 1]))
        i += 2
    if i < len(children):
        paired.append(children[i])
    if not paired:
        return None
    acc = paired[-1]
    for k in range(len(paired) - 2, -1, -1):
        acc = _pair_meld(paired[k], acc)
    return acc


@register_algo(
    algo_id="044_pairing_heap_sort",
    name_zh="配对堆排序",
    name_en="Pairing Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="自调整堆结构：合并只需把较大根挂成较小根的第一个孩子；提取最小根时"
         "对子节点做「两趟配对合并」，无需记录任何平衡信息。",
)
def pairing_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    root = None
    arr.msg("阶段一：逐个插入（惰性合并）")
    for k, v in enumerate(values):
        root = _pair_meld(root, _PNode(v))
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}")
    arr.msg("阶段二：反复提取最小根，对子节点做两趟配对")
    out = []
    while root is not None:
        out.append(root.v)
        root = _pair_delete_min(root)
    _emit_sorted(arr, out, "配对堆按序写回")


class _SNode:
    __slots__ = ("v", "left", "right")

    def __init__(self, v: int) -> None:
        self.v = v
        self.left = None
        self.right = None


def _skew_merge(a: _SNode, b: _SNode):
    """迭代式斜堆合并：沿右脊下降，回溯时无条件交换左右子树。"""
    if a is None:
        return b
    if b is None:
        return a
    stack = []
    while a is not None and b is not None:
        if a.v > b.v:
            a, b = b, a
        stack.append(a)
        a, b = a.right, b
    tail = a if a is not None else b
    while stack:
        node = stack.pop()
        node.right = tail
        node.left, node.right = node.right, node.left
        tail = node
    return tail


@register_algo(
    algo_id="045_skew_heap_sort",
    name_zh="斜堆排序",
    name_en="Skew Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="每次合并都无条件交换左右子树的自调整堆，用交换代替平衡信息，"
         "结构极其简洁却能维持摊销对数复杂度。",
)
def skew_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    root = None
    arr.msg("阶段一：逐个插入（无条件交换的堆合并）")
    for k, v in enumerate(values):
        root = _skew_merge(root, _SNode(v))
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}")
    arr.msg("阶段二：反复取出根（最小值）并合并其左右子堆")
    out = []
    while root is not None:
        out.append(root.v)
        root = _skew_merge(root.left, root.right)
    _emit_sorted(arr, out, "斜堆按序写回")


# ==========================================================================
# 16 ~ 18  二叉搜索树家族：BST / AVL / Treap
# ==========================================================================
class _BstNode:
    __slots__ = ("v", "left", "right", "prio", "height")

    def __init__(self, v: int) -> None:
        self.v = v
        self.left = None
        self.right = None
        self.prio = 0
        self.height = 1


def _bst_inorder(root, out=None):
    if out is None:
        out = []
    stack = []
    cur = root
    while stack or cur is not None:
        while cur is not None:
            stack.append(cur)
            cur = cur.left
        cur = stack.pop()
        out.append(cur.v)
        cur = cur.right
    return out


def _bst_height(node) -> int:
    return node.height if node is not None else 0


def _bst_update(node) -> None:
    node.height = 1 + max(_bst_height(node.left), _bst_height(node.right))


@register_algo(
    algo_id="046_binary_search_tree_sort",
    name_zh="朴素二叉搜索树排序",
    name_en="Binary Search Tree Sort (Unbalanced)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n^2)",
    space="O(n)", stable=False,
    desc="逐个插入构建普通二叉搜索树，再通过中序遍历把有序序列写回主数组；"
         "输入已排序时会退化成链表（O(N^2)），可直观对比平衡树的差异。",
)
def binary_search_tree_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    root = None
    arr.msg("阶段一：逐个插入构建二叉搜索树（非递归插入）")
    for k, v in enumerate(values):
        node = _BstNode(v)
        if root is None:
            root = node
        else:
            cur = root
            while True:
                if v < cur.v:
                    if cur.left is None:
                        cur.left = node
                        break
                    cur = cur.left
                else:
                    if cur.right is None:
                        cur.right = node
                        break
                    cur = cur.right
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}")
    arr.msg("阶段二：中序遍历 BST 得到升序序列")
    _emit_sorted(arr, _bst_inorder(root), "BST 中序遍历写回")


def _avl_rotate_right(y):
    x = y.left
    y.left = x.right
    x.right = y
    _bst_update(y)
    _bst_update(x)
    return x


def _avl_rotate_left(x):
    y = x.right
    x.right = y.left
    y.left = x
    _bst_update(x)
    _bst_update(y)
    return y


def _avl_insert(node, v):
    if node is None:
        return _BstNode(v)
    if v < node.v:
        node.left = _avl_insert(node.left, v)
    else:
        node.right = _avl_insert(node.right, v)
    _bst_update(node)
    bf = _bst_height(node.left) - _bst_height(node.right)
    if bf > 1:
        if v < node.left.v:
            return _avl_rotate_right(node)
        node.left = _avl_rotate_left(node.left)
        return _avl_rotate_right(node)
    if bf < -1:
        if v >= node.right.v:
            return _avl_rotate_left(node)
        node.right = _avl_rotate_right(node.right)
        return _avl_rotate_left(node)
    return node


@register_algo(
    algo_id="047_avl_tree_sort",
    name_zh="AVL 平衡树排序",
    name_en="AVL Tree Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="带 LL / RR / LR / RL 四种旋转的严格平衡二叉搜索树，任何输入下树高都"
         "稳定在 1.44·log N 以内，中序遍历即得升序结果。",
)
def avl_tree_sort(arr):
    n = arr.n
    if n < 2:
        return
    values = _read_all(arr)
    root = None
    arr.msg("阶段一：逐个插入并执行 AVL 旋转再平衡")
    for k, v in enumerate(values):
        root = _avl_insert(root, v)
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}，当前树高 {_bst_height(root)}")
    arr.msg("阶段二：中序遍历写回")
    _emit_sorted(arr, _bst_inorder(root), "AVL 中序遍历写回")


def _treap_insert(node, v, prio):
    """递归插入：插入后若随机优先级小于父节点则旋转上浮。"""
    if node is None:
        nd = _BstNode(v)
        nd.prio = prio
        return nd
    if v < node.v:
        node.left = _treap_insert(node.left, v, prio)
        if node.left.prio < node.prio:
            node = _avl_rotate_right(node)
    else:
        node.right = _treap_insert(node.right, v, prio)
        if node.right.prio < node.prio:
            node = _avl_rotate_left(node)
    return node


@register_algo(
    algo_id="048_treap_sort",
    name_zh="树堆排序（随机化 BST）",
    name_en="Treap Sort (Randomized BST)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="每个节点携带一个随机优先级，插入后沿路径旋转上浮直到满足小顶堆性质，"
         "以期望 O(log N) 的树高实现随机化平衡。",
)
def treap_sort(arr):
    n = arr.n
    if n < 2:
        return
    rng = random.Random(20240921)
    values = _read_all(arr)
    root = None
    arr.msg("阶段一：插入节点并依据随机优先级旋转上浮")
    for k, v in enumerate(values):
        root = _treap_insert(root, v, rng.random())
        if k % max(1, n // 8) == 0:
            arr.msg(f"已插入 {k + 1}/{n}，当前树高 {_bst_height(root)}")
    arr.msg("阶段二：中序遍历写回")
    _emit_sorted(arr, _bst_inorder(root), "Treap 中序遍历写回")
