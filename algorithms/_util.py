# -*- coding: utf-8 -*-
"""算法库内部共享工具（不对外暴露算法，仅供各 cat*.py 复用）。

包含：
* 序列区间插入排序 / 二分查找插入点
* d 叉堆下沉 / 上浮与通用 d 叉堆排序（三叉、四叉、八叉堆复用）
* 莱昂纳多数（Leonardo Numbers）与"森林堆"通用引擎
  —— 平滑排序 Smoothsort / 白杨堆 Poplar Sort / 三叉平滑堆变体共用
* 最小-最大堆（Min-Max Heap）的下沉与上浮原语
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

__all__ = [
    "LP", "leonardo", "poplar_size", "insertion_sort_range", "binary_insert_pos",
    "sift_down", "sift_up", "heap_sort_dary", "sift_down_range", "k_way_merge",
    "ForestSpec", "forest_sort",
    "make_leonardo_spec", "make_poplar_spec", "make_ternary_forest_spec",
    "mm_sift_down", "mm_sift_up", "mm_fix", "mm_build", "MAIN", "AUX",
    # ---- 希尔步长序列 ----
    "shell_sort_gaps", "shell_sort_range", "gaps_shell", "gaps_frank_lazarus",
    "gaps_hibbard",
    "gaps_papernov", "gaps_pratt", "gaps_knuth", "gaps_sedgewick82",
    "gaps_incerpi_sedgewick", "gaps_sedgewick86", "gaps_gonnet",
    "gaps_tokuda", "gaps_ciura",
    # ---- 归并 / 旋转原语 ----
    "lower_bound", "upper_bound", "rotate_blocks", "inplace_merge_shift",
    "sym_merge", "rotate_merge", "weave_merge",
    "merge_main_to_aux", "merge_aux_runs_to_main", "merge_aux_two_runs",
    "aux_insertion_sort", "aux_merge_sort",
    "copy_aux_to_main", "copy_main_to_aux",
]

# --------------------------------------------------------------------------
# 数列
# --------------------------------------------------------------------------
#: 莱昂纳多数 L(0)=1, L(1)=1, L(k)=L(k-1)+L(k-2)+1
LP: List[int] = [1, 1]
while len(LP) < 48:
    LP.append(LP[-1] + LP[-2] + 1)


def leonardo(k: int) -> int:
    """阶为 k 的莱昂纳多堆元素个数。"""
    return LP[k] if 0 <= k < len(LP) else 0


#: 完美二叉树（白杨堆）大小：2^k - 1
def poplar_size(k: int) -> int:
    return (1 << k) - 1


# --------------------------------------------------------------------------
# 区间插入排序 / 二分插入
# --------------------------------------------------------------------------
def insertion_sort_range(va, lo: int, hi: int, gap: int = 1) -> None:
    """对 ``[lo, hi]`` 内以 ``gap`` 为步长的子序列做插入排序。"""
    for i in range(lo + gap, hi + 1, gap):
        j = i
        while j - gap >= lo and va.gt(j - gap, j):
            va.swap(j - gap, j)
            j -= gap


def binary_insert_pos(va, lo: int, hi: int, val: int) -> int:
    """在已排序区间 ``[lo, hi)`` 中二分查找 ``val`` 的插入位置。"""
    while lo < hi:
        mid = (lo + hi) >> 1
        if va.cmp_val(mid, val):
            lo = mid + 1
        else:
            hi = mid
    return lo


# --------------------------------------------------------------------------
# d 叉堆
# --------------------------------------------------------------------------
def sift_down(va, start: int, end: int, d: int = 2) -> None:
    """在 ``[start, end]`` 内对 ``start`` 位置做 d 叉堆下沉（大顶）。"""
    root = start
    while True:
        first = root * d + 1
        if first > end:
            return
        best = first
        last = first + d - 1
        if last > end:
            last = end
        c = first + 1
        while c <= last:
            if va.cmp(best, c):
                best = c
            c += 1
        if va.cmp(root, best):
            va.swap(root, best)
            root = best
        else:
            return


def sift_up(va, idx: int, d: int = 2) -> None:
    """d 叉堆上浮。"""
    while idx > 0:
        parent = (idx - 1) // d
        if va.cmp(parent, idx):
            va.swap(parent, idx)
            idx = parent
        else:
            return


def sift_down_range(va, root: int, base: int, end: int) -> None:
    """大顶堆下沉（支持任意区间）：堆占据 ``[base, end]``，``root`` 为待下沉位置。

    与 :func:`sift_down` 的区别在于堆的根不一定是下标 0——混合排序的快排兜底
    需要在子区间 ``[lo, hi]`` 上直接建堆，因此必须带 ``base`` 偏移。
    """
    while True:
        c = base + 2 * (root - base) + 1
        if c > end:
            return
        if c + 1 <= end and va.cmp(c, c + 1):
            c += 1
        if va.cmp(root, c):
            va.swap(root, c)
            root = c
        else:
            return


def k_way_merge(va, src, dst, runs, dst_off: int) -> None:
    """把 ``src`` 访问器上的若干**相邻有序段**归并为一段写入 ``dst[dst_off ...]``。

    ``src`` / ``dst`` 取 :data:`MAIN` 或 :data:`AUX`，因此同一份代码既能
    「主数组 → 辅助数组」也能「辅助数组 → 主数组」。相等元素优先取靠前的段，
    因而保持稳定。``runs`` 为 ``[(lo, hi), ...]`` 半开区间列表。
    """
    m = len(runs)
    ptr = [r[0] for r in runs]
    end = [r[1] for r in runs]
    k = dst_off
    while True:
        best = -1
        for t in range(m):
            if ptr[t] < end[t]:
                if best < 0 or src.lt(va, ptr[t], ptr[best]):
                    best = t
        if best < 0:
            return
        dst.write(va, k, src.val(va, ptr[best]))
        ptr[best] += 1
        k += 1


def heap_sort_dary(va, d: int = 2, build_with_sift_up: bool = False) -> None:
    """通用 d 叉大顶堆排序（d=2/3/4/8 ...）。"""
    n = va.n
    if n < 2:
        return
    if build_with_sift_up:
        for i in range(1, n):
            sift_up(va, i, d)
    else:
        # Floyd 自底向上建堆
        last_parent = (n - 2) // d
        for i in range(last_parent, -1, -1):
            sift_down(va, i, n - 1, d)
    for end in range(n - 1, 0, -1):
        va.swap(0, end)
        sift_down(va, 0, end - 1, d)


# --------------------------------------------------------------------------
# 森林堆通用引擎（Smoothsort / Poplar / 三叉平滑堆）
# --------------------------------------------------------------------------
class ForestSpec:
    """描述一类"森林堆"（若干棵树覆盖整个前缀）。

    * ``sizes[k]``    —— 阶为 k 的树包含的元素个数
    * ``single``      —— 追加单元素堆时应赋予的阶
    * ``merge``       —— 检查森林末尾若干棵树能否与"新元素作为根"合并，返回新阶
    * ``parts``       —— 合并需要吞掉末尾几棵树（2 或 3）
    * ``split``       —— 移除某棵树的根之后，拆成哪几棵子树
    * ``children``    —— 某棵树的根的孩子 ``[(位置, 阶), ...]``
    """

    __slots__ = ("name", "sizes", "single", "merge", "parts", "split", "children")

    def __init__(self, name, sizes, single, merge, parts, split, children):
        self.name = name
        self.sizes = sizes
        self.single = single
        self.merge = merge
        self.parts = parts
        self.split = split
        self.children = children


def _forest_sift_down(va, p: int, k: int, spec: ForestSpec) -> None:
    """把位置 p（阶 k 的树的根）沿较大孩子一路下沉。"""
    while True:
        kids = spec.children(p, k)
        if not kids:
            return
        best_pos, best_k = kids[0]
        for cp, ck in kids[1:]:
            if va.cmp(best_pos, cp):
                best_pos, best_k = cp, ck
        if va.cmp(p, best_pos):
            va.swap(p, best_pos)
            p, k = best_pos, best_k
        else:
            return


def forest_sort(va, spec: ForestSpec) -> None:
    """通用森林堆排序：自底向上建森林 + 每次取出森林根最大值放到末尾。"""
    n = va.n
    if n < 2:
        return
    sizes = spec.sizes

    # ---- 阶段一：建森林（每个新元素成为新树的根） ----
    forest: List[Tuple[int, int]] = []      # [(起始下标, 阶)]
    for i in range(n):
        orders = [o for _, o in forest]
        k = spec.merge(orders)
        if k is not None:
            parts = forest[-spec.parts:]
            forest = forest[:-spec.parts]
            forest.append((parts[0][0], k))
            _forest_sift_down(va, i, k, spec)
        else:
            forest.append((i, spec.single(orders[-1] if orders else None)))

    va.msg(f"{spec.name}：森林构建完成，共 {len(forest)} 棵有序树")

    # ---- 阶段二：反复把"森林中最大的根"换到末尾 ----
    for i in range(n - 1, 0, -1):
        best = 0
        for h in range(1, len(forest)):
            if va.cmp(_root_pos(forest[best], sizes), _root_pos(forest[h], sizes)):
                best = h
        if best != len(forest) - 1:
            va.swap(_root_pos(forest[best], sizes), i)
            _forest_sift_down(va, _root_pos(forest[best], sizes), forest[best][1], spec)
        # 末位已就位，最后一棵树失去根 → 拆分成子树（或整体消失）
        va.mark(i, "SORTED")
        start, k = forest.pop()
        if sizes[k] > 1:
            forest.extend(spec.split(start, k))


def _root_pos(heap: Tuple[int, int], sizes: Sequence[int]) -> int:
    start, k = heap
    return start + sizes[k] - 1


def make_leonardo_spec() -> ForestSpec:
    """莱昂纳多森林：阶 a 与 a-1 两棵树 + 新根 → 阶 a+1。"""
    sizes = [leonardo(k) for k in range(48)]

    def single(rightmost: Optional[int]) -> int:
        if rightmost is None:
            return 1
        return 0 if rightmost == 1 else 1

    def merge(orders: List[int]) -> Optional[int]:
        if len(orders) >= 2 and orders[-2] == orders[-1] + 1:
            return orders[-2] + 1
        return None

    def split(start: int, k: int):
        return [(start, k - 1), (start + sizes[k - 1], k - 2)]

    def children(p: int, k: int):
        if k < 2:
            return []
        return [(p - 1 - sizes[k - 2], k - 1), (p - 1, k - 2)]

    return ForestSpec("平滑排序", sizes, single, merge, 2, split, children)


def make_poplar_spec() -> ForestSpec:
    """白杨森林：阶 k 与阶 k 两棵完美二叉树 + 新根 → 阶 k+1。"""
    sizes = [poplar_size(k) for k in range(48)]

    def single(rightmost: Optional[int]) -> int:
        return 1

    def merge(orders: List[int]) -> Optional[int]:
        if len(orders) >= 2 and orders[-2] == orders[-1]:
            return orders[-1] + 1
        return None

    def split(start: int, k: int):
        # 左子树占前 2^(k-1)-1 个位置，右子树紧随其后（各阶为 k-1）
        return [(start, k - 1), (start + (1 << (k - 1)) - 1, k - 1)]

    def children(p: int, k: int):
        if k < 2:
            return []
        half = 1 << (k - 1)
        return [(p - half, k - 1), (p - 1, k - 1)]

    return ForestSpec("白杨堆排序", sizes, single, merge, 2, split, children)


def make_ternary_forest_spec() -> ForestSpec:
    """三叉平滑森林：三棵同阶树 + 新根 → 阶 k+1（大小 3·T[k]+1）。"""
    sizes = [1]
    while len(sizes) < 32:
        sizes.append(3 * sizes[-1] + 1)

    def single(rightmost: Optional[int]) -> int:
        return 0

    def merge(orders: List[int]) -> Optional[int]:
        if len(orders) >= 3 and orders[-3] == orders[-2] == orders[-1]:
            return orders[-1] + 1
        return None

    def split(start: int, k: int):
        step = sizes[k - 1]
        return [(start, k - 1), (start + step, k - 1), (start + 2 * step, k - 1)]

    def children(p: int, k: int):
        if k < 1:
            return []
        step = sizes[k - 1]
        return [(p - 1, k - 1), (p - 1 - step, k - 1), (p - 1 - 2 * step, k - 1)]

    return ForestSpec("三叉平滑堆变体", sizes, single, merge, 3, split, children)


# --------------------------------------------------------------------------
# 最小-最大堆（Min-Max Heap, Atkinson et al.）
# --------------------------------------------------------------------------
class _MainAccess:
    """主数组访问器。"""

    __slots__ = ()

    @staticmethod
    def lt(va, i, j):
        return va.cmp(i, j)

    @staticmethod
    def val(va, i):
        return va.peek(i)

    @staticmethod
    def swap(va, i, j):
        va.swap(i, j)

    @staticmethod
    def write(va, i, v):
        va.set(i, v)


class _AuxAccess:
    """辅助数组访问器（比较计入 AUX_CMP）。"""

    __slots__ = ()

    @staticmethod
    def lt(va, i, j):
        return va.aux_cmp(i, j)

    @staticmethod
    def val(va, i):
        return va.aux_peek(i)

    @staticmethod
    def swap(va, i, j):
        va.aux_swap(i, j)

    @staticmethod
    def write(va, i, v):
        va.aux_set(i, v)


MAIN = _MainAccess()
AUX = _AuxAccess()


def _mm_level(i: int) -> int:
    return (i + 1).bit_length() - 1


def _mm_is_min_level(i: int) -> bool:
    return _mm_level(i) % 2 == 0


def _mm_children(i: int, size: int) -> List[int]:
    return [c for c in (2 * i + 1, 2 * i + 2) if c < size]


def _mm_grandchildren(i: int, size: int) -> List[int]:
    out: List[int] = []
    for c in (2 * i + 1, 2 * i + 2):
        for g in (2 * c + 1, 2 * c + 2):
            if g < size:
                out.append(g)
    return out


def mm_sift_down(va, i: int, size: int, acc=MAIN) -> None:
    """最小-最大堆下沉。

    位于最小层的节点与"后代中的最小者"比较；位于最大层的节点与"后代中的最大者"
    比较；若命中孙辈则需再与父节点校验一次该层秩序。
    """
    while True:
        min_level = _mm_is_min_level(i)
        kids = _mm_children(i, size)
        grand = _mm_grandchildren(i, size)
        pool = kids + grand
        if not pool:
            return
        best = i
        for c in pool:
            if min_level:
                if acc.lt(va, c, best):      # 最小层：找后代中的最小者
                    best = c
            else:
                if acc.lt(va, best, c):      # 最大层：找后代中的最大者
                    best = c
        if best == i:
            return
        acc.swap(va, i, best)
        if best in grand:
            parent = (best - 1) >> 1
            if min_level:
                if acc.lt(va, parent, best):     # 最小层：父节点应更小
                    acc.swap(va, parent, best)
            else:
                if acc.lt(va, best, parent):     # 最大层：父节点应更大
                    acc.swap(va, parent, best)
            i = best
        else:
            return


def mm_sift_up(va, i: int, size: int, acc=MAIN) -> None:
    """最小-最大堆上浮（建堆 / 修复任意位置时使用），逐层与父、祖父校验。"""
    while i > 0:
        parent = (i - 1) >> 1
        if _mm_is_min_level(i):
            if acc.lt(va, parent, i):       # 最小层节点却大于父节点 → 上浮
                acc.swap(va, i, parent)
                i = parent
                continue
            gp = (parent - 1) >> 1
            if parent > 0 and acc.lt(va, gp, i):   # 大于最小层祖父 → 上浮
                acc.swap(va, i, gp)
                i = gp
                continue
            return
        else:
            if acc.lt(va, i, parent):       # 最大层节点却小于父节点 → 上浮
                acc.swap(va, i, parent)
                i = parent
                continue
            gp = (parent - 1) >> 1
            if parent > 0 and acc.lt(va, i, gp):   # 小于最大层祖父 → 上浮
                acc.swap(va, i, gp)
                i = gp
                continue
            return


def mm_fix(va, i: int, size: int, acc=MAIN) -> None:
    """修复位置 i 处的任意替换：先向上消除祖先违例，再向下消除后代违例。"""
    mm_sift_up(va, i, size, acc)
    mm_sift_down(va, i, size, acc)


def mm_build(va, size: int, acc=MAIN) -> None:
    """自底向上建最小-最大堆。"""
    for i in range((size - 2) // 2, -1, -1):
        mm_sift_down(va, i, size, acc)


# ==========================================================================
# 希尔排序：步长序列生成器 + 通用外壳
# ==========================================================================
def _descend(seq) -> List[int]:
    """把步长集合去重、降序排列，并保证以 1 收尾（保证最终完全有序）。"""
    out = sorted({int(h) for h in seq if h >= 1}, reverse=True)
    if not out or out[-1] != 1:
        out.append(1)
    return out


def gaps_shell(n: int) -> List[int]:
    """Shell 1959 原始序列：h_k = ⌊N / 2^k⌋。"""
    out, h = [], n >> 1
    while h >= 1:
        out.append(h)
        h >>= 1
    return _descend(out)


def gaps_frank_lazarus(n: int) -> List[int]:
    """Frank-Lazarus 1960：h_k = 2⌊N / 2^{k+1}⌋ + 1（强制奇数步长）。"""
    out, k = [], 1
    while True:
        h = 2 * (n // (1 << (k + 1))) + 1
        if h < 1:
            break
        out.append(h)
        k += 1
        if k > 64:
            break
    return _descend(out)


def gaps_hibbard(n: int) -> List[int]:
    """Hibbard 1963：h_k = 2^k - 1（1, 3, 7, 15, 31 …），最坏 O(N^{3/2})。"""
    out, k = [], 1
    while (1 << k) - 1 < n:
        out.append((1 << k) - 1)
        k += 1
    return _descend(out)


def gaps_papernov(n: int) -> List[int]:
    """Papernov-Stasevich 1965：h_k = 2^k + 1（1, 3, 5, 9, 17, 33 …）。"""
    out, k = [1], 1
    while (1 << k) + 1 < n:
        out.append((1 << k) + 1)
        k += 1
    return _descend(out)


def gaps_pratt(n: int) -> List[int]:
    """Pratt 1971：3-光滑数 2^p·3^q（理论最坏 O(N log^2 N)）。"""
    out, p = [], 1
    while p <= n:
        q = p
        while q <= n:
            out.append(q)
            q *= 3
        p *= 2
    return _descend(out)


def gaps_knuth(n: int) -> List[int]:
    """Knuth 1973：h_k = (3^k - 1) / 2（1, 4, 13, 40, 121, 364 …）。"""
    out, h = [], 1
    while h < n:
        out.append(h)
        h = 3 * h + 1
    return _descend(out)


def gaps_sedgewick82(n: int) -> List[int]:
    """Sedgewick 1982：h_k = 4^k + 3·2^{k-1} + 1（1, 8, 23, 77, 281 …）。"""
    out, k = [1], 1
    while True:
        h = 4 ** k + 3 * (2 ** (k - 1)) + 1
        if h > n:
            break
        out.append(h)
        k += 1
        if k > 40:
            break
    return _descend(out)


#: Incerpi-Sedgewick 1985 论文给出的前若干项（互质乘积构造）
_INCERPI_TABLE = (
    1, 3, 5, 9, 17, 29, 51, 91, 157, 271, 471, 815, 1413, 2449, 4245,
    7355, 12741, 22085, 38273, 66339, 114971, 199269, 345371, 598619,
    1037493, 1798557,
)


def gaps_incerpi_sedgewick(n: int) -> List[int]:
    """Incerpi-Sedgewick 1985：文献发表的互质乘积序列表（截取 ≤ N 的部分）。"""
    return _descend([h for h in _INCERPI_TABLE if h < n])


def gaps_sedgewick86(n: int) -> List[int]:
    """Sedgewick 1986 交错序列：奇偶项交替取两条公式（1, 5, 19, 41, 109 …）。"""
    out, k = [1], 1
    while k <= 30:
        if k % 2 == 0:
            h = 9 * (2 ** k - 2 ** (k // 2)) + 1
        else:
            h = 8 * (2 ** k) - 6 * (2 ** ((k + 1) // 2)) + 1
        if h > n:
            break
        out.append(h)
        k += 1
    return _descend(out)


def gaps_gonnet(n: int) -> List[int]:
    """Gonnet & Baeza-Yates 1991：h_k = max(⌊5·h_{k-1} / 11⌋, 1)。"""
    out, h = [], max(n, 1)
    while True:
        if not out or out[-1] != h:
            out.append(h)
        if h == 1:
            break
        h = max((5 * h) // 11, 1)
    return _descend(out)


def gaps_tokuda(n: int) -> List[int]:
    """Tokuda 1992：h_k = ⌈(9·(9/4)^{k-1} - 4) / 5⌉（1, 4, 9, 20, 46, 103 …，整数精确计算）。"""
    out, k = [], 1
    while k <= 40:
        num = 9 ** k - 4 ** k                 # 9·9^{k-1} - 4·4^{k-1}
        den = 5 * (4 ** (k - 1))
        h = -((-num) // den)                  # 向上取整
        if h >= n:
            break
        out.append(h)
        k += 1
    return _descend(out)


def gaps_ciura(n: int) -> List[int]:
    """Ciura 2001 经验最优序列：1, 4, 10, 23, 57, 132, 301, 701, 1750，其后按 ⌊2.25h⌋ 扩展。"""
    base = [1, 4, 10, 23, 57, 132, 301, 701, 1750]
    out = [h for h in base if h < n]
    h = 1750
    while h < n:
        h = int(h * 2.25)
        if h < n:
            out.append(h)
    return _descend(out)


def shell_sort_gaps(va, gaps: Sequence[int]) -> None:
    """按给定（降序）步长序列执行希尔排序：每个步长对 h 个交错子序列各做插入排序。"""
    n = va.n
    if n < 2:
        return
    for h in gaps:
        if h < 1 or h >= n:
            continue
        va.msg(f"步长 h={h}：对 {h} 条交错子序列分别插入排序")
        for i in range(h, n):
            j = i
            while j - h >= 0 and va.gt(j - h, j):
                va.swap(j - h, j)
                j -= h
    va.msg("步长降为 1：最后一次全序列插入排序，数组完全有序")


def shell_sort_range(va, lo: int, hi: int, gaps: Sequence[int]) -> None:
    """在闭区间 ``[lo, hi]`` 上按给定（降序）步长序列执行希尔排序。

    混合排序（如「快排 + 希尔」）需要在中等粒度子区间上收尾，因此需要区间版本。
    """
    if hi <= lo:
        return
    span = hi - lo + 1
    for h in gaps:
        if h < 1 or h >= span:
            continue
        for i in range(lo + h, hi + 1):
            j = i
            while j - h >= lo and va.gt(j - h, j):
                va.swap(j - h, j)
                j -= h


# ==========================================================================
# 归并 / 旋转原语
# ==========================================================================
def lower_bound(va, lo: int, hi: int, val: int) -> int:
    """在 ``[lo, hi)`` 内二分查找第一个 ``>= val`` 的下标（用于稳定归并的右界）。"""
    while lo < hi:
        mid = (lo + hi) >> 1
        if va.cmp_val(mid, val):
            lo = mid + 1
        else:
            hi = mid
    return lo


def upper_bound(va, lo: int, hi: int, val: int) -> int:
    """在 ``[lo, hi)`` 内二分查找第一个 ``> val`` 的下标（保证插入稳定性）。"""
    while lo < hi:
        mid = (lo + hi) >> 1
        if va.gt_val(mid, val):
            hi = mid
        else:
            lo = mid + 1
    return lo


def rotate_blocks(va, x: int, y: int, z: int) -> None:
    """交换相邻两段 ``[x, y)`` 与 ``[y, z)``：三次区间翻转（Gries-Mills 手摇算法）。"""
    if x >= y or y >= z:
        return
    va.flip(x, y - 1)
    va.flip(y, z - 1)
    va.flip(x, z - 1)


def inplace_merge_shift(va, lo: int, mid: int, hi: int) -> None:
    """平移插入原地归并：不使用辅助数组，把右段较小元素整块左移一格插入。"""
    i, j = lo, mid
    while i < mid and j < hi:
        if va.cmp(i, j):            # arr[i] <= arr[j] → i 就位
            i += 1
        else:
            k = j
            while k > i:
                va.swap(k - 1, k)
                k -= 1
            i += 1
            mid += 1
            j += 1


def _merge_by_rotation(va, lo: int, mid: int, hi: int, symmetric: bool) -> None:
    """块旋转归并（半开区间 ``[lo, mid)`` 与 ``[mid, hi)``）。

    取一段中的枢轴元素 ``x``，在另一段中二分定位它的落点，旋转对齐后
    ``x`` 本身就落在最终位置上，左右两侧退化成为两个互不相交的同型子问题。
    ``symmetric=True`` 时枢轴取整个合并区间的中点（SymMerge），
    否则取较长子段的中点（Rotate Merge）。两者均为稳定原地归并。
    """
    if lo >= mid or mid >= hi:
        return
    if not va.gt(mid - 1, mid):         # arr[mid-1] <= arr[mid] → 两段已就位
        return
    if symmetric:
        m = (lo + hi) >> 1
    elif mid - lo >= hi - mid:
        m = (lo + mid) >> 1
    else:
        m = (mid + hi) >> 1
    if m < mid:
        # 枢轴 x = arr[m] 落在左段：把 [m, mid) 与右段中 < x 的前缀交换
        n = lower_bound(va, mid, hi, va.peek(m))
        rotate_blocks(va, m, mid, n)
        new_mid = m + (n - mid)          # 此处 arr[new_mid] == x，已就位
        _merge_by_rotation(va, lo, m, new_mid, symmetric)
        _merge_by_rotation(va, new_mid + 1, n, hi, symmetric)
    else:
        # 枢轴 x = arr[m] 落在右段：把左段中 > x 的后缀与 [mid, m] 交换
        n = upper_bound(va, lo, mid, va.peek(m))
        rotate_blocks(va, n, mid, m + 1)
        new_mid = n + (m - mid)          # 此处 arr[new_mid] == x，已就位
        _merge_by_rotation(va, lo, n, new_mid, symmetric)
        _merge_by_rotation(va, new_mid + 1, m + 1, hi, symmetric)


def sym_merge(va, lo: int, mid: int, hi: int) -> None:
    """对称旋转原地稳定归并（Kim 的 SymMerge）：两次对称二分 + 块旋转递归。"""
    _merge_by_rotation(va, lo, mid, hi, symmetric=True)


def rotate_merge(va, lo: int, mid: int, hi: int) -> None:
    """块旋转归并：以较长子段中点为轴，二分定位另一段分割点后三次翻转。"""
    _merge_by_rotation(va, lo, mid, hi, symmetric=False)


def weave_merge(va, lo: int, mid: int, hi: int) -> None:
    """奇偶交织归并：把两段已排序数据像洗牌一样交替穿插，再用插入排序收尾。"""
    i, j, k = lo, mid, lo
    while i < mid and j < hi:
        va.aux_set(k, va.peek(i))
        i += 1
        k += 1
        va.aux_set(k, va.peek(j))
        j += 1
        k += 1
    while i < mid:
        va.aux_set(k, va.peek(i))
        i += 1
        k += 1
    while j < hi:
        va.aux_set(k, va.peek(j))
        j += 1
        k += 1
    for t in range(lo, hi):
        va.set(t, va.aux_peek(t))
    insertion_sort_range(va, lo, hi - 1)


def merge_main_to_aux(va, lo: int, mid: int, hi: int) -> None:
    """把主数组两段有序区间 ``[lo, mid)``、``[mid, hi)`` 归并写入 ``aux[lo, hi)``。"""
    i, j, k = lo, mid, lo
    while i < mid and j < hi:
        if va.cmp(j, i):                    # arr[j] < arr[i] → 取右段（相等取左，保持稳定）
            va.aux_set(k, va.get(j))
            j += 1
        else:
            va.aux_set(k, va.get(i))
            i += 1
        k += 1
    while i < mid:
        va.aux_set(k, va.get(i))
        i += 1
        k += 1
    while j < hi:
        va.aux_set(k, va.get(j))
        j += 1
        k += 1


def merge_aux_two_runs(va, a_lo: int, a_hi: int, b_lo: int, b_hi: int, dst: int) -> None:
    """归并 ``aux`` 中两段**不相邻**的有序区 ``[a_lo, a_hi)``、``[b_lo, b_hi)``，
    结果写入主数组 ``[dst, dst + len)``（稳定：相等时取靠前的一段）。"""
    i, j, k = a_lo, b_lo, dst
    while i < a_hi and j < b_hi:
        if va.aux_cmp(j, i):
            va.set(k, va.aux_peek(j))
            j += 1
        else:
            va.set(k, va.aux_peek(i))
            i += 1
        k += 1
    while i < a_hi:
        va.set(k, va.aux_peek(i))
        i += 1
        k += 1
    while j < b_hi:
        va.set(k, va.aux_peek(j))
        j += 1
        k += 1


def merge_aux_runs_to_main(va, lo: int, mid: int, hi: int) -> None:
    """把 ``aux`` 中两段相邻有序区间归并写回主数组 ``[lo, hi)``。"""
    merge_aux_two_runs(va, lo, mid, mid, hi, lo)


def aux_merge_sort(va, lo: int, hi: int, tmp: int) -> None:
    """在辅助数组内部做自底向上归并排序（用于丢弃区等纯 aux 缓冲）。

    ``[lo, hi)`` 为待排序区，``[tmp, tmp + (hi - lo))`` 作为乒乓暂存区，
    两者不得重叠。全部操作都以 ``aux`` 为对象，保证统计口径一致。
    """
    n = hi - lo
    if n < 2:
        return
    width = 1
    src, dst = lo, tmp
    while width < n:
        i = 0
        while i < n:
            mid = min(i + width, n)
            end = min(i + 2 * width, n)
            a, b, w = i, mid, i
            while a < mid and b < end:
                if va.aux_cmp(src + b, src + a):
                    va.aux_set(dst + w, va.aux_peek(src + b))
                    b += 1
                else:
                    va.aux_set(dst + w, va.aux_peek(src + a))
                    a += 1
                w += 1
            while a < mid:
                va.aux_set(dst + w, va.aux_peek(src + a))
                a += 1
                w += 1
            while b < end:
                va.aux_set(dst + w, va.aux_peek(src + b))
                b += 1
                w += 1
            i += 2 * width
        src, dst = dst, src
        width <<= 1
    if src != lo:
        for i in range(n):
            va.aux_set(lo + i, va.aux_peek(src + i))


def aux_insertion_sort(va, lo: int, hi: int) -> None:
    """辅助数组上的插入排序（半开区间 ``[lo, hi)``），仅适合很短的缓冲。"""
    for i in range(lo + 1, hi):
        j = i
        while j > lo and va.aux_cmp(j, j - 1):
            va.aux_swap(j, j - 1)
            j -= 1


def copy_aux_to_main(va, lo: int, hi: int) -> None:
    """把 ``aux[lo, hi)`` 拷回主数组同位置。"""
    for i in range(lo, hi):
        va.set(i, va.aux_peek(i))


def copy_main_to_aux(va, lo: int, hi: int) -> None:
    """把主数组 ``[lo, hi)`` 拷入 ``aux`` 同位置。"""
    for i in range(lo, hi):
        va.aux_set(i, va.get(i))
