# -*- coding: utf-8 -*-
"""类别 11：教学、幽默与极限慢速排序（#151 ~ #160，共 10 种）。

本类算法分为三组：

* **慢速分治组**：#151 慢排序 / #152 臭皮匠排序 / #153 傻瓜排序
  —— 用「重叠子问题」制造夸张的时间复杂度，是递归复杂度分析的最佳教具
* **物理模拟组**：#154 意大利面排序 / #155 睡眠排序
  —— 把排序想象成一次物理过程（抽面条 / 定时器唤醒）
* **猴子随机组**：#156 猴子排序 / #157 蠢蛋排序 / #158 渐进锁定猴子排序 /
  #159 双向锁定猴子排序 —— 靠随机碰运气，必须内置熔断

## 关于熔断（安全阀）

猴子家族在 N 稍大时**期望收敛时间趋于无穷**：纯随机洗牌命中「恰好有序」的概率
是 ``1/n!``。因此本实现遵循规范书「内置安全步数熔断提示」的要求：

1. 随机阶段使用**固定种子的伪随机数**，保证指令流完全可复现（否则单步回放会失真）；
2. 当尝试次数超过阈值后，转入**确定性收尾**——不再靠运气，而是把还没归位的
   位置逐个锁定。这样既保留了「猴子乱撞」的教学看点，又保证任意规模下都能在
   有限步内结束，且结果绝对正确。

慢速分治组同理：慢排序与臭皮匠排序在 N 稍大时操作数会爆炸增长，因此实现上采用
「分块 + 原地归并」的工程化封装（块内跑原汁原味的递归），保证 160 种算法在统一
自检规模下全部可运行。
"""

from __future__ import annotations

import random

from core.protocol import ROLE_CURSOR, ROLE_MAX, ROLE_MIN, ROLE_SORTED
from core.registry import register_algo

from ._util import aux_merge_sort, insertion_sort_range, sym_merge

CATEGORY = "11. 教学与幽默极限排序 (Educational & Esoteric Sorts)"


# ==========================================================================
# #151 Slow Sort (Multiply and Surrender)
# ==========================================================================
def _slow_core(va, i: int, j: int) -> None:
    """原汁原味的「乘积与投降」递归：排左半 → 排右半 → 把最大者换到末尾 → 再排前缀。"""
    if i >= j:
        return
    m = (i + j) >> 1
    _slow_core(va, i, m)
    _slow_core(va, m + 1, j)
    if va.gt(m, j):
        va.swap(m, j)
    _slow_core(va, i, j - 1)


@register_algo(
    algo_id="151_slow_sort",
    name_zh="慢排序 Slow Sort",
    name_en="Slow Sort (Multiply and Surrender)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n^{log n})", time_worst="O(n^{log n})",
    space="O(log n)", stable=False,
    desc="Broder 与 Stolfi 的幽默分治算法「乘积与投降」：递归排左半、递归排右半，"
         "把两半的最大值比一比、换到最末尾，然后**又**递归排「去掉最后一个元素」的"
         "整个前缀——子问题规模几乎不缩小，于是复杂度从 n log n 膨胀到 n^{log n}。"
         "为让任意规模都能在有限步内跑完，实现上把数组切成不超过 32 的块，块内使用"
         "原版递归，块间用原地归并收尾。",
    extra={"max_n": 512},
)
def slow_sort(arr):
    n = arr.n
    if n < 2:
        return
    block = 32
    for lo in range(0, n, block):
        hi = min(lo + block, n) - 1
        arr.msg(f"块 [{lo}, {hi}]：启动「乘积与投降」递归")
        _slow_core(arr, lo, hi)
    width = block
    while width < n:
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                sym_merge(arr, lo, mid, hi)
            lo += 2 * width
        width <<= 1
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("各块归并完毕：数组有序")


# ==========================================================================
# #152 Stooge Sort
# ==========================================================================
def _stooge_core(va, i: int, j: int) -> None:
    if i >= j:
        return
    if va.gt(i, j):
        va.swap(i, j)
    if j - i + 1 > 2:
        t = (j - i + 1) // 3
        _stooge_core(va, i, j - t)
        _stooge_core(va, i + t, j)
        _stooge_core(va, i, j - t)


@register_algo(
    algo_id="152_stooge_sort",
    name_zh="臭皮匠排序 Stooge Sort",
    name_en="Stooge Sort",
    category=CATEGORY,
    time_best="O(n^{2.71})", time_avg="O(n^{2.71})", time_worst="O(n^{2.71})",
    space="O(log n)", stable=False,
    desc="首尾逆序就交换，然后把前 2/3 递归排一遍、后 2/3 递归排一遍，最后**再**"
         "把前 2/3 排一遍（第三遍不是多余的，因为第二遍会打乱第一遍的成果）。"
         "递推式 T(n) = 3T(2n/3) 给出 O(n^{log_{1.5}3}) ≈ O(n^2.7095)。"
         "为让任意规模都能跑完，实现上先用不超过 40 的块跑原版递归，再原地归并。",
    extra={"max_n": 512},
)
def stooge_sort(arr):
    n = arr.n
    if n < 2:
        return
    block = 40
    for lo in range(0, n, block):
        hi = min(lo + block, n) - 1
        arr.msg(f"块 [{lo}, {hi}]：三重叠递归开启")
        _stooge_core(arr, lo, hi)
    width = block
    while width < n:
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            if mid < hi:
                sym_merge(arr, lo, mid, hi)
            lo += 2 * width
        width <<= 1
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("各块归并完毕：数组有序")


# ==========================================================================
# #153 Silly Sort
# ==========================================================================
def _silly_core(va, lo: int, hi: int) -> None:
    """重叠分治：两半各自递归后，对整个区间再做一趟「双循环交换」，然后再叠一次。"""
    if lo >= hi:
        return
    mid = (lo + hi) >> 1
    _silly_core(va, lo, mid)
    _silly_core(va, mid + 1, hi)
    for i in range(lo, hi):
        for j in range(i + 1, hi + 1):
            if va.gt(i, j):
                va.swap(i, j)
    _silly_core(va, lo, mid)


@register_algo(
    algo_id="153_silly_sort",
    name_zh="傻瓜排序 Silly Sort",
    name_en="Silly Sort",
    category=CATEGORY,
    time_best="O(n²)", time_avg="O(n²)", time_worst="O(n²)",
    space="O(log n)", stable=False,
    desc="刻意把分治写成「重叠」的样子：先把左右两半各自排好，紧接着对整个区间"
         "做一趟双循环交换（每个元素和它右侧所有元素比一遍，保证区间内完全有序），"
         "然后又把左半再排一遍。三重叠的递归树让比较次数膨胀到朴素选择的数倍，"
         "是「看起来分治、实际白干」的经典反面教材。",
)
def silly_sort(arr):
    n = arr.n
    if n < 2:
        return
    _silly_core(arr, 0, n - 1)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("重叠分治收敛：数组有序")


# ==========================================================================
# #154 Spaghetti Sort (Mechanical Scan)
# ==========================================================================
@register_algo(
    algo_id="154_spaghetti_sort",
    name_zh="意大利面排序 Spaghetti Sort",
    name_en="Spaghetti Sort (Mechanical Scan)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n + m)", time_worst="O(n + m)",
    space="O(n)", stable=True,
    desc="把每根面条按长度立在桌面上，手掌从最高处水平向下平移：碰到哪根就把它"
         "抽出来放到已排序列的末尾。辅助缓冲保存「面条长度」与「是否已被抽走」"
         "两个字段。手掌下降的每一格都是一次刻度事件，抽走动作才是真正的数据写入，"
         "因此主数组的总写入次数恰好等于元素个数。m 为最大面条长度。",
    extra={"max_n": 1024},
)
def spaghetti_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(2 * n)
    for i in range(n):
        arr.aux_set(i, arr.get(i))          # [0, n)  面条长度
        arr.aux_set(n + i, 0)               # [n, 2n) 是否已被抽走
    buckets = {}
    mx = 0
    for i in range(n):
        v = arr.aux_peek(i)
        buckets.setdefault(v, []).append(i)
        if v > mx:
            mx = v

    # 手掌自最高处向下平移：最先被抽走的是最长的面条，因此按**降序**写入
    # 结果数组的最后一位开始往前填，最终结果仍是升序。
    out = n - 1
    for height in range(mx, 0, -1):
        if height not in buckets:
            continue
        for i in buckets[height]:
            if arr.aux_peek(n + i):
                continue
            arr.aux_set(n + i, 1)
            arr.mark(i, ROLE_MAX)
            arr.set(out, height)
            arr.mark(out, ROLE_SORTED)
            out -= 1
        arr.msg(f"手掌降至高度 {height}：抽走 {len(buckets[height])} 根面条")
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("面条全部抽完并按长度就位：数组有序")


# ==========================================================================
# #155 Sleep Sort (Discrete Event Simulation)
# ==========================================================================
@register_algo(
    algo_id="155_sleep_sort",
    name_zh="睡眠排序 Sleep Sort",
    name_en="Sleep Sort (Discrete Event Simulation)",
    category=CATEGORY,
    time_best="O(n + m)", time_avg="O(n + m)", time_worst="O(n + m)",
    space="O(n)", stable=True,
    desc="不创建任何真实线程，而是把「睡眠时长 = 元素数值」注册进离散事件队列："
         "虚拟时钟从最小时刻走到最大时刻，每到一个刻度就把该时刻「醒来」的元素按"
         "注册先后顺序收集起来。因为醒来时刻就是数值本身，收集顺序天然升序；"
         "同一时刻按注册先后收集，因此是稳定的。m 为值域宽度。",
    extra={"max_n": 2048},
)
def sleep_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    events = {}
    lo_t, hi_t = arr.get(0), arr.get(0)
    for i in range(n):
        v = arr.get(i)
        arr.aux_set(i, v)
        events.setdefault(v, []).append(i)
        if v < lo_t:
            lo_t = v
        if v > hi_t:
            hi_t = v
    out = 0
    for tick in range(lo_t, hi_t + 1):
        waiting = events.get(tick)
        if not waiting:
            continue
        for i in waiting:
            arr.mark(i, ROLE_CURSOR)
        for i in waiting:
            arr.set(out, tick)
            arr.mark(out, ROLE_SORTED)
            out += 1
        arr.msg(f"虚拟时钟 {tick}：{len(waiting)} 个元素醒来并被收集")
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("所有定时器触发完毕：数组有序")


# ==========================================================================
# 猴子家族公共工具
# ==========================================================================
def _is_sorted(va) -> bool:
    d = va.data
    for i in range(len(d) - 1):
        if d[i] > d[i + 1]:
            return False
    return True


def _shuffle(va, lo: int, hi: int, rng: random.Random) -> None:
    """Fisher-Yates 洗牌（半开区间 ``[lo, hi)``），固定种子保证可复现。"""
    for k in range(hi - 1, lo, -1):
        r = rng.randrange(lo, k + 1)
        if r != k:
            va.swap(k, r)


def _deterministic_finish(va, lo: int, hi: int) -> None:
    """确定性收尾：把 ``[lo, hi)`` 用「锁定最小值」的方式逐个归位。"""
    for i in range(lo, hi - 1):
        p = i
        for j in range(i + 1, hi):
            if va.cmp(j, p):
                p = j
        if p != i:
            va.swap(i, p)
        va.mark(i, ROLE_SORTED)


def _finish_all(va) -> None:
    arr_sorted = va.data
    if all(arr_sorted[i] <= arr_sorted[i + 1] for i in range(len(arr_sorted) - 1)):
        return
    _deterministic_finish(va, 0, va.n)


# ==========================================================================
# #156 Bogo Sort (Monkey Shuffle)
# ==========================================================================
@register_algo(
    algo_id="156_bogo_sort",
    name_zh="猴子排序 Bogo Sort",
    name_en="Bogo Sort (Monkey Shuffle)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n·n!)", time_worst="O(∞)",
    space="O(1)", stable=False,
    desc="猴子敲键盘：每轮先检查是否有序，无序就用 Fisher-Yates 把整个数组彻底打乱，"
         "如此反复碰运气。命中「恰好有序」的概率是 1/n!，所以 N 稍大就基本不可能收敛。"
         "本实现使用固定种子的伪随机数保证指令流可复现，并在尝试次数超过阈值时启动"
         "安全熔断，转入确定性收尾（逐个锁定最小值），保证有限步内一定结束。",
    extra={"max_n": 64, "note": "教学演示，N ≤ 8 时可观察到真实收敛"},
)
def bogo_sort(arr):
    n = arr.n
    if n < 2:
        return
    rng = random.Random(0xB090)
    limit = max(64, 4 * n)
    attempt = 0
    while not _is_sorted(arr) and attempt < limit:
        attempt += 1
        _shuffle(arr, 0, n, rng)
    arr.msg(f"随机阶段结束：共洗牌 {attempt} 次")
    if not _is_sorted(arr):
        arr.msg("安全熔断触发：转入确定性收尾")
        _finish_all(arr)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("数组有序")


# ==========================================================================
# #157 Bozo Sort (Random Pair Swap)
# ==========================================================================
@register_algo(
    algo_id="157_bozo_sort",
    name_zh="蠢蛋排序 Bozo Sort",
    name_en="Bozo Sort (Random Pair Swap)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n·n!)", time_worst="O(∞)",
    space="O(1)", stable=False,
    desc="比猴子排序更懒惰：不打乱整个数组，只是每次随机抽出两个下标交换一次，"
         "然后看看是否有幸刚好有序。它其实等价于在一个巨大的置换图上做随机游走，"
         "收敛所需步数同样是天文数字，因此同样内置固定种子与安全熔断机制。",
    extra={"max_n": 64, "note": "教学演示"},
)
def bozo_sort(arr):
    n = arr.n
    if n < 2:
        return
    rng = random.Random(0xB020)
    limit = max(64, 5 * n)
    attempt = 0
    while not _is_sorted(arr) and attempt < limit:
        attempt += 1
        i = rng.randrange(n)
        j = rng.randrange(n)
        if i != j:
            arr.swap(i, j)
    arr.msg(f"随机对换阶段结束：共尝试 {attempt} 次")
    if not _is_sorted(arr):
        arr.msg("安全熔断触发：转入确定性收尾")
        _finish_all(arr)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("数组有序")


# ==========================================================================
# #158 Less Bogo Sort (Progressive Prefix Lock)
# ==========================================================================
def _lock_prefix(va, lock: int) -> int:
    """从 lock 位置起尽可能向右扩大「已锁定前缀」（等于剩余部分的最小值序列）。"""
    n = va.n
    while lock < n:
        p = lock
        for j in range(lock + 1, n):
            if va.cmp(j, p):
                p = j
        if p == lock:
            va.mark(lock, ROLE_SORTED)
            lock += 1
        else:
            break
    return lock


@register_algo(
    algo_id="158_less_bogo_sort",
    name_zh="渐进锁定猴子排序 Less Bogo Sort",
    name_en="Less Bogo Sort (Progressive Prefix Lock)",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n² log n)", time_worst="O(n² log n)",
    space="O(1)", stable=False,
    desc="猴子排序的实用化改良：每轮只对**尚未锁定**的后缀做 Fisher-Yates 洗牌，"
         "洗完后检查前缀有没有碰巧又对上了——只要某位置的元素恰好等于剩余部分的"
         "最小值，就把这一位永久锁定，不再参与后续洗牌。随着锁定的前缀越来越长，"
         "洗牌区间越来越短，收敛速度远快于原始猴子排序。",
    extra={"max_n": 512},
)
def less_bogo_sort(arr):
    n = arr.n
    if n < 2:
        return
    rng = random.Random(0x1E55)
    lock = _lock_prefix(arr, 0)
    limit = max(128, 6 * n)
    attempt = 0
    while lock < n and attempt < limit:
        attempt += 1
        _shuffle(arr, lock, n, rng)
        lock = _lock_prefix(arr, lock)
    arr.msg(f"洗牌 {attempt} 次后已锁定前缀长度 {lock}")
    if lock < n:
        arr.msg("安全熔断触发：转入确定性收尾")
        _deterministic_finish(arr, lock, n)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("数组有序")


# ==========================================================================
# #159 Cocktail Bogo Sort
# ==========================================================================
@register_algo(
    algo_id="159_cocktail_bogo_sort",
    name_zh="双向锁定猴子排序 Cocktail Bogo Sort",
    name_en="Cocktail Bogo Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n² log n)", time_worst="O(n² log n)",
    space="O(1)", stable=False,
    desc="同时从两端锁定：既看后缀的最小值有没有恰好落到左端，也看后缀的最大值"
         "有没有恰好落到右端，两头的「巧合」都会被立即锁定，让随机洗牌的区间从"
         "两侧同时收窄。相比只锁左侧的渐进锁定版本，收敛更快。",
    extra={"max_n": 512},
)
def cocktail_bogo_sort(arr):
    n = arr.n
    if n < 2:
        return
    rng = random.Random(0xC0C7)

    def relock(lo, hi):
        while lo < hi:
            pmin = lo
            for j in range(lo + 1, hi):
                if arr.cmp(j, pmin):
                    pmin = j
            if pmin == lo:
                arr.mark(lo, ROLE_SORTED)
                lo += 1
            else:
                break
        while lo < hi:
            pmax = hi - 1
            for j in range(lo, hi - 1):
                if arr.gt(j, pmax):
                    pmax = j
            if pmax == hi - 1:
                arr.mark(hi - 1, ROLE_SORTED)
                hi -= 1
            else:
                break
        return lo, hi

    lo, hi = 0, n
    lo, hi = relock(lo, hi)
    limit = max(128, 6 * n)
    attempt = 0
    while lo < hi and attempt < limit:
        attempt += 1
        _shuffle(arr, lo, hi, rng)
        lo, hi = relock(lo, hi)
    arr.msg(f"洗牌 {attempt} 次后锁定区间为 [{lo}, {hi})")
    if lo < hi:
        arr.msg("安全熔断触发：转入确定性收尾")
        _deterministic_finish(arr, lo, hi)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("数组有序")


# ==========================================================================
# #160 Stalin Sort + Gulag Re-merge
# ==========================================================================
@register_algo(
    algo_id="160_stalin_sort",
    name_zh="斯大林检阅重归并排序 Stalin Sort",
    name_en="Stalin Sort + Gulag Re-merge",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=True,
    desc="第一遍线性检阅：凡是小于前一个元素的「不合群分子」全部流放到辅助区"
         "（古拉格），留下来的人保持严格不减。流放区随后在辅助缓冲内部做归并排序，"
         "最后把「留守序列」与「流放序列」用原地对称归并合并回来——数据一个不少，"
         "最终完整有序。这也是「先破坏再收拾」这一幽默梗的正确收尾方式。",
)
def stalin_sort(arr):
    n = arr.n
    if n < 2:
        return
    # 需要 2n 格：前 n 格放流放区数据，后 n 格留给归并排序的乒乓暂存区
    arr.aux_init(2 * n)
    loyal: list[int] = []
    gulag: list[int] = []
    arr.msg("第一遍检阅：不合群分子（小于前一个元素）直接流放")
    for i in range(n):
        v = arr.get(i)
        if not loyal or v >= loyal[-1]:
            arr.mark(i, ROLE_SORTED)
            loyal.append(v)
        else:
            arr.mark(i, ROLE_MAX)
            gulag.append(v)
    k = len(loyal)
    if not gulag:
        arr.msg("无人被流放：数组本就严格有序")
        arr.aux_clear()
        return
    arr.msg(f"留守 {k} 人，流放 {len(gulag)} 人")
    # 关键：留守分子与流放分子在原数组里是**交错**的，必须先把留守序列压实到
    # 前 k 格（否则写回流放区会覆盖掉后排的留守分子），再把流放区就地排序。
    for t, val in enumerate(loyal):
        arr.set(t, val)
    arr.msg("留守序列已压实到左侧；流放区就地归并排序")
    for t, val in enumerate(gulag):
        arr.aux_set(t, val)
    m = len(gulag)
    aux_merge_sort(arr, 0, m, m)
    arr.msg("把流放区写回主数组右侧")
    for t in range(m):
        arr.set(k + t, arr.aux_peek(t))
    arr.aux_clear()
    arr.msg("原地对称归并：留守序列 + 流放序列 → 完整有序序列")
    sym_merge(arr, 0, k, n)
    arr.clear_marks()
    for i in range(n):
        arr.mark(i, ROLE_SORTED)
    arr.msg("所有人都归位：数组有序")
