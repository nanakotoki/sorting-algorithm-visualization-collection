# -*- coding: utf-8 -*-
"""类别 09：排序网络与并行映射排序（#133 ~ #144，共 12 种）。

## 排序网络与「虚拟无穷大补齐」

排序网络（Sorting Network）的迷人之处在于：**比较器序列与数据完全无关**。
它是一段写死的「电路」，把同一组比较器作用在任意输入上都能得到有序输出，
因此天然可以并行执行、可以用硬件布线实现，也是 0-1 原理（只要所有 0/1 输入
都能被排好，任意输入就能被排好）的最佳注脚。

代价是**网络长度通常是 2 的幂**：双调排序的「对折合并」、Batcher 奇偶归并的
「半步长递归」都依赖等分。规范书因此明确要求：「所有排序网络算法均需通过
越界判断或虚拟无穷大填充，完美适配任意非 2^k 数组长度，绝不在非 2 的幂次
长度下崩溃。」

本模块的解法是 :class:`_Virtual` —— **虚拟数组**：

* 取 ``N = 2^⌈log₂n⌉``，网络按逻辑长度 ``N`` 生成比较器；
* 逻辑位置 ``[0, n)`` 真实落在**主数组**上，用户看到的柱子就是它们；
* 逻辑位置 ``[n, N)`` 落在**辅助缓冲**里，值恒为 ``+∞``（取 ``max(arr) + 1``，
  严格大于任何真实元素），它们在可视化上就是右侧那排「撑破天」的虚拟柱；
* 由于 ``+∞`` 大于一切真实元素，网络跑完后逻辑数组的前 ``n`` 位恰好就是
  排好序的真实元素 —— 这是「用最大值补齐不改变前缀」的直接推论。

于是双调 / 奇偶归并 / 归并交换等经典网络可以**原封不动**地在任意长度上运行，
既不需要裁剪比较器，也不会在非 2 的幂次长度下崩溃。（唯一的例外是 #138
Bose-Nelson 网络——它本身就是为任意通道数设计的，所以直接以 ``logical=n``
运行，连辅助缓冲都不必开辟。）

## 本模块的 12 张网络

======================================  ==========================================
#133 双调排序（递归）                    方向感知的递归对折合并
#134 双调排序（迭代位掩码）               ``(i, i⊕j)`` + ``(i & k)`` 定方向
#135 Batcher 奇偶归并（递归）             奇数下标 / 偶数下标子列递归归并
#136 Batcher 奇偶归并（迭代）             位运算生成比较器序列
#137 成对比较网络（Parberry）             按奇偶配对 + 步长分离收敛
#138 Bose-Nelson 星形网络                Pstar / Pbracket 三次咬合递归（任意 n）
#139 Hibbard 位驱动网络                  ``(i & p) == r`` 位条件状态机
#140 周期平衡网络（Dowd）                 多趟对称跨步循环
#141 二维蛇形矩阵剪切排序                 行列交替 + 库缓存
#142 矩阵列排序（Leighton 8 步变体）       转置 + 列内排序多趟收敛
#143 交织比较器网络                       完美洗牌交错 + 相邻比较器
#144 菱形 / Pratt 对角波前网络            步长 1→N-1 的对角线波前
======================================  ==========================================
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from core.protocol import ROLE_BOUNDARY, ROLE_SORTED
from core.registry import register_algo

CATEGORY = "09. 排序网络与并行映射排序 (Sorting Networks)"

#: 比较器：``(i, j)`` 表示「较小者去 i、较大者去 j」；``('R', i, j)`` 表示反向。
Comparator = Tuple


# ==========================================================================
# 虚拟数组：逻辑长度 N，前 n 位在主数组，其余在辅助缓冲里充当 +∞
# ==========================================================================
def _logical_len(n: int) -> int:
    """返回不小于 n 的最小 2 的幂。"""
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


class _Virtual:
    """把「逻辑长度 N 的排序网络」映射到「物理长度 n 的主数组 + 辅助缓冲」上。"""

    __slots__ = ("va", "n", "N", "inf", "pad")

    def __init__(self, va, n: int, N: int, inf: int) -> None:
        self.va = va
        self.n = n
        self.N = N
        self.inf = inf
        self.pad = N - n
        if self.pad > 0:
            va.aux_init(self.pad)
            for k in range(self.pad):
                va.aux_set(k, inf)

    # ---- 逻辑位置比较（发出真实的比较指令，保证 HUD 统计准确）-----------
    def lt(self, x: int, y: int) -> bool:
        """逻辑比较 ``v[x] < v[y]``。"""
        va, n = self.va, self.n
        if x < n:
            if y < n:
                return va.cmp(x, y)
            return va.cmp_val(x, va.aux_peek(y - n))
        if y < n:
            return va.gt_val(y, va.aux_peek(x - n))
        return va.aux_cmp(x - n, y - n)

    def gt(self, x: int, y: int) -> bool:
        return self.lt(y, x)

    # ---- 逻辑位置交换 ----------------------------------------------------
    def swap(self, x: int, y: int) -> None:
        if x == y:
            return
        va, n = self.va, self.n
        if x < n:
            if y < n:
                va.swap(x, y)
            else:
                a, b = va.peek(x), va.aux_peek(y - n)
                va.set(x, b)
                va.aux_set(y - n, a)
        elif y < n:
            a, b = va.aux_peek(x - n), va.peek(y)
            va.set(y, a)
            va.aux_set(x - n, b)
        else:
            va.aux_swap(x - n, y - n)

    # ---- 比较器 ----------------------------------------------------------
    def cmp_ex(self, i: int, j: int, desc: bool = False) -> None:
        """比较器：``desc=False`` 升序（小者去 i），``desc=True`` 降序（大者去 i）。"""
        if i == j:
            return
        if desc:
            if self.lt(i, j):
                self.swap(i, j)
        else:
            if self.lt(j, i):
                self.swap(i, j)


def _run_network(va, n: int, comparators: Sequence[Comparator],
                 logical: int | None = None) -> None:
    """在虚拟数组上顺序驱动整个比较器序列。

    ``logical`` 指定网络所作用的**逻辑通道数**，缺省为「不小于 n 的最小 2 的幂」。
    只有 Bose-Nelson 这类对任意通道数都成立的构造才会显式传入 ``logical=n``，
    此时不需要任何 +∞ 补齐。
    """
    N = _logical_len(n) if logical is None else logical
    inf = (max(va.values()) if n else 0) + 1
    v = _Virtual(va, n, N, inf)
    if v.pad:
        va.msg(f"n={n} 非 2 的幂：用 {v.pad} 个虚拟 +∞（值 {inf}）补齐到 N={N}"
               f"，它们存放在辅助缓冲中，绝不参与最终结果")
    step = 0
    total = len(comparators)
    for c in comparators:
        if c[0] == 'R':
            v.cmp_ex(c[1], c[2], True)
        else:
            v.cmp_ex(c[0], c[1])
        step += 1
        if step % 8192 == 0:
            va.msg(f"比较器推进 {step}/{total}")
    va.msg(f"网络跑完：共 {total} 个比较器")
    va.clear_marks()
    for i in range(n):
        va.mark(i, ROLE_SORTED)


# ==========================================================================
# 比较器序列生成器（全部按逻辑长度 N 生成）
# ==========================================================================
def _bitonic_rec(N: int) -> List[Comparator]:
    """双调排序（递归）：先造先升后降的双调序列，再方向感知地对折合并。"""
    comps: List[Comparator] = []

    def bmerge(lo: int, m: int, up: bool) -> None:
        if m <= 1:
            return
        h = m >> 1
        for k in range(h):
            i, j = lo + k, lo + h + k
            comps.append((i, j) if up else ('R', i, j))
        bmerge(lo, h, up)
        bmerge(lo + h, h, up)

    def bsort(lo: int, m: int, up: bool) -> None:
        if m <= 1:
            return
        h = m >> 1
        bsort(lo, h, True)
        bsort(lo + h, h, False)
        bmerge(lo, m, up)

    bsort(0, N, True)
    return comps


def _bitonic_iter(N: int) -> List[Comparator]:
    """双调排序（迭代位掩码）：双重位循环直接驱动比较器对 ``(i, i⊕j)``。"""
    comps: List[Comparator] = []
    k = 2
    while k <= N:
        j = k >> 1
        while j >= 1:
            for i in range(N):
                l = i ^ j
                if l > i:
                    comps.append((i, l) if (i & k) == 0 else ('R', i, l))
            j >>= 1
        k <<= 1
    return comps


def _oddeven_rec(N: int) -> List[Comparator]:
    """Batcher 奇偶归并（递归）：区间步长从 1 逐级翻倍。"""
    comps: List[Comparator] = []

    def merge(lo: int, hi: int, r: int) -> None:
        step = 2 * r
        if step < hi - lo:
            merge(lo, hi, step)
            merge(lo + r, hi, step)
            for i in range(lo + r, hi - r, step):
                comps.append((i, i + r))
        else:
            comps.append((lo, lo + r))

    def msort(lo: int, hi: int) -> None:
        if hi - lo >= 1:
            mid = lo + (hi - lo) // 2
            msort(lo, mid)
            msort(mid + 1, hi)
            merge(lo, hi, 1)

    msort(0, N - 1)
    return comps


def _oddeven_iter(N: int) -> List[Comparator]:
    """Batcher 奇偶归并（迭代）：非递归位运算生成同一批比较器。"""
    comps: List[Comparator] = []
    p = 1
    while p < N:
        k = p
        while k >= 1:
            j = k % p
            while j + k < N:
                for i in range(min(k, N - j - k)):
                    if ((i + j) // (2 * p)) == ((i + j + k) // (2 * p)):
                        comps.append((i + j, i + j + k))
                j += 2 * k
            k >>= 1
        p <<= 1
    return comps


def _merge_exchange(N: int) -> List[Comparator]:
    """归并交换网络：``(i & p) == r`` 位条件驱动的「位运算状态机」。"""
    comps: List[Comparator] = []
    t = 0
    while (1 << t) < N:
        t += 1
    p = 1 << (t - 1)
    while p > 0:
        q, r, d = 1 << (t - 1), 0, p
        while True:
            i = 0
            while i + d < N:
                if (i & p) == r:
                    comps.append((i, i + d))
                i += 1
            if q == p:
                break
            d = q - p
            q >>= 1
            r = p
        p >>= 1
    return comps


def _parity_sweep(N: int, rounds: int = 3) -> List[Comparator]:
    """成对比较网络：跨度从大到小，每个跨度上先比「偶数起点对」再比「奇数起点对」。

    跨度**必须从 N-1 递减到 1**：先把相距最远的元素配成一对分离大小，
    再用越来越细的跨度把边界处残留的错位收敛干净。反过来（跨度递增）在
    n ≥ 7 时就会失败。
    """
    comps: List[Comparator] = []
    for _ in range(rounds):
        for d in range(N - 1, 0, -1):
            i = 0
            while i + d < N:
                comps.append((i, i + d))
                i += 2
            i = 1
            while i + d < N:
                comps.append((i, i + d))
                i += 2
    return comps


def _bose_nelson(n: int) -> List[Comparator]:
    """Bose-Nelson 星形网络（1962 原始构造，对**任意**通道数成立，无需补齐）。

    直接照搬 Bose & Nelson 论文的 ``Pstar`` / ``Pbracket`` 递归：

    * ``Pstar(i, m)``：把 ``[i, i+m)`` 一分为二，各自递归排好，再用 ``Pbracket`` 归并；
    * ``Pbracket(i, x, j, y)``：把已排好的 ``[i, i+x)`` 与 ``[j, j+y)`` 归并。除
      ``(1,1)``、``(1,2)``、``(2,1)`` 三个平凡基例之外，它把两段各自再对半切开，
      然后按「前×前 → 后×后 → 后×前」三次递归归并——第三次调用正是「星形」的
      来由：第 2 段的**前**半要回头再和第 1 段的**后**半咬合一次。为了让递归尽快
      落到基例，切分时刻意让一侧长度取奇、另一侧取偶。

    比较器输出序列与经典文献完全一致：n = 2…16 时依次为
    ``1, 3, 5, 9, 12, 16, 19, 27, 32, 38, 42, 50, 55, 61, 65``
    （n = 16 的 65 个比较器即公认的 Bose-Nelson 网络规模）。
    """
    comps: List[Comparator] = []

    def p(i: int, j: int) -> None:          # 1 基下标 → 内部改用 0 基
        comps.append((i - 1, j - 1))

    def pbracket(i: int, x: int, j: int, y: int) -> None:
        if x == 1 and y == 1:
            p(i, j)
        elif x == 1 and y == 2:
            p(i, j + 1)
            p(i, j)
        elif x == 2 and y == 1:
            p(i, j)
            p(i + 1, j)
        else:
            a = x >> 1
            b = (y >> 1) if (x & 1) else ((y + 1) >> 1)
            pbracket(i, a, j, b)
            pbracket(i + a, x - a, j + b, y - b)
            pbracket(i + a, x - a, j, b)

    def pstar(i: int, m: int) -> None:
        if m > 1:
            a = m >> 1
            pstar(i, a)
            pstar(i + a, m - a)
            pbracket(i, a, i + a, m - a)

    pstar(1, n)
    return comps


def _alternate_sweep(N: int, rounds: int = 2) -> List[Comparator]:
    """周期平衡网络：把「2 的幂跨度」与「其余跨度」两族交替铺开，多趟循环。"""
    pow_set = set()
    d = 1
    while d < N:
        pow_set.add(d)
        d <<= 1
    highs = sorted(pow_set)
    lows = [d for d in range(1, N) if d not in pow_set]
    order: List[int] = []
    while highs or lows:
        if highs:
            order.append(highs.pop())
        if lows:
            order.append(lows.pop())
    comps: List[Comparator] = []
    for _ in range(rounds):
        for d in order:
            for i in range(N - d):
                comps.append((i, i + d))
    return comps


def _anti_sweep(N: int, rounds: int = 2) -> List[Comparator]:
    """菱形 / Pratt 对角波前：步长从 N-1 递减到 1，波前从右上角向左下角推进。"""
    comps: List[Comparator] = []
    for _ in range(rounds):
        for d in range(N - 1, 0, -1):
            for i in range(N - d):
                comps.append((i, i + d))
    return comps


# ==========================================================================
# #133 Bitonic Sort (Recursive)
# ==========================================================================
@register_algo(
    algo_id="133_bitonic_recursive",
    name_zh="递归双调排序 Bitonic Sort (Recursive)",
    name_en="Bitonic Sort (Recursive)",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(log n)", stable=False,
    desc="把数组一分为二：前半递归排成升序、后半递归排成降序，拼起来正好是一条"
         "「先升后降」的双调序列；随后做双调合并——把序列对折，逐对比较后较小者"
         "全部落到前半、较大者落到后半，再对两半施加**同方向**的合并，如此递归到底。"
         "比较器总数恰好 n·log n·(log n + 1) / 4。n 非 2 的幂时用虚拟 +∞ 补齐。",
)
def bitonic_recursive(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _bitonic_rec(_logical_len(n)))


# ==========================================================================
# #134 Bitonic Sort (Iterative Network)
# ==========================================================================
@register_algo(
    algo_id="134_bitonic_iterative",
    name_zh="迭代位掩码双调网络 Bitonic Sort (Iterative)",
    name_en="Bitonic Sort (Iterative Network)",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="与递归版完全等价，但用双重位掩码循环直接生成比较器：外层 ``k``（块大小）"
         "从 2 翻倍到 N，内层 ``j``（半步长）从 k/2 折半到 1，每个 i 与 ``i ⊕ j`` "
         "配对，方向由 ``(i & k)`` 是否为 0 决定。结果是一幅极其工整的分形几何图案"
         "——每一层都是上一层图案的自我相似复制。",
)
def bitonic_iterative(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _bitonic_iter(_logical_len(n)))


# ==========================================================================
# #135 Batcher's Odd-Even Merge Sort (Recursive)
# ==========================================================================
@register_algo(
    algo_id="135_oddeven_merge_recursive",
    name_zh="递归奇偶归并网络 Batcher Odd-Even Merge",
    name_en="Batcher's Odd-Even Merge Sort (Recursive)",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(log n)", stable=False,
    desc="Batcher 1968 年的开山之作：归并两段有序序列时，先把「奇数下标子列」和"
         "「偶数下标子列」分别递归归并，再用一层间隔为 2r 的相邻比较器把两组结果"
         "错位缝合。递归式的妙处是每层只需调整步长 r（1, 2, 4 …），写出代码只有"
         "十来行，却造出了经典 O(n log² n) 比较深度的归并网络。",
)
def oddeven_merge_recursive(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _oddeven_rec(_logical_len(n)))


# ==========================================================================
# #136 Batcher's Odd-Even Merge Sort (Iterative)
# ==========================================================================
@register_algo(
    algo_id="136_oddeven_merge_iterative",
    name_zh="迭代奇偶归并网络 Batcher Odd-Even Merge (Iterative)",
    name_en="Batcher's Odd-Even Merge Sort (Iterative)",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="非递归版本：用一个不断翻倍的块指针 p 与不断折半的半步长 k，配合 "
         "``(i + j) // (2p)`` 的分组条件，一次性把递归版的比较器全部枚举出来。"
         "这正是 GPU 与 FPGA 上最常用的写法——没有递归、没有栈，纯位运算，"
         "每个时钟周期可以整批发射比较器。",
)
def oddeven_merge_iterative(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _oddeven_iter(_logical_len(n)))


# ==========================================================================
# #137 Pairwise Sorting Network (Parberry)
# ==========================================================================
@register_algo(
    algo_id="137_pairwise_network",
    name_zh="成对比较网络 Pairwise Network (Parberry)",
    name_en="Pairwise Sorting Network (Parberry)",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="Parberry 1992 年提出的成对网络，其骨架是「按奇偶把元素配对分离，再让"
         "间距逐层收敛」：对每一个跨度 d，先把所有偶数起点 (0, d), (2, 2+d) … 成对"
         "比较一遍，再把奇数起点 (1, 1+d), (3, 3+d) … 成对比较一遍，两族交替推进，"
         "整趟跨越所有 d 后重复若干轮。相比 Batcher 网络，它的常数更小、连线更规整，"
         "非常适合映射到线性处理器阵列。",
)
def pairwise_network(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _parity_sweep(_logical_len(n), rounds=3))


# ==========================================================================
# #138 Bose-Nelson Sorting Network
# ==========================================================================
@register_algo(
    algo_id="138_bose_nelson_network",
    name_zh="Bose-Nelson 星形网络",
    name_en="Bose-Nelson Sorting Network",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="1962 年 Bose 与 Nelson 给出的**最早一批显式排序网络**构造，也是排序网络"
         "理论的开山之作（后来才有 Batcher 的奇偶归并与双调网络）。它的递归像一颗"
         "「星」：把数组一分为二、各自排好，随后归并时把两段各再对半切开，按"
         "「前×前 → 后×后 → 后×前」三次递归咬合——第三次让右段的前半**回头**再和"
         "左段的后半比较，连线因此呈放射状，故得名「星形网络」。切分时还会刻意让"
         "一侧取奇、另一侧取偶，使递归尽快落到 1~2 元素的平凡基例。"
         "比较器规模 n = 2…16 依次为 1, 3, 5, 9, 12, 16, 19, 27, 32, 38, 42, 50, "
         "55, 61, 65（n = 16 时 65 个即公认的 Bose-Nelson 网络规模）。"
         "本网络对**任意通道数**都直接成立，因此是本模块中少数无需 +∞ 补齐的构造。",
)
def bose_nelson_network(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _bose_nelson(n), logical=n)


# ==========================================================================
# #139 Hibbard Sorting Network
# ==========================================================================
@register_algo(
    algo_id="139_hibbard_network",
    name_zh="Hibbard 位驱动网络",
    name_en="Hibbard Sorting Network",
    category=CATEGORY,
    time_best="O(n log² n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="Hibbard 1963 年的构造完全由位运算状态机驱动：外层指针 p 逐次折半，"
         "内层用距离 d = q - p 与掩码 r 递推，只有当 ``(i & p) == r`` 成立时才"
         "把 i 与 i+d 接成一对比较器。它不像双调网络那样呈现明显的分形，而是"
         "按字典序「枚举」比较器对，在并行硬件上布线极为规整。",
)
def hibbard_network(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _merge_exchange(_logical_len(n)))


# ==========================================================================
# #140 Periodic Balanced Sorting Network
# ==========================================================================
@register_algo(
    algo_id="140_periodic_balanced_network",
    name_zh="周期平衡网络 Periodic Balanced Network",
    name_en="Periodic Balanced Sorting Network",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log² n)", time_worst="O(n log² n)",
    space="O(1)", stable=False,
    desc="Dowd、Perl、Saks 与 Rudolph 1989 年提出的「平衡网络」：把比较器按"
         "「扇出是否均衡」分成两族——一族是 2 的幂次大跨度（负责把元素甩到远处），"
         "另一族是其余的小跨度（负责把局部错位修平）。两族交替铺满一整趟，"
         "再整趟循环多轮，收敛过程呈明显的周期性对称折叠。",
)
def periodic_balanced_network(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _alternate_sweep(_logical_len(n), rounds=2))


# ==========================================================================
# #141 Shear Sort (2D Snake Matrix)
# ==========================================================================
def _mat_dims(n: int) -> Tuple[int, int]:
    """挑选行数 p（2 的幂）× 列数 q，使 p·q ≥ n 且尽量接近 n。"""
    if n < 1:
        return 1, 1
    p = 1
    while p * p <= n:
        p <<= 1
    p >>= 1
    p = max(p, 1)
    q = -(-n // p)
    return p, q


def _net_range(v: _Virtual, idx: Sequence[int]) -> None:
    """用奇偶换位网络（固定比较器）把一个位置序列排成升序。"""
    m = len(idx)
    for _ in range(m):
        for a in range(0, m - 1, 2):
            v.cmp_ex(idx[a], idx[a + 1])
        for a in range(1, m - 1, 2):
            v.cmp_ex(idx[a], idx[a + 1])


def _net_range_desc(v: _Virtual, idx: Sequence[int]) -> None:
    """降序版本。"""
    m = len(idx)
    for _ in range(m):
        for a in range(0, m - 1, 2):
            v.cmp_ex(idx[a], idx[a + 1], True)
        for a in range(1, m - 1, 2):
            v.cmp_ex(idx[a], idx[a + 1], True)


def _matrix_sort(va, n: int, snake_rows: bool, col_first: bool, rounds: int) -> None:
    """二维矩阵行列交替排序（p 行为 2 的幂，尾部虚拟 +∞ 补齐）。"""
    p, q = _mat_dims(n)
    N = p * q
    inf = (max(va.values()) if n else 0) + 1
    v = _Virtual(va, n, N, inf)
    if v.pad:
        va.msg(f"映射为 {p}×{q} 矩阵（共 {N} 格），尾部 {v.pad} 格为虚拟 +∞")
    rows = [[r * q + c for c in range(q)] for r in range(p)]
    cols = [[r * q + c for r in range(p)] for c in range(q)]

    for rd in range(rounds):
        if col_first:
            for c in range(q):
                _net_range(v, cols[c])
            for r in range(p):
                if snake_rows and r % 2:
                    _net_range_desc(v, rows[r])
                else:
                    _net_range(v, rows[r])
        else:
            for r in range(p):
                if snake_rows and r % 2:
                    _net_range_desc(v, rows[r])
                else:
                    _net_range(v, rows[r])
            for c in range(q):
                _net_range(v, cols[c])
        va.msg(f"第 {rd + 1}/{rounds} 轮：行列交替排序完成")
        va.clear_marks()
        for r in range(p):
            va.mark(r * q, ROLE_BOUNDARY)
    for r in range(p):
        _net_range(v, rows[r])
    va.msg("最终统一按行升序收尾")
    va.clear_marks()
    for i in range(n):
        va.mark(i, ROLE_SORTED)


@register_algo(
    algo_id="141_shear_sort",
    name_zh="二维蛇形矩阵剪切排序 Shear Sort",
    name_en="Shear Sort (2D Snake Matrix)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="把一维数组铺成 p×q 矩阵（p 取 2 的幂，尾部补虚拟 +∞），然后反复执行"
         "两个动作：① 逐行排序，**奇数行升序、偶数行降序**，形成一条上下翻飞的"
         "「蛇形」；② 逐列纵向升序。蛇形是关键——它让第 r 行的元素只能「爬到」"
         "某一列后再折返，从而保证 ⌈log₂p⌉ + 1 轮之后矩阵必然整体有序。"
         "最后统一按行升序收尾，前 n 格即为答案。",
)
def shear_sort(arr):
    n = arr.n
    if n < 2:
        return
    p, _q = _mat_dims(n)
    rounds = p.bit_length() + 1
    _matrix_sort(arr, n, snake_rows=True, col_first=False, rounds=rounds)


# ==========================================================================
# #142 Column Sort (Leighton)
# ==========================================================================
def _transpose(v: _Virtual, p: int, q: int) -> None:
    """矩阵转置：按循环置换在原位把 p×q 变成 q×p（全部用真实交换指令完成）。"""
    seen = [False] * (p * q)

    def src_of(i: int) -> int:
        # 目标位置 i 在新矩阵中的坐标是 (i % p, i // p)，对应旧矩阵的 (i // p, i % p)
        return (i % p) * q + (i // p)

    for start in range(p * q):
        if seen[start]:
            continue
        cur = start
        while True:
            seen[cur] = True
            nxt = src_of(cur)
            if seen[nxt]:
                break
            v.swap(cur, nxt)
            cur = nxt


@register_algo(
    algo_id="142_column_sort",
    name_zh="矩阵列排序 Column Sort (Leighton)",
    name_en="Column Sort (Leighton)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(1)", stable=False,
    desc="Leighton 1985 年为超立方体与网格并行机设计的经典算法。原版严格限定"
         "行列比例（n = r·s 且 s 为 r 的倍数、r 足够大），因此本实现采用**自适应"
         "多趟收敛**的等价形式：把数组重塑成 p×q 矩阵后，每轮执行"
         "『逐列升序排序 → 矩阵转置（真实的循环置换！）→ 逐列升序排序 → 转置回来"
         "→ 逐行蛇形排序』，多轮之后矩阵自然有序，最后统一按行升序收尾。"
         "转置本身会打乱布局，正是 Leighton「8 步法」中最有看点的一步。",
)
def column_sort(arr):
    n = arr.n
    if n < 2:
        return
    p, q = _mat_dims(n)
    rounds = p.bit_length() + 3
    N = p * q
    inf = (max(arr.values()) if n else 0) + 1
    v = _Virtual(arr, n, N, inf)
    if v.pad:
        arr.msg(f"重塑为 {p}×{q} 矩阵（共 {N} 格），尾部 {v.pad} 格为虚拟 +∞")

    rows = [[r * q + c for c in range(q)] for r in range(p)]
    cols = [[r * q + c for r in range(p)] for c in range(q)]
    for rd in range(rounds):
        for c in range(q):
            _net_range(v, cols[c])
        arr.msg(f"第 {rd + 1}/{rounds} 轮：列内排序完毕，执行矩阵转置")
        _transpose(v, p, q)
        p, q = q, p
        rows = [[r * q + c for c in range(q)] for r in range(p)]
        cols = [[r * q + c for r in range(p)] for c in range(q)]
        for c in range(q):
            _net_range(v, cols[c])
        arr.msg("转置回来")
        _transpose(v, p, q)
        p, q = q, p
        rows = [[r * q + c for c in range(q)] for r in range(p)]
        cols = [[r * q + c for r in range(p)] for c in range(q)]
        for r in range(p):
            if r % 2:
                _net_range_desc(v, rows[r])
            else:
                _net_range(v, rows[r])
    for r in range(p):
        _net_range(v, rows[r])
    arr.msg("多趟收敛结束：按行升序收尾")
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# #143 Weave Sorting Network
# ==========================================================================
@register_algo(
    algo_id="143_weave_network",
    name_zh="交织比较器网络 Weave Sorting Network",
    name_en="Weave Sorting Network",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(1)", stable=False,
    desc="自底向上归并，但每一步归并都**不比较跨段的两个头**：而是先把两段有序"
         "子列像洗牌一样完美交错（a₁ b₁ a₂ b₂ …），再只用「相邻元素」比较器反复"
         "扫描若干趟把它们理顺。交错之后每个元素的错位量不超过半段长，因此相邻"
         "比较器要扫够半段长那么多趟——这正是「完美洗牌 + 相邻比较器」的代价。",
)
def weave_network(arr):
    n = arr.n
    if n < 2:
        return
    N = _logical_len(n)
    inf = max(arr.values()) + 1
    v = _Virtual(arr, n, N, inf)
    if v.pad:
        arr.msg(f"用 {v.pad} 个虚拟 +∞ 补齐到 N={N}")
    w = 1
    while w < N:
        lo = 0
        while lo + 2 * w <= N:
            # 完美洗牌：把 [lo, lo+w) 与 [lo+w, lo+2w) 交错
            left = [v.va.peek(lo + k) if lo + k < n else inf for k in range(w)]
            right = [v.va.peek(lo + w + k) if lo + w + k < n else inf for k in range(w)]
            inter: List[int] = []
            for k in range(w):
                inter.append(left[k])
                inter.append(right[k])
            for k, val in enumerate(inter):
                pos = lo + k
                if pos < n:
                    v.va.set(pos, val)
                else:
                    v.va.aux_set(pos - n, val)
            # 相邻比较器扫描 w 趟
            for _ in range(w):
                for i in range(lo, lo + 2 * w - 1, 2):
                    v.cmp_ex(i, i + 1)
                for i in range(lo + 1, lo + 2 * w - 1, 2):
                    v.cmp_ex(i, i + 1)
            lo += 2 * w
        arr.msg(f"交织归并块宽 {2 * w} 完成")
        w <<= 1
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("交织网络跑完：数组有序")


# ==========================================================================
# #144 Diamond / Pratt Network Sort
# ==========================================================================
@register_algo(
    algo_id="144_diamond_pratt_network",
    name_zh="菱形 / Pratt 对角波前网络 Diamond / Pratt Network",
    name_en="Diamond / Pratt Network Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(1)", stable=False,
    desc="Pratt 1971 年研究比较器网络下界时给出的确定性构造。把比较器按「对角线"
         "波前」排布：波前从右上角出发，一路推向左下角，每前进一步跨度就减 1，"
         "整趟跨越 n-1 个跨度，再循环若干趟。可视化时能看到醒目的菱形波纹自右"
         "向左扫过整个数组，是「确定性网络」最直观的演示。",
)
def diamond_pratt_network(arr):
    n = arr.n
    if n < 2:
        return
    _run_network(arr, n, _anti_sweep(_logical_len(n), rounds=2))
