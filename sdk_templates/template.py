#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— Python 自定义算法模板（单文件）。

运行方式（由主程序自动完成，也可手工验证）：

    python template.py < input.txt

其中 input.txt 形如::

    8
    5 3 9 1 7 2 8 4

协议（每行一条指令，写入 stdout 后必须刷新）：

    CMP i j          比较 arr[i] 与 arr[j]（返回 arr[i] < arr[j]，比较 +1，读取 +2）
    CMP_VAL i val    比较 arr[i] 与寄存器值 val（返回 arr[i] < val，比较 +1，读取 +1）
    READ i           读取 arr[i] 到寄存器（读取 +1）
    SWAP i j         交换 arr[i] 与 arr[j]（交换 +1，写入 +2，访问 +4）
    SET i val        令 arr[i] = val（写入 +1，访问 +1）
    FLIP l r         原地翻转区间 [l, r]（交换 +(r-l+1)/2）
    AUX_INIT size    初始化辅助数组（画布自动切为上下分屏）
    AUX_SET i val    写作 aux[i] = val（辅助写入 +1）
    AUX_GET i        读取 aux[i]（辅助读取 +1）
    AUX_SWAP i j     交换 aux[i] 与 aux[j]（辅助写入 +2）
    AUX_CMP i j      比较 aux[i] 与 aux[j]（比较 +1）
    AUX_CLEAR        销毁辅助数组并收起分屏
    MARK i ROLE      标记索引（PIVOT / BOUNDARY / HEAP_ROOT / SORTED / CURSOR / MIN / MAX）
    CLEAR_MARKS      清除全部临时标记
    MSG text...      更新看板上的实时解说词（可含空格）

只写你自己的排序逻辑即可，所有可视化、计数器与音效都由指令流自动驱动。

**三种取数写法，任选其一**（推荐第一种，语义最明确）：

    arr.cmp(i, j)        比较 arr[i] < arr[j]          → CMP i j
    arr.gt(i, j)         比较 arr[i] > arr[j]          → CMP j i
    arr[i] < arr[j]      下标语法，比较时自动记录      → CMP i j（完全等价）

    arr[i]               惰性代理：取值本身不产生指令
    arr.get(i)           取值并记 1 次数组访问          → READ i

``arr[i]`` 返回的是**惰性代理**而不是普通 int，这带来两个必须知道的行为：

1. **只有比较会被记录**。``if arr[i] < arr[j]`` 正常出画面；但
   ``a = int(arr[i]); b = int(arr[j]); if a < b`` 里的 ``<`` 发生在解释器内部，
   主程序收不到任何信号，画面会一动不动 —— 这是最隐蔽的坑。
   直接写 ``a = arr[i]; b = arr[j]; if a < b`` 则是安全的（a、b 仍是代理）。
2. **它永远读数组的当前值**。``x = arr[i]`` 之后做了 swap，``x`` 拿到的
   是新值；要冻结此刻的数值，必须 ``x = int(arr[i])`` 显式转换。
"""

import sys

sys.setrecursionlimit(1 << 20)

# 管道通信一律走 UTF-8。Windows 上 Python 默认按本地代码页（GBK）编码 stdout，
# 只要 MSG 里出现「✓」这类非 GBK 字符就会直接 UnicodeEncodeError 崩掉，
# 因此这里主动把标准流切到 UTF-8（主程序侧同样以 UTF-8 解码）。
for _stream in ("stdout", "stderr", "stdin"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ==========================================================================
# 1. 统一数组包装器（无需修改）
# ==========================================================================
class _Cell:
    """``arr[i]`` 的惰性代理 —— **参与比较时才向指令流写一条 CMP**。

    存在的唯一理由：让 ``arr[i] < arr[j]`` 这种最自然的写法也能被可视化。

    如果 ``__getitem__`` 直接返回 int，比较就发生在 Python 解释器内部，
    主程序一个字节也收不到 —— 用户的排序会「跑完但实时预览只有一步」。
    这正是本项目早期最常见的踩坑点：语法完全正确、结果也对，只是没画面。

    代理自身**不产生任何指令**（取值是免费的），只有六个比较运算符
    会发 CMP / CMP_VAL，与 ``arr.cmp(i, j)`` 产出的指令逐字节等价。
    """

    __slots__ = ("_arr", "_i")

    def __init__(self, arr, i):
        self._arr = arr
        self._i = i

    # ---- 比较：唯一会写指令的地方 ----------------------------------------
    def __lt__(self, other):
        return self._arr._cmp_cell(self._i, other, "<")

    def __gt__(self, other):
        return self._arr._cmp_cell(self._i, other, ">")

    def __le__(self, other):
        return self._arr._cmp_cell(self._i, other, "<=")

    def __ge__(self, other):
        return self._arr._cmp_cell(self._i, other, ">=")

    def __eq__(self, other):
        return self._arr._cmp_cell(self._i, other, "==")

    def __ne__(self, other):
        return self._arr._cmp_cell(self._i, other, "!=")

    def __hash__(self):
        return hash(self._arr.data[self._i])

    # ---- 取值语义：算术一律降级为数值，不写指令 --------------------------
    def __int__(self):
        return self._arr.data[self._i]

    __index__ = __int__

    def __float__(self):
        return float(self._arr.data[self._i])

    def __bool__(self):
        return bool(self._arr.data[self._i])

    def __repr__(self):
        return repr(self._arr.data[self._i])

    def __str__(self):
        return str(self._arr.data[self._i])

    def __add__(self, o):
        return self._arr.data[self._i] + _as_num(o)

    def __radd__(self, o):
        return _as_num(o) + self._arr.data[self._i]

    def __sub__(self, o):
        return self._arr.data[self._i] - _as_num(o)

    def __rsub__(self, o):
        return _as_num(o) - self._arr.data[self._i]

    def __mul__(self, o):
        return self._arr.data[self._i] * _as_num(o)

    def __rmul__(self, o):
        return _as_num(o) * self._arr.data[self._i]

    def __floordiv__(self, o):
        return self._arr.data[self._i] // _as_num(o)

    def __truediv__(self, o):
        return self._arr.data[self._i] / _as_num(o)

    def __mod__(self, o):
        return self._arr.data[self._i] % _as_num(o)

    def __neg__(self):
        return -self._arr.data[self._i]

    def __abs__(self):
        return abs(self._arr.data[self._i])


def _as_num(x):
    """把 ``_Cell`` 或任意标量压成数值，供算术运算使用。"""
    return int(x) if isinstance(x, _Cell) else x


class VisualArray:
    """主程序注入的数组包装器：每次读写都会向 stdout 打印一条指令。"""

    __slots__ = ("data", "n", "_aux")

    def __init__(self, values):
        self.data = [int(v) for v in values]
        self.n = len(self.data)
        self._aux = []

    # ---- 内部工具 --------------------------------------------------------
    @staticmethod
    def _emit(*parts):
        sys.stdout.write(" ".join(str(p) for p in parts))
        sys.stdout.write("\n")
        sys.stdout.flush()          # 逐行刷新：主程序才能实时渲染

    def _check(self, i):
        i = int(i)
        if i < 0 or i >= self.n:
            raise IndexError(f"索引越界: {i}（数组长度 {self.n}）")
        return i

    # ---- 结构与读取 ------------------------------------------------------
    def size(self):
        return self.n

    def __len__(self):
        return self.n

    def peek(self, i):
        """纯读取，不产生指令、不计统计（仅在必须知道数值时使用）。"""
        return self.data[self._check(i)]

    def get(self, i):
        """读取到寄存器：计 1 次数组访问。"""
        i = self._check(i)
        self._emit("READ", i)
        return self.data[i]

    # ---- 下标语法糖（arr[i] / arr[i] = v）--------------------------------
    def __getitem__(self, i):
        """``arr[i]`` → :class:`_Cell` 惰性代理。

        这里**故意不发 READ**：``arr[i] < arr[j]`` 最终只产生一条 CMP，
        而主程序解析 CMP 时会自动记 2 次读取 —— 与 ``arr.cmp(i, j)``
        的统计逐项相同。若此处再发 READ，读取数会翻倍到 4 次，
        看板上的 Total Accesses 就虚高了。
        """
        return _Cell(self, self._check(i))

    def __setitem__(self, i, val):
        """``arr[i] = val`` 等价于 ``arr.set(i, val)``（珊瑚红高亮）。"""
        self.set(i, val)

    # ---- 比较 ------------------------------------------------------------
    #: 六个比较运算符 → 判定函数（供 _Cell 的魔术方法分派）
    _CMP_FN = {
        "<": lambda a, b: a < b,
        ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

    def _cmp_cell(self, i, other, op):
        """``_Cell`` 的比较落点：先发一条 CMP / CMP_VAL，再返回布尔结果。"""
        fn = self._CMP_FN[op]
        if isinstance(other, _Cell) and other._arr is self:
            j = other._i
            # CMP 指令的语义固定是「arr[a] < arr[b] 吗」。用户写
            # arr[i] > arr[j] 时把参数倒过来发（CMP j i），两根黄灯在
            # 屏上的前后顺序才和表达式一致 —— 与 gt() 的处理方式相同。
            if op in (">", ">="):
                self._emit("CMP", j, i)
            else:
                self._emit("CMP", i, j)
            return fn(self.data[i], self.data[j])
        val = _as_num(other)
        self._emit("CMP_VAL", i, int(val))
        return fn(self.data[i], val)

    def cmp(self, i, j):
        """arr[i] < arr[j]（黄灯高亮）。"""
        i, j = self._check(i), self._check(j)
        self._emit("CMP", i, j)
        return self.data[i] < self.data[j]

    def gt(self, i, j):
        """arr[i] > arr[j]（严格大于，相等元素不会误判）。"""
        i, j = self._check(i), self._check(j)
        self._emit("CMP", j, i)
        return self.data[i] > self.data[j]

    def cmp_val(self, i, val):
        """arr[i] < val（val 为寄存器中的值）。"""
        i = self._check(i)
        self._emit("CMP_VAL", i, int(val))
        return self.data[i] < val

    def gt_val(self, i, val):
        """arr[i] > val。"""
        i = self._check(i)
        self._emit("CMP_VAL", i, int(val))
        return self.data[i] > val

    # ---- 写入 ------------------------------------------------------------
    def swap(self, i, j):
        """交换两个元素（珊瑚红高亮）。"""
        i, j = self._check(i), self._check(j)
        if i == j:
            return
        self._emit("SWAP", i, j)
        self.data[i], self.data[j] = self.data[j], self.data[i]

    def set(self, i, val):
        """覆写 arr[i] = val（珊瑚红高亮）。"""
        i = self._check(i)
        val = int(val)
        self._emit("SET", i, val)
        self.data[i] = val

    def flip(self, left, right):
        """原地对称翻转区间 [left, right]（煎饼排序 / 块旋转）。"""
        left, right = self._check(left), self._check(right)
        if left >= right:
            return
        self._emit("FLIP", left, right)
        self.data[left:right + 1] = self.data[left:right + 1][::-1]

    # ---- 辅助数组 --------------------------------------------------------
    def aux_init(self, size):
        self._emit("AUX_INIT", int(size))
        self._aux = [0] * int(size)

    def aux_set(self, i, val):
        self._emit("AUX_SET", int(i), int(val))
        self._aux[int(i)] = int(val)

    def aux_get(self, i):
        i = int(i)
        self._emit("AUX_GET", i)
        return self._aux[i]

    def aux_swap(self, i, j):
        i, j = int(i), int(j)
        if i == j:
            return
        self._emit("AUX_SWAP", i, j)
        self._aux[i], self._aux[j] = self._aux[j], self._aux[i]

    def aux_cmp(self, i, j):
        i, j = int(i), int(j)
        self._emit("AUX_CMP", i, j)
        return self._aux[i] < self._aux[j]

    def aux_clear(self):
        self._emit("AUX_CLEAR")
        self._aux = []

    # ---- 标记与解说 ------------------------------------------------------
    def mark(self, i, role):
        self._emit("MARK", self._check(i), str(role).upper())

    def clear_marks(self):
        self._emit("CLEAR_MARKS")

    def msg(self, text):
        self._emit("MSG", text)

    # ---- 自检 ------------------------------------------------------------
    def is_sorted(self):
        return all(self.data[i] <= self.data[i + 1] for i in range(self.n - 1))


# ==========================================================================
# 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
# ==========================================================================
def my_custom_sort(arr, n):
    """示例：插入排序。请替换成你自己的算法。"""
    if n < 2:
        return
    for i in range(1, n):
        j = i
        arr.mark(j, "CURSOR")
        while j > 0 and arr.gt(j - 1, j):     # arr[j-1] > arr[j] 才交换
            arr.swap(j - 1, j)
            j -= 1
        arr.mark(j, "SORTED")
    arr.clear_marks()


# ==========================================================================
# 3. 输入输出（无需修改）
# ==========================================================================
def read_input():
    tokens = sys.stdin.read().split()
    if not tokens:
        return 0, []
    n = int(tokens[0])
    values = [int(t) for t in tokens[1:1 + n]]
    if len(values) != n:
        raise ValueError(f"输入的数组长度 {len(values)} 与声明的 N={n} 不符")
    return n, values


def main():
    try:
        n, values = read_input()
    except Exception as exc:
        sys.stderr.write(f"输入解析失败: {exc}\n")
        return 2

    arr = VisualArray(values)
    try:
        my_custom_sort(arr, n)
    except Exception as exc:
        arr.msg(f"自定义算法异常：{type(exc).__name__}: {exc}")
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1

    if arr.is_sorted():
        arr.msg("自定义算法完成：数组已有序 ✓")
    else:
        arr.msg("自定义算法结束：数组尚未有序 ✗")
        sys.stderr.write("警告：算法返回时数组并未有序\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
