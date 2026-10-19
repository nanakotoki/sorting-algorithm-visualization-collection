# -*- coding: utf-8 -*-
"""类别 02 —— 选择、锦标赛与循环置换排序（#019 ~ #030，共 12 种）。

简单/双向/稳定选择、宾果、圈排序（含优化版）、胜者树与败者树锦标赛、
笛卡尔树、砂纸、滚动选择以及双端最小-最大堆排序。
"""

from __future__ import annotations

from core.protocol import ROLE_CURSOR, ROLE_MAX, ROLE_MIN, ROLE_PIVOT, ROLE_SORTED
from core.registry import register_algo

from ._util import AUX, mm_build, mm_fix, mm_sift_down

CATEGORY = "02. 选择、锦标赛与循环置换排序 (Selection, Tournament & Cycle)"


# ==========================================================================
# 1  简单选择排序
# ==========================================================================
@register_algo(
    algo_id="019_selection_sort",
    name_zh="标准简单选择排序",
    name_en="Selection Sort",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="每一趟在未排序区线性扫描一次最小值，与未排序区首位一次性交换。",
)
def selection_sort(arr):
    n = arr.n
    for i in range(n - 1):
        m = i
        for j in range(i + 1, n):
            if arr.cmp(j, m):
                m = j
        arr.mark(m, ROLE_MIN)
        arr.msg(f"第 {i + 1} 趟：最小值在 arr[{m}] → 交换到 arr[{i}]")
        arr.clear_marks()
        if m != i:
            arr.swap(i, m)
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 2  双向选择排序
# ==========================================================================
@register_algo(
    algo_id="020_double_selection_sort",
    name_zh="双向选择排序",
    name_en="Double Selection Sort (Cocktail Selection)",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="单趟扫描同时找出最小值与最大值，一次性把两个极值分别送回首尾两端，"
         "外层次数减半。",
)
def double_selection_sort(arr):
    n = arr.n
    lo, hi = 0, n - 1
    while lo < hi:
        mn = mx = lo
        for j in range(lo + 1, hi + 1):
            if arr.cmp(j, mn):
                mn = j
            if arr.cmp(mx, j):
                mx = j
        arr.mark(mn, ROLE_MIN)
        arr.mark(mx, ROLE_MAX)
        arr.msg(f"区间 [{lo}, {hi}]：最小 arr[{mn}]，最大 arr[{mx}]")
        if mn != lo:
            arr.swap(lo, mn)
            if mx == lo:          # 最大值恰好被前一次交换搬到了 mn
                mx = mn
        if mx != hi:
            arr.swap(hi, mx)
        arr.clear_marks()
        arr.mark(lo, ROLE_SORTED)
        arr.mark(hi, ROLE_SORTED)
        lo += 1
        hi -= 1


# ==========================================================================
# 3  稳定选择排序
# ==========================================================================
@register_algo(
    algo_id="021_stable_selection_sort",
    name_zh="稳定选择排序",
    name_en="Stable Selection Sort",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=True,
    desc="找到最小值后不使用跨位置 SWAP，而是把中间整段元素向右平移一格再插入，"
         "从而保持相等元素的原始相对次序。",
)
def stable_selection_sort(arr):
    n = arr.n
    for i in range(n - 1):
        m = i
        for j in range(i + 1, n):
            if arr.cmp(j, m):
                m = j
        if m != i:
            arr.msg(f"最小值 arr[{m}] 右移插入到 arr[{i}]（保持稳定性）")
            v = arr.get(m)
            for k in range(m, i, -1):
                arr.set(k, arr.get(k - 1))
            arr.set(i, v)
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 4  宾果排序
# ==========================================================================
@register_algo(
    algo_id="022_bingo_sort",
    name_zh="宾果排序",
    name_en="Bingo Sort",
    category=CATEGORY,
    time_best="O(n)", time_avg="O(n * m)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="先锁定当前最大值，下一趟把所有等于该最大值的重复元素一次性搬到位，"
         "对大量重复值的数据极快（m 为不同值的个数）。",
)
def bingo_sort(arr):
    n = arr.n
    if n < 2:
        return
    m0 = 0
    for j in range(1, n):
        if arr.cmp(m0, j):
            m0 = j
    cur_max = arr.get(m0)
    end = n - 1
    round_no = 0
    while end > 0:
        round_no += 1
        nxt = None
        i = 0
        while i <= end:
            v = arr.get(i)
            if v == cur_max:
                if i != end:
                    arr.swap(i, end)
                arr.mark(end, ROLE_SORTED)
                end -= 1
                continue          # 交换后 arr[i] 是原 arr[end]，需重新检查
            if nxt is None or not arr.cmp_val(i, nxt):
                nxt = v
            i += 1
        arr.msg(f"第 {round_no} 轮：把所有 {cur_max} 一次性归位")
        if nxt is None:
            break
        cur_max = nxt
    for k in range(n):
        arr.mark(k, ROLE_SORTED)


# ==========================================================================
# 5 ~ 6  圈排序
# ==========================================================================
@register_algo(
    algo_id="023_cycle_sort",
    name_zh="标准圈排序",
    name_en="Cycle Sort (Standard)",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="计算每个元素前面有多少个比它小的元素来确定目标坐标，再沿置换环写回，"
         "实现理论最少的写次数（每个元素最多写 1 次）。",
)
def cycle_sort(arr):
    n = arr.n
    if n < 2:
        return
    for start in range(n - 1):
        item = arr.get(start)
        pos = start
        for i in range(start + 1, n):
            if arr.cmp_val(i, item):
                pos += 1
        if pos == start:
            arr.mark(start, ROLE_SORTED)
            continue
        arr.msg(f"置换环起点 arr[{start}]，目标坐标 {pos}")
        while pos < n and arr.peek(pos) == item:
            pos += 1
        if pos >= n:
            continue
        buf = arr.peek(pos)
        arr.set(pos, item)
        item = buf
        while pos != start:
            pos = start
            for i in range(start + 1, n):
                if arr.cmp_val(i, item):
                    pos += 1
            while pos < n and arr.peek(pos) == item:
                pos += 1
            if pos >= n:
                break
            buf = arr.peek(pos)
            arr.set(pos, item)
            item = buf
        arr.mark(start, ROLE_SORTED)


@register_algo(
    algo_id="024_optimized_cycle_sort",
    name_zh="优化原地圈排序",
    name_en="Optimized In-Place Cycle Sort",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="快速跳过已经处于正确位置的元素：若当前元素与前一个元素相等，则它必然"
         "已经就位，直接跳过整段计数扫描；同时跳过重复值环。",
)
def optimized_cycle_sort(arr):
    n = arr.n
    if n < 2:
        return
    prev_item = None
    prev_pos = None
    for start in range(n - 1):
        # 与前一个元素相等 → 已就位（保持相等的相对次序的前提）
        if (start > 0 and not arr.cmp(start, start - 1)
                and not arr.cmp(start - 1, start)):
            arr.mark(start, ROLE_SORTED)
            continue
        item = arr.get(start)
        if prev_item is not None and item == prev_item and prev_pos is not None:
            pos = prev_pos
        else:
            pos = start
            for i in range(start + 1, n):
                if arr.cmp_val(i, item):
                    pos += 1
        if pos == start:
            arr.mark(start, ROLE_SORTED)
            prev_item, prev_pos = item, None
            continue
        while pos < n and arr.peek(pos) == item:
            pos += 1
        if pos >= n:
            continue
        buf = arr.peek(pos)
        arr.set(pos, item)
        item = buf
        while pos != start:
            pos = start
            for i in range(start + 1, n):
                if arr.cmp_val(i, item):
                    pos += 1
            while pos < n and arr.peek(pos) == item:
                pos += 1
            if pos >= n:
                break
            buf = arr.peek(pos)
            arr.set(pos, item)
            item = buf
        prev_item, prev_pos = None, None
        arr.mark(start, ROLE_SORTED)


# ==========================================================================
# 7  胜者树锦标赛排序
# ==========================================================================
@register_algo(
    algo_id="025_tournament_sort",
    name_zh="胜者树锦标赛排序",
    name_en="Tournament Sort (Winner Tree)",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="在辅助数组中构建一棵完全二叉树「胜者树」，每个内部节点保存两个孩子中的"
         "较小值；每次取出树根最小值后只沿该叶子到根的路径重新比赛。",
)
def tournament_sort(arr):
    n = arr.n
    if n < 2:
        return
    size = 1
    while size < n:
        size <<= 1
    inf = max(arr.data) + 1
    arr.aux_init(2 * size)
    arr.msg(f"搭建胜者树：叶子 {size} 个，内部节点 {size - 1} 个")
    for i in range(n):
        arr.aux_set(size + i, arr.get(i))
    for i in range(n, size):
        arr.aux_set(size + i, inf)
    for p in range(size - 1, 0, -1):
        a = arr.aux_peek(2 * p)
        b = arr.aux_peek(2 * p + 1)
        if arr.aux_cmp(2 * p + 1, 2 * p):
            arr.aux_set(p, b)
        else:
            arr.aux_set(p, a)

    for k in range(n):
        v = arr.aux_peek(1)
        arr.set(k, v)
        arr.mark(k, ROLE_SORTED)
        p = 1
        while p < size:
            left = 2 * p
            p = left if arr.aux_peek(left) == v else left + 1
        arr.aux_set(p, inf)
        p >>= 1
        while p >= 1:
            a = arr.aux_peek(2 * p)
            b = arr.aux_peek(2 * p + 1)
            if arr.aux_cmp(2 * p + 1, 2 * p):
                arr.aux_set(p, b)
            else:
                arr.aux_set(p, a)
            p >>= 1
        if k % max(1, n // 8) == 0:
            arr.msg(f"已产出 {k + 1}/{n} 个最小值")


# ==========================================================================
# 8  败者树锦标赛排序
# ==========================================================================
@register_algo(
    algo_id="026_loser_tree_sort",
    name_zh="败者树锦标赛排序",
    name_en="Loser Tree Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="父节点只记录落败者、冠军继续向上传递，因此重构时无需访问兄弟节点，"
         "比赛次数比胜者树更少。",
)
def loser_tree_sort(arr):
    n = arr.n
    if n < 2:
        return
    size = 1
    while size < n:
        size <<= 1
    inf = max(arr.data) + 1
    arr.aux_init(size + 1)
    arr.msg(f"搭建败者树：{size} 个叶子 + 1 个无穷大哨兵")
    for i in range(n):
        arr.aux_set(i, arr.get(i))
    for i in range(n, size):
        arr.aux_set(i, inf)
    arr.aux_set(size, inf)                 # 哨兵槽，供初始化 ls[] 使用
    loser = [size] * size                  # loser[t] = 节点 t 的败者叶子；loser[0] = 冠军
    win = [0] * (2 * size)
    for j in range(size):
        win[size + j] = j
    for p in range(size - 1, 0, -1):
        a, b = win[2 * p], win[2 * p + 1]
        if arr.aux_cmp(b, a):              # aux[b] < aux[a]
            win[p], loser[p] = b, a
        else:
            win[p], loser[p] = a, b
    loser[0] = win[1]

    def adjust(j: int) -> None:
        s = j
        t = (size + j) >> 1
        while t >= 1:
            if not arr.aux_cmp(s, loser[t]):   # aux[loser[t]] <= aux[s] → 挑战者落败
                s, loser[t] = loser[t], s
            t >>= 1
        loser[0] = s

    for k in range(n):
        champ = loser[0]
        v = arr.aux_peek(champ)
        arr.set(k, v)
        arr.mark(k, ROLE_SORTED)
        arr.aux_set(champ, inf)
        adjust(champ)
        if k % max(1, n // 8) == 0:
            arr.msg(f"已产出 {k + 1}/{n} 个最小值")


# ==========================================================================
# 9  笛卡尔树排序
# ==========================================================================
@register_algo(
    algo_id="027_cartesian_tree_sort",
    name_zh="笛卡尔树排序",
    name_en="Cartesian Tree Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="线性时间构建满足「中序即原序、父节点为子树最小值」性质的笛卡尔树，"
         "再用优先队列不断弹出根并把左右子树入队，按序写回主数组。",
)
def cartesian_tree_sort(arr):
    import heapq

    n = arr.n
    if n < 2:
        return
    arr.msg("阶段一：用单调栈线性构建笛卡尔树")
    values = [arr.get(i) for i in range(n)]
    left = [-1] * n
    right = [-1] * n
    stack = []
    for i in range(n):
        last = -1
        while stack and values[stack[-1]] > values[i]:
            last = stack.pop()
        left[i] = last
        if stack:
            right[stack[-1]] = i
        stack.append(i)
    root = stack[0] if stack else -1

    arr.msg("阶段二：优先队列按序提取根节点")
    heap = []
    if root >= 0:
        heapq.heappush(heap, (values[root], root))
    out = 0
    while heap:
        _, node = heapq.heappop(heap)
        arr.set(out, values[node])
        arr.mark(out, ROLE_SORTED)
        out += 1
        if left[node] >= 0:
            heapq.heappush(heap, (values[left[node]], left[node]))
        if right[node] >= 0:
            heapq.heappush(heap, (values[right[node]], right[node]))


# ==========================================================================
# 10  砂纸选择交换排序
# ==========================================================================
@register_algo(
    algo_id="028_sandpaper_sort",
    name_zh="砂纸选择交换排序",
    name_en="Sandpaper Sort",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="二重循环固定左端点 i，只要发现 arr[i] > arr[j] 就立即交换，像砂纸"
         "反复打磨一样把所有较小元素逐步磨到左侧。",
)
def sandpaper_sort(arr):
    n = arr.n
    for i in range(n - 1):
        arr.msg(f"打磨左端 arr[{i}]")
        for j in range(i + 1, n):
            if arr.gt(i, j):
                arr.swap(i, j)
        arr.mark(i, ROLE_SORTED)


# ==========================================================================
# 11  滚动选择排序
# ==========================================================================
@register_algo(
    algo_id="029_roll_sort",
    name_zh="滚动选择排序",
    name_en="Roll Sort",
    category=CATEGORY,
    time_best="O(n^2)", time_avg="O(n^2)", time_worst="O(n^2)",
    space="O(1)", stable=False,
    desc="选择排序的滚动窗口变体：最小值扫描的起点像滚轮一样在剩余区间里循环"
         "位移，每找到一个候选就滚动着继续向右推进。",
)
def roll_sort(arr):
    n = arr.n
    if n < 2:
        return
    cursor = 0
    for i in range(n - 1):
        m = i
        span = n - i
        for t in range(span):
            j = i + ((cursor - i + t) % span)
            if j == i:
                continue            # 不与自己比较，其余 span-1 个候选必须全部覆盖
            arr.mark(j, ROLE_CURSOR)
            if arr.cmp(j, m):
                m = j
        arr.clear_marks()
        if m != i:
            arr.swap(i, m)
        arr.mark(i, ROLE_SORTED)
        cursor = m if m > i else i + 1


# ==========================================================================
# 12  双端最小-最大堆排序
# ==========================================================================
@register_algo(
    algo_id="030_min_max_heap_sort",
    name_zh="双端最小最大堆排序",
    name_en="Min-Max Heap Sort",
    category=CATEGORY,
    time_best="O(n log n)", time_avg="O(n log n)", time_worst="O(n log n)",
    space="O(n)", stable=False,
    desc="构建「奇数层为小顶、偶数层为大顶」的最小-最大堆，堆顶即全局最小值、"
         "堆顶孩子之一即全局最大值，于是可从数组两端同时向内收缩归位。",
)
def min_max_heap_sort(arr):
    n = arr.n
    if n < 2:
        return
    arr.aux_init(n)
    for i in range(n):
        arr.aux_set(i, arr.get(i))
    arr.msg("自底向上构建最小-最大堆")
    mm_build(arr, n, AUX)
    lo, hi = 0, n - 1
    size = n
    while size > 0:
        if size == 1:
            arr.set(lo, arr.aux_peek(0))
            arr.mark(lo, ROLE_SORTED)
            size -= 1
            break
        # ---- 取最小值（堆顶）----
        arr.set(lo, arr.aux_peek(0))
        arr.mark(lo, ROLE_SORTED)
        lo += 1
        arr.aux_swap(0, size - 1)
        size -= 1
        mm_sift_down(arr, 0, size, AUX)
        if size == 1:
            arr.set(lo, arr.aux_peek(0))
            arr.mark(lo, ROLE_SORTED)
            size -= 1
            break
        # ---- 取最大值（堆顶孩子中的较大者）----
        m = 1
        if size > 2 and arr.aux_cmp(1, 2):
            m = 2
        arr.set(hi, arr.aux_peek(m))
        arr.mark(hi, ROLE_SORTED)
        hi -= 1
        arr.aux_swap(m, size - 1)
        size -= 1
        mm_fix(arr, m, size, AUX)
        arr.msg(f"已归位两端：剩余堆规模 {size}")
