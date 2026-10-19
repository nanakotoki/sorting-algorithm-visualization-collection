# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— 统一数组包装器与原子操作协议。

本模块是整个系统的"心跳"：

* 定义原子指令集（CMP / CMP_VAL / SWAP / SET / FLIP / AUX_* / MARK / MSG ...）
* ``VisualArray``    —— 内置 160 种算法与外部多语言脚本共用的数组包装器
* ``Trace``          —— 紧凑列式存储的指令流（array('B') + array('i') * 2）
* ``TracePlayer``    —— 回溯状态机，支持任意步跳转 / 单步前进 / 单步后退

设计要点
--------
1. 算法只通过 ``VisualArray`` 的原子接口操作数据，因此比较次数、交换次数、
   主存写次数、数组总访问次数都能 100% 精确统计。
2. 一次运行会把全部原子操作录制成 ``Trace``；回放时按序重放即可还原任意
   中间状态（单步回溯调试）。为避免 O(n) 重放，``TracePlayer`` 每
   ``stride`` 步拍一张快照，回退时只重放最近一次快照之后的操作。
3. 指令流用列式数组存储，单条指令仅 9 字节，N=10000 的堆排序也只需几 MB。
"""

from __future__ import annotations

import sys
import threading
import time
from array import array
from typing import Callable, Dict, Iterator, List, Optional, Sequence

__all__ = [
    "OP_CMP", "OP_CMP_VAL", "OP_SWAP", "OP_SET", "OP_FLIP", "OP_AUX_INIT",
    "OP_AUX_SET", "OP_AUX_SWAP", "OP_AUX_CLEAR", "OP_MARK", "OP_CLEAR_MARKS",
    "OP_MSG", "OP_READ", "OP_AUX_READ", "OP_AUX_CMP", "OP_NAMES",
    "ROLE_PIVOT", "ROLE_BOUNDARY", "ROLE_HEAP_ROOT", "ROLE_SORTED",
    "ROLE_CURSOR", "ROLE_MAX", "ROLE_MIN",
    "AlgorithmTimeout", "Trace", "VisualArray", "TracePlayer",
    "record", "ensure_deep_recursion", "is_sorted_values",
    "SOUND_OPS", "extract_hot_events", "hot_events_window",
    "collect_notes_between",
]

# --------------------------------------------------------------------------
# 1. 原子操作码
# --------------------------------------------------------------------------
OP_CMP = 0          # CMP <i> <j>
OP_CMP_VAL = 1      # CMP_VAL <i> <val>
OP_SWAP = 2         # SWAP <i> <j>
OP_SET = 3          # SET <i> <val>
OP_FLIP = 4         # FLIP <left> <right>
OP_AUX_INIT = 5     # AUX_INIT <size>
OP_AUX_SET = 6      # AUX_SET <i> <val>
OP_AUX_SWAP = 7     # AUX_SWAP <i> <j>
OP_AUX_CLEAR = 8    # AUX_CLEAR
OP_MARK = 9         # MARK <i> <role>
OP_CLEAR_MARKS = 10  # CLEAR_MARKS
OP_MSG = 11         # MSG <text>
OP_READ = 12        # READ <i>            （读取主数组到寄存器）
OP_AUX_READ = 13    # AUX_READ <i>        （读取辅助数组到寄存器）
OP_AUX_CMP = 14     # AUX_CMP <i> <j>     （辅助数组内部比较，如堆/树结构比较）

OP_NAMES: Dict[int, str] = {
    OP_CMP: "CMP", OP_CMP_VAL: "CMP_VAL", OP_SWAP: "SWAP", OP_SET: "SET",
    OP_FLIP: "FLIP", OP_AUX_INIT: "AUX_INIT", OP_AUX_SET: "AUX_SET",
    OP_AUX_SWAP: "AUX_SWAP", OP_AUX_CLEAR: "AUX_CLEAR", OP_MARK: "MARK",
    OP_CLEAR_MARKS: "CLEAR_MARKS", OP_MSG: "MSG", OP_READ: "READ",
    OP_AUX_READ: "AUX_READ", OP_AUX_CMP: "AUX_CMP",
}

# --------------------------------------------------------------------------
# 2. 状态标记角色
# --------------------------------------------------------------------------
ROLE_PIVOT = "PIVOT"          # 霓虹紫：基准值
ROLE_BOUNDARY = "BOUNDARY"    # 电光青：区间边界
ROLE_HEAP_ROOT = "HEAP_ROOT"  # 橙色：堆顶
ROLE_SORTED = "SORTED"        # 翠绿：已就位
ROLE_CURSOR = "CURSOR"        # 亮蓝：游标 / 写指针
ROLE_MAX = "MAX"              # 品红：当前最大值
ROLE_MIN = "MIN"              # 青绿：当前最小值
#: 暗蓝灰：元素已被「搬进辅助数组」。基数 / 计数 / 桶排序的分桶阶段主数组
#: 一个字节都不变（数据全在 aux 里组装），画面会像卡住一样；这个角色用于
#: 逐元素标注「这个位置已经被消费掉了」，让主数组有一条可见的推进前沿。
ROLE_CONSUMED = "CONSUMED"

MARK_ROLES = (ROLE_PIVOT, ROLE_BOUNDARY, ROLE_HEAP_ROOT, ROLE_SORTED,
              ROLE_CURSOR, ROLE_MAX, ROLE_MIN, ROLE_CONSUMED)

# 默认录制上限：约 4M 步 ≈ 36 MB，超出即优雅截断
DEFAULT_MAX_OPS = 4_000_000


class AlgorithmTimeout(RuntimeError):
    """算法产生的原子操作超过了 ``max_ops`` 上限（例如 Bogo Sort 未收敛）。"""


# --------------------------------------------------------------------------
# 3. 指令流（紧凑列式存储）
# --------------------------------------------------------------------------
class Trace:
    """一次算法运行的完整原子指令流。"""

    __slots__ = ("kinds", "aa", "bb", "ss", "n_ops", "truncated", "elapsed")

    def __init__(self) -> None:
        self.kinds = array("B")   # 操作码
        self.aa = array("i")      # 第一参数
        self.bb = array("i")      # 第二参数 / 数值
        self.ss: Dict[int, str] = {}   # 仅 MARK / MSG 使用的稀疏字符串槽
        self.n_ops = 0
        self.truncated = False    # 是否因超出上限被截断
        self.elapsed = 0.0        # 算法本身的纯耗时（秒）

    # -- 构造 --------------------------------------------------------------
    def add(self, kind: int, a: int = 0, b: int = 0, s: Optional[str] = None) -> None:
        self.kinds.append(kind)
        self.aa.append(int(a))
        self.bb.append(int(b))
        if s is not None:
            self.ss[self.n_ops] = s
        self.n_ops += 1

    # -- 查询 --------------------------------------------------------------
    def __len__(self) -> int:
        return self.n_ops

    def op(self, idx: int):
        """返回第 idx 条指令的 ``(kind, a, b, s)`` 四元组。"""
        return self.kinds[idx], self.aa[idx], self.bb[idx], self.ss.get(idx)

    def byte_size(self) -> int:
        return len(self.kinds) + 4 * len(self.aa) + 4 * len(self.bb)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Trace ops={self.n_ops} truncated={self.truncated} bytes={self.byte_size()}>"


# --------------------------------------------------------------------------
# 4. VisualArray —— 算法面向的唯一数据接口
# --------------------------------------------------------------------------
class VisualArray:
    """统一数组包装器：所有原子操作同时完成"真实数据修改"与"指令录制"。"""

    __slots__ = ("data", "n", "trace", "aux", "aux_size", "max_ops", "_warned")

    def __init__(self, values: Sequence[int], trace: Optional[Trace] = None,
                 max_ops: int = DEFAULT_MAX_OPS) -> None:
        self.data: List[int] = [int(v) for v in values]
        self.n = len(self.data)
        self.trace: Trace = trace if trace is not None else Trace()
        self.aux: List[int] = []
        self.aux_size = 0
        self.max_ops = max_ops
        self._warned = False

    # ---- 内部：发出指令 --------------------------------------------------
    def _emit(self, kind: int, a: int = 0, b: int = 0, s: Optional[str] = None) -> None:
        t = self.trace
        t.add(kind, a, b, s)
        if t.n_ops >= self.max_ops:
            raise AlgorithmTimeout(
                f"已达最大步数上限 {self.max_ops}，算法被安全截断")

    # ---- 结构信息 --------------------------------------------------------
    def size(self) -> int:
        return self.n

    def __len__(self) -> int:
        return self.n

    def values(self) -> List[int]:
        """当前主数组快照（不产生指令）。"""
        return list(self.data)

    # ---- 主数组原子操作 --------------------------------------------------
    def peek(self, i: int) -> int:
        """纯读取，不计入统计（用于结构性读取，避免指令流膨胀）。"""
        return self.data[i]

    def get(self, i: int) -> int:
        """读取到寄存器：计 1 次数组访问。"""
        self._emit(OP_READ, i)
        return self.data[i]

    def cmp(self, i: int, j: int) -> bool:
        """``arr[i] < arr[j]``：黄灯高亮，比较 +1，读取 +2，访问 +2。"""
        self._emit(OP_CMP, i, j)
        return self.data[i] < self.data[j]

    def cmp_val(self, i: int, val: int) -> bool:
        """``arr[i] < val``（val 为寄存器值）：比较 +1，读取 +1，访问 +1。"""
        self._emit(OP_CMP_VAL, i, val)
        return self.data[i] < val

    def gt(self, i: int, j: int) -> bool:
        """**严格**大于：``arr[i] > arr[j]``。

        与 ``cmp(i, j)`` 共用 CMP 指令（参数交换即可），但语义严格，
        因此对相等元素不会触发无意义的交换——这是"无交换即有序"类算法
        （奇偶排序、梳排序、地精排序）能够正确收敛的关键。
        """
        return self.cmp(j, i)

    def gt_val(self, i: int, val: int) -> bool:
        """**严格**大于：``arr[i] > val``（val 为寄存器值），复用 CMP_VAL 指令。"""
        self._emit(OP_CMP_VAL, i, val)
        return self.data[i] > val

    def cmp_gt(self, i: int, j: int) -> bool:
        """``arr[i] >= arr[j]`` 的便捷写法（非严格）。"""
        return not self.cmp(i, j)

    def swap(self, i: int, j: int) -> None:
        """交换：珊瑚红高亮，交换 +1，主存写 +2，总访问 +4。"""
        if i == j:
            return
        self._emit(OP_SWAP, i, j)
        d = self.data
        d[i], d[j] = d[j], d[i]

    def set(self, i: int, val: int) -> None:
        """覆写：珊瑚红高亮，主存写 +1，总访问 +1。"""
        self._emit(OP_SET, i, int(val))
        self.data[i] = int(val)

    def flip(self, left: int, right: int) -> None:
        """区间 [left, right] 原地对称翻转（煎饼排序 / 块旋转归并）。"""
        if left >= right:
            return
        self._emit(OP_FLIP, left, right)
        self.data[left:right + 1] = self.data[left:right + 1][::-1]

    # 语义别名，便于各算法书写
    reverse_range = flip
    rotate_flip = flip

    # ---- 辅助数组原子操作 ------------------------------------------------
    def aux_init(self, size: int) -> None:
        """初始化辅助数组（画布自动切换为上下分屏）。"""
        self._emit(OP_AUX_INIT, size)
        self.aux = [0] * size
        self.aux_size = size

    def aux_peek(self, i: int) -> int:
        return self.aux[i]

    def aux_get(self, i: int) -> int:
        self._emit(OP_AUX_READ, i)
        return self.aux[i]

    def aux_set(self, i: int, val: int) -> None:
        """向辅助数组写入：青色高亮，辅助写 +1。"""
        self._emit(OP_AUX_SET, i, int(val))
        self.aux[i] = int(val)

    def aux_swap(self, i: int, j: int) -> None:
        if i == j:
            return
        self._emit(OP_AUX_SWAP, i, j)
        self.aux[i], self.aux[j] = self.aux[j], self.aux[i]

    def aux_cmp(self, i: int, j: int) -> bool:
        """辅助数组内部比较 ``aux[i] < aux[j]``（堆 / 树结构排序统计比较次数）。"""
        self._emit(OP_AUX_CMP, i, j)
        return self.aux[i] < self.aux[j]

    def aux_clear(self) -> None:
        self._emit(OP_AUX_CLEAR)
        self.aux = []
        self.aux_size = 0

    # ---- 标记与解说 ------------------------------------------------------
    def mark(self, i: int, role: str) -> None:
        self._emit(OP_MARK, i, 0, role)

    def clear_marks(self) -> None:
        self._emit(OP_CLEAR_MARKS)

    def msg(self, text: str) -> None:
        self._emit(OP_MSG, 0, 0, str(text))


# --------------------------------------------------------------------------
# 5. 录制入口
# --------------------------------------------------------------------------
def record(func: Callable[[VisualArray], None], values: Sequence[int],
           max_ops: int = DEFAULT_MAX_OPS) -> Trace:
    """执行 ``func`` 并返回其完整指令流。"""
    tr = Trace()
    va = VisualArray(values, tr, max_ops=max_ops)
    t0 = time.perf_counter()
    try:
        func(va)
    except AlgorithmTimeout:
        tr.truncated = True
    finally:
        tr.elapsed = time.perf_counter() - t0
    return tr


_recursion_ready = False


def ensure_deep_recursion(depth: int = 300_000) -> None:
    """递归型算法（快排 / 归并 / 递归圆圈排序）需要更深的调用栈。"""
    global _recursion_ready
    if _recursion_ready:
        return
    try:
        sys.setrecursionlimit(depth)
    except Exception:  # pragma: no cover
        pass
    try:
        threading.stack_size(64 * 1024 * 1024)
    except Exception:  # pragma: no cover
        pass
    _recursion_ready = True


def is_sorted_values(values: Sequence[int]) -> bool:
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))


# --------------------------------------------------------------------------
# 6. TracePlayer —— 回溯状态机
# --------------------------------------------------------------------------
class TracePlayer:
    """按序重放指令流，支持 seek / step(+1) / step(-1)。"""

    __slots__ = ("trace", "initial", "stride", "_snaps", "_snap_bytes",
                 "data", "aux", "aux_active", "marks", "msg", "step",
                 "cmp", "swaps", "main_writes", "aux_writes", "reads",
                 "aux_reads", "accesses")

    def __init__(self, trace: Trace, initial: Sequence[int],
                 max_snapshots: int = 200) -> None:
        self.trace = trace
        self.initial = [int(v) for v in initial]
        self.stride = max(256, trace.n_ops // max_snapshots) if trace.n_ops else 256
        self._snaps: Dict[int, tuple] = {}
        self._snap_bytes = 0
        self._reset_state()
        self._snapshot()

    # ---- 状态重置 --------------------------------------------------------
    def _reset_state(self) -> None:
        self.data: List[int] = list(self.initial)
        self.aux: List[int] = []
        self.aux_active = False
        self.marks: Dict[str, set] = {}
        self.msg = ""
        self.step = 0
        self.cmp = 0
        self.swaps = 0
        self.main_writes = 0
        self.aux_writes = 0
        self.reads = 0
        self.aux_reads = 0
        self.accesses = 0

    # ---- 快照 ------------------------------------------------------------
    def _snapshot(self) -> None:
        if self.step in self._snaps:
            return
        snap = (list(self.data), list(self.aux), {k: set(v) for k, v in self.marks.items()},
                self.msg, self.aux_active,
                (self.cmp, self.swaps, self.main_writes, self.aux_writes,
                 self.reads, self.aux_reads, self.accesses))
        self._snaps[self.step] = snap
        self._snap_bytes += (len(self.data) + len(self.aux)) * 8

    def _restore(self, step: int) -> None:
        data, aux, marks, msg, aux_active, counters = self._snaps[step]
        self.data = list(data)
        self.aux = list(aux)
        self.marks = {k: set(v) for k, v in marks.items()}
        self.msg = msg
        self.aux_active = aux_active
        (self.cmp, self.swaps, self.main_writes, self.aux_writes,
         self.reads, self.aux_reads, self.accesses) = counters
        self.step = step

    # ---- 单步执行 --------------------------------------------------------
    def _apply(self, idx: int) -> None:
        tr = self.trace
        kind = tr.kinds[idx]
        a = tr.aa[idx]
        b = tr.bb[idx]

        if kind == OP_CMP:
            self.cmp += 1
            self.reads += 2
            self.accesses += 2
        elif kind == OP_CMP_VAL:
            self.cmp += 1
            self.reads += 1
            self.accesses += 1
        elif kind == OP_SWAP:
            d = self.data
            d[a], d[b] = d[b], d[a]
            self.swaps += 1
            self.main_writes += 2
            self.accesses += 4
        elif kind == OP_SET:
            self.data[a] = b
            self.main_writes += 1
            self.accesses += 1
        elif kind == OP_FLIP:
            self.data[a:b + 1] = self.data[a:b + 1][::-1]
            span = b - a + 1
            self.swaps += span // 2
            self.main_writes += span
            self.accesses += 2 * span
        elif kind == OP_READ:
            self.reads += 1
            self.accesses += 1
        elif kind == OP_AUX_INIT:
            self.aux = [0] * a
            self.aux_active = True
        elif kind == OP_AUX_SET:
            self.aux[a] = b
            self.aux_writes += 1
        elif kind == OP_AUX_SWAP:
            self.aux[a], self.aux[b] = self.aux[b], self.aux[a]
            self.aux_writes += 2
        elif kind == OP_AUX_READ:
            self.aux_reads += 1
        elif kind == OP_AUX_CMP:
            self.aux_reads += 2
            self.cmp += 1
        elif kind == OP_AUX_CLEAR:
            self.aux = []
            self.aux_active = False
        elif kind == OP_MARK:
            self.marks.setdefault(tr.ss.get(idx, ROLE_CURSOR), set()).add(a)
        elif kind == OP_CLEAR_MARKS:
            self.marks = {}
        elif kind == OP_MSG:
            self.msg = tr.ss.get(idx, "")

    # ---- 公开接口 --------------------------------------------------------
    @property
    def total(self) -> int:
        return self.trace.n_ops

    @property
    def progress(self) -> float:
        return 1.0 if not self.trace.n_ops else self.step / self.trace.n_ops

    def seek(self, target: int) -> None:
        """跳转到指定步数（支持向前与向后）。"""
        total = self.trace.n_ops
        if target < 0:
            target = 0
        elif target > total:
            target = total
        if target < self.step:
            base = (target // self.stride) * self.stride
            while base > 0 and base not in self._snaps:
                base -= self.stride
            if base in self._snaps:
                self._restore(base)
            else:
                self._reset_state()
        while self.step < target:
            self._apply(self.step)
            self.step += 1
            if self.step % self.stride == 0:
                self._snapshot()

    def advance(self, count: int = 1) -> int:
        """前进 ``count`` 步，返回实际前进的步数。"""
        before = self.step
        self.seek(min(self.step + count, self.trace.n_ops))
        return self.step - before

    def step_back(self, count: int = 1) -> int:
        before = self.step
        self.seek(max(self.step - count, 0))
        return before - self.step

    def at_end(self) -> bool:
        return self.step >= self.trace.n_ops

    def run_to_end(self) -> None:
        self.seek(self.trace.n_ops)

    def snapshot_bytes(self) -> int:
        return self._snap_bytes

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (f"<TracePlayer step={self.step}/{self.trace.n_ops} "
                f"cmp={self.cmp} swap={self.swaps}>")


# --------------------------------------------------------------------------
# 7. 指令流 → 视觉 / 听觉事件（画布与视频导出器共用的纯函数）
# --------------------------------------------------------------------------
#: 会产生「响声」的指令类型（其余只是标记 / 解说，不发声）
SOUND_OPS = (OP_CMP, OP_CMP_VAL, OP_SWAP, OP_SET, OP_READ, OP_FLIP)

#: 高亮角色优先级：后出现的角色会覆盖先出现的
_HOT_MAIN_KINDS = {
    OP_CMP: "cmp", OP_CMP_VAL: "cmp", OP_READ: "read",
    OP_SWAP: "swap", OP_SET: "set",
}
_HOT_AUX_KINDS = {
    OP_AUX_SET: "aux_set", OP_AUX_SWAP: "aux_swap",
    OP_AUX_READ: "aux_read", OP_AUX_CMP: "aux_cmp",
}


def _apply_hot_at(trace: Trace, idx: int, hot_main: Dict[int, str],
                  hot_aux: Dict[int, str], limit: int) -> None:
    """把第 ``idx`` 条指令的高亮写进两个字典（内部工具）。"""
    kind = trace.kinds[idx]
    a = trace.aa[idx]
    b = trace.bb[idx]

    main_kind = _HOT_MAIN_KINDS.get(kind)
    if main_kind is not None:
        hot_main[a] = main_kind
        if kind in (OP_CMP, OP_SWAP):
            hot_main[b] = main_kind
        return
    if kind == OP_FLIP:
        span = b - a + 1
        # 统一用 "flip" 这一种高亮角色，而不是复用 "swap"：
        # 煎饼 / 准煎饼这类算法里翻转是唯一的写操作，若与两两交换共用同一个
        # 珊瑚红，观众分不清「动了两根」还是「翻了整段」。渲染层还会为
        # "flip" 单独铺一条区间底色带（见 BarsRenderer._paint_flip_band）。
        if span <= limit:                # 短区间整段点亮
            for i in range(a, b + 1):
                hot_main[i] = "flip"
        else:                            # 超长区间只点亮两端
            hot_main[a] = "flip"
            hot_main[b] = "flip"
        return
    aux_kind = _HOT_AUX_KINDS.get(kind)
    if aux_kind is not None:
        hot_aux[a] = aux_kind
        if kind in (OP_AUX_SWAP, OP_AUX_CMP):
            hot_aux[b] = aux_kind


def extract_hot_events(trace: Trace, step: int, limit: int = 256
                       ) -> "tuple[Dict[int, str], Dict[int, str]]":
    """读取「刚执行完的那条指令」，返回 ``(主数组高亮, 辅助数组高亮)``。

    :class:`TracePlayer` 在 ``step`` 步之后状态即为「**前 step 条**指令已生效」，
    因此「当前指令」是第 ``step - 1`` 条。
    """
    hot_main: Dict[int, str] = {}
    hot_aux: Dict[int, str] = {}
    if step <= 0 or trace.n_ops == 0:
        return hot_main, hot_aux
    _apply_hot_at(trace, min(step, trace.n_ops) - 1, hot_main, hot_aux, limit)
    return hot_main, hot_aux


def hot_events_window(trace: Trace, lo: int, hi: int, limit: int = 256,
                      window: int = 16
                      ) -> "tuple[Dict[int, str], Dict[int, str]]":
    """合并 ``[lo, hi)`` 区间内**最近 ``window`` 条**指令的高亮。

    视频导出时一帧可能推进上万条原子操作，只取「最后一条」会让高亮随机闪
    烁、完全看不出在干什么。聚合最近若干条指令后，高速档画面会呈现成
    「一条持续流动的活动轨迹」，既好看又真实。
    """
    hot_main: Dict[int, str] = {}
    hot_aux: Dict[int, str] = {}
    hi = max(0, min(int(hi), trace.n_ops))
    if hi <= 0:
        return hot_main, hot_aux
    span = max(1, int(window))
    lo = max(0, max(int(lo), hi - span))
    for idx in range(lo, hi):
        _apply_hot_at(trace, idx, hot_main, hot_aux, limit)
    return hot_main, hot_aux


def collect_notes_between(trace: Trace, i0: int, i1: int, values: Sequence[int],
                          limit: int = 256) -> List[int]:
    """把 ``[i0, i1)`` 这一批指令涉及到的元素值抽出来，用于发声。

    极速档一帧可能推进上千步，因此超过 ``limit`` 时**按位置均匀抽样**，
    既保留音阶上行的听感，又不会把音频糊成噪音。
    """
    n_ops = trace.n_ops
    i0 = max(0, min(int(i0), n_ops))
    i1 = max(i0, min(int(i1), n_ops))
    span = i1 - i0
    if span <= 0:
        return []
    step = 1 if span <= limit else span // limit
    out: List[int] = []
    n = len(values)
    for k in range(i0, i1, step):
        if trace.kinds[k] in SOUND_OPS:
            i = trace.aa[k]
            if 0 <= i < n:
                out.append(values[i])
    return out
