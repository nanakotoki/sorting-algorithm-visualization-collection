# -*- coding: utf-8 -*-
"""NumPy 向量化渲染内核与 Qt 画布控件。

设计要点（对应规范书 5.1 / 5.2 两节）
-------------------------------------
**渲染内核与 Qt 完全解耦**：:class:`StyleRenderer` 及其 5 个子类只依赖 NumPy，
输入 :class:`VizFrame`、输出 ``(H, W, 3) uint8`` 的 RGB 位图。这样同一套渲染
代码既能驱动屏幕上的 :class:`CanvasWidget`，也能被 Batch 6 的离屏视频导出器
直接逐帧调用，真正做到「所见即所得」。

**严禁逐根柱子调用 ``drawRect``**。所有几何计算都用 NumPy 一次性算完全部
屏幕坐标，再通过 **布尔掩码批量赋值**写进 RGB 缓冲：

* 稀疏模式（``n ≤ 画布宽``）：用 ``searchsorted`` 求出每一屏幕列归属哪根柱子，
  再算一次 ``rows >= top_of_column`` 的二维掩码，整块填色；
* 稠密模式（``n > 画布宽``，例如 N=10000）：用 ``np.maximum.reduceat`` 把每根
  柱子上的元素**按屏幕列聚合取最大值**，柱宽自然退化为 1 像素，依然只做
  常数次 NumPy 运算，N=10,000 也能稳定 60 FPS。

极坐标样式（圆环）为避免每帧做 ``atan2``，把「每像素的角度与半径」按画布
尺寸**预计算并缓存**，每帧只剩除法与比较。

12 种几何样式
-------------
**基础三式**（保留）

``bars``          经典垂直柱状图（自适应间隙与宽度）
``wheel``         径向花瓣环（角度 = 索引，瓣长 = 数值）
``scatter``       峰谷折线图（乱序是剧烈起伏的山脊）

**核心特色四式**（Instructions2 第一组）

``mirror``        对称声波图（以水平中轴为镜像面）
``disparity``     极坐标偏差收缩环（半径 = 与目标位置的误差）
``pyramid``       居中金字塔堆叠（水平横条沿中轴左右对称）
``residual``      残差位移火柴图（到理想对角线的垂直偏差）

**高概念创意五式**（Instructions2 第二组）

``waterfall``     时空瀑布流（横轴索引 × 纵轴时间的历史轨迹）
``loom``          平行双轨织布机（每根连线 = 一对逆序关系）
``nautilus``      极坐标鹦鹉螺放射柱（由内环向外发散的频谱）
``dreamcatcher``  圆环错位捕梦网（当前角 → 目标角的弦网）
``tree``          隐式完全二叉树（父 ⌊(i-1)/2⌋ 的堆拓扑）

次世代高画质六式（Instruction3）
-------------------------------
前 12 种走的是 **NumPy 光栅管线**（批量算坐标 + 布尔掩码整块写缓冲），
快到可以说「与 N 无关」，但画不了抗锯齿曲线、渐变与半透明叠加。
下面 6 种改走 **QPainter 矢量管线**（见 :class:`VectorRenderer`）：

``slice``         高清图像切片还原（第 i 格显示第 rank_i 号竖切片，故障艺术）
``arcs``          霓虹拱桥光弧（弧的跨度 = 元素偏离目标位置的距离）
``helix3d``       3D 全息双螺旋（透视投影 + 画家算法 + 三面立体棱柱）
``aurora``        流体极光丝带（Catmull-Rom 转三次贝塞尔，加色混合）
``orbs``          高光玻璃球与抛物线飞跃（四段径向渐变 + 彗星尾迹）
``crystal``       低多边形晶格网（顶点偏移 = 当前名次与有序名次之差）

两条管线共用 :class:`StyleRenderer.render` 这一个出口，界面与离屏视频
导出器对此完全无感 —— 这也是「屏上所见 = 导出所得」得以成立的原因。

全局画质管线（四条，对所有样式生效）
----------------------------------
1. **抗锯齿 / 平滑矢量变换**：``CanvasWidget.paintEvent`` 与每个矢量渲染器
   都会打开 ``Antialiasing | TextAntialiasing | SmoothPixmapTransform``。
2. **动态余晖残影**：:meth:`StyleRenderer._compose_trail`，1/4 分辨率累积层，
   每帧 ×215/255 衰减，高光拖出 8~12 帧光轨。
3. **霓虹辉光叠加**：一律用 ``CompositionMode_Plus`` + 「宽画笔低 alpha 的
   Bloom 打底、细画笔高 alpha 的白芯收边」双层画法。
4. **黑曜石镜面倒影**：:meth:`StyleRenderer._reflect_floor`，圆形视图把
   主绘图区压到上方 78%，底部 22% 做纵向渐隐的倒影 + 地平线辉光。

色彩编码严格遵循规范书：深空黑背景、柠檬黄比较、珊瑚红交换、
霓虹紫 pivot、电光青 boundary、翠绿已就位。

性能约定
--------
凡「每元素一根线」的样式（``loom`` / ``dreamcatcher`` / ``residual``）
以及节点密集的 ``tree``，在 ``N > 512`` 时启用**均匀步长降采样**，并强制
保留所有正处于 ``CMP / SWAP / PIVOT`` 高亮状态的索引 —— 保证 N=10,000 时
既能稳在 60 FPS，又不会把「正在发生的那一次操作」给抽掉。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QSizePolicy, QWidget

__all__ = [
    "PALETTES", "STYLES", "HOT_MARKER_STYLES", "VizFrame", "StyleRenderer",
    "BarsRenderer", "WheelRenderer", "ScatterRenderer", "MirrorRenderer",
    "DisparityRenderer", "PyramidRenderer", "ResidualRenderer",
    "WaterfallRenderer", "LoomRenderer", "NautilusRenderer",
    "DreamcatcherRenderer", "TreeRenderer",
    "VectorRenderer", "SliceRenderer", "ArcRenderer", "HelixRenderer",
    "AuroraRenderer", "OrbRenderer", "CrystalRenderer",
    "make_renderer", "CanvasWidget", "render_frame_to_array", "palette_for",
    "set_slice_source", "slice_source_name", "reset_slice_source",
]

# --------------------------------------------------------------------------
# 1. 色彩编码系统（规范书 5.1）
# --------------------------------------------------------------------------
RGB = Tuple[int, int, int]

C_BG: RGB = (0x0D, 0x0E, 0x12)          # 深空黑
C_GRID: RGB = (0x1A, 0x1D, 0x24)        # 网格辅助线
C_WHITE: RGB = (0xEC, 0xEF, 0xF4)       # 纯白极简
C_BLUE_HI: RGB = (0x00, 0xB4, 0xD8)     # 渐变科技蓝（亮端）
C_BLUE_LO: RGB = (0x00, 0x77, 0xB6)     # 渐变科技蓝（暗端）
C_CMP: RGB = (0xFF, 0xEA, 0x00)         # 亮柠檬黄：正在比较
C_SWAP: RGB = (0xFF, 0x2A, 0x55)        # 珊瑚高亮红：正在交换 / 覆写
C_PIVOT: RGB = (0xB5, 0x37, 0xF2)       # 霓虹紫：基准值
C_BOUNDARY: RGB = (0x00, 0xF5, 0xD4)    # 电光青：区间边界
C_SORTED: RGB = (0x00, 0xE6, 0x76)      # 翠绿：已就位
C_HEAP: RGB = (0xFF, 0x9E, 0x2C)        # 橙色：堆顶
C_CURSOR: RGB = (0x40, 0xC4, 0xFF)      # 亮蓝：游标
C_MAX: RGB = (0xFF, 0x4D, 0xD2)         # 品红：当前最大
C_MIN: RGB = (0x2C, 0xE0, 0xB8)         # 青绿：当前最小
C_AUX: RGB = (0x4D, 0xD0, 0xE1)         # 辅助数组主色
C_AUX_HOT: RGB = (0x84, 0xFF, 0xFF)     # 辅助数组高亮
C_RULER: RGB = (0x24, 0x2A, 0x36)       # 参考导轨
#: 参考圆环 / 中轴线。比网格线亮一档 —— 偏差收缩环、捕梦网这类样式的
#: 全部信息都在「点离圆环有多远」上，环本身看不见的话这种样式就白做了。
C_RING: RGB = (0x35, 0x3F, 0x53)
C_DIVIDER: RGB = (0x22, 0x26, 0x30)     # 主/辅分屏分隔条
C_FLIP: RGB = (0xF2, 0x5A, 0xC8)        # 玫红：整段翻转（煎饼排序家族）
C_FLIP_BED: RGB = (0x2C, 0x14, 0x2A)    # 翻转区间的暗紫底色
C_CONSUMED: RGB = (0x33, 0x41, 0x54)    # 暗蓝灰：已搬入辅助数组
C_FLOOR: RGB = (0x0B, 0x0C, 0x10)       # 黑曜石地面（镜面倒影的底色）
C_HORIZON: RGB = (0x39, 0x4C, 0x6B)     # 地平线辉光

#: 标记角色 → 颜色（越靠后优先级越高，会覆盖前面的角色）
ROLE_COLORS: Tuple[Tuple[str, RGB], ...] = (
    # CONSUMED 放在最前：它只是「这块已经被搬走」的弱提示，任何真正的
    # 状态标记（已就位 / 基准值 / 比较高亮）都必须能盖住它。
    ("CONSUMED", C_CONSUMED),
    ("SORTED", C_SORTED),
    ("CURSOR", C_CURSOR),
    ("MIN", C_MIN),
    ("MAX", C_MAX),
    ("HEAP_ROOT", C_HEAP),
    ("BOUNDARY", C_BOUNDARY),
    ("PIVOT", C_PIVOT),
)

#: 实时操作高亮（优先级最高）
HOT_COLORS: Dict[str, RGB] = {
    "cmp": C_CMP,
    "swap": C_SWAP,
    "set": C_SWAP,
    "read": C_CURSOR,
    # FLIP 单独一种颜色：煎饼排序里「整段镜像」是唯一的写操作，若和 SWAP
    # 共用珊瑚红，观众只会看到「一大片红」，分不清是「交换两个」还是
    # 「翻转一整段」。玫红 + 区间底色带才能表达「这一段被整体翻过来了」。
    "flip": C_FLIP,
    "aux_set": C_AUX_HOT,
    "aux_swap": C_AUX_HOT,
    "aux_cmp": C_AUX_HOT,
    "aux_read": C_AUX_HOT,
}

#: 常规元素配色方案：(键, 中文标签)
PALETTES: Tuple[Tuple[str, str], ...] = (
    ("white", "纯白极简 (Pure White)"),
    ("gradient", "渐变科技蓝 (Tech Blue)"),
    ("rainbow", "HSV 全光谱彩虹 (Rainbow)"),
)

#: 18 种几何视图：(键, 中文标签)
#:
#: ``key`` 会写进 QSettings 存档，**已有键不要改动**（改了就丢用户偏好）。
#: 标签保持「中文 + 一个短英文词」：下拉框只有 190 px，长英文名会被省略成
#: 「经典垂直柱状图 (Vertical ...)」，反而看不出区别。
STYLES: Tuple[Tuple[str, str], ...] = (
    # ---- 基础三式 ----
    ("bars", "经典垂直柱状图 · Bars"),
    ("wheel", "径向花瓣环 · Petals"),
    ("scatter", "峰谷折线图 · Ridge"),
    # ---- 核心特色四式 ----
    ("mirror", "对称声波图 · Mirror"),
    ("disparity", "偏差收缩环 · Disparity"),
    ("pyramid", "居中金字塔 · Pyramid"),
    ("residual", "残差火柴图 · Stems"),
    # ---- 高概念创意五式 ----
    ("waterfall", "时空瀑布流 · Waterfall"),
    ("loom", "双轨织布机 · Loom"),
    ("nautilus", "鹦鹉螺放射柱 · Nautilus"),
    ("dreamcatcher", "圆环捕梦网 · Web"),
    ("tree", "隐式二叉树 · Heap Tree"),
    # ---- 次世代高画质六式（Instruction3）----
    # 这六种走的是完全不同的渲染管线：QPainter 矢量光栅（抗锯齿 / 渐变 /
    # 加色混合），而不是前 12 种的 NumPy 位图掩码。两者在同一个
    # ``StyleRenderer`` 接口后面，调用方（界面 / 导出器）完全无感。
    ("slice", "高清切片还原 · Slices"),
    ("arcs", "霓虹拱桥光弧 · Arcs"),
    ("helix3d", "全息双螺旋 · 3D Helix"),
    ("aurora", "流体极光丝带 · Aurora"),
    ("orbs", "高光玻璃球 · Orbs"),
    ("crystal", "低多边形晶格 · Crystal"),
)

#: 哪些样式的「横轴就是数组下标」——只有这些才在画布底部画向上三角指示标。
#: 其余样式（花瓣环 / 金字塔 / 二叉树…）里元素按角度、行或层级分布，
#: 底部三角标会指向完全无关的位置，纯属噪声。
HOT_MARKER_STYLES = frozenset({"bars", "scatter", "mirror", "residual"})

_U8 = np.uint8


# --------------------------------------------------------------------------
# 2. 调色板
# --------------------------------------------------------------------------
def _hsv_to_rgb(h_deg: np.ndarray, s: float = 0.74, v: float = 0.99) -> np.ndarray:
    """向量化 HSV → RGB（h 单位：度）。返回 ``(n, 3) uint8``。"""
    h = (np.asarray(h_deg, dtype=np.float64) % 360.0) / 60.0
    i = np.floor(h).astype(np.int64) % 6
    f = h - np.floor(h)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.clip(np.stack([r, g, b], axis=1) * 255.0, 0, 255).astype(_U8)


_PALETTE_CACHE: Dict[Tuple[int, str], np.ndarray] = {}


def palette_for(count: int, mode: str = "white") -> np.ndarray:
    """返回 ``(count, 3) uint8`` 的常规元素配色表（带缓存）。

    索引 k 对应「第 k 小」的元素，因此同一张表可直接按元素值取色。
    """
    count = max(1, int(count))
    key = (count, mode)
    hit = _PALETTE_CACHE.get(key)
    if hit is not None:
        return hit

    if mode == "gradient":
        t = np.linspace(0.0, 1.0, count, dtype=np.float64)[:, None]
        lo = np.array(C_BLUE_LO, dtype=np.float64)
        hi = np.array(C_BLUE_HI, dtype=np.float64)
        table = np.clip(lo + (hi - lo) * t, 0, 255).astype(_U8)
    elif mode == "rainbow":
        table = _hsv_to_rgb(np.linspace(0.0, 300.0, count))
    else:
        table = np.tile(np.array(C_WHITE, dtype=_U8), (count, 1))

    if len(_PALETTE_CACHE) > 32:        # 简单容量控制，避免无限增长
        _PALETTE_CACHE.clear()
    _PALETTE_CACHE[key] = table
    return table


def _index_of(values: np.ndarray, n_max: int) -> np.ndarray:
    return np.clip(values.astype(np.int64) - 1, 0, max(0, int(n_max) - 1))


def _norm01(values: np.ndarray, n_max: int) -> np.ndarray:
    """把元素值映射到 ``[0, 1]``（规范书里的 ``norm_i``）。

    等价于 ``(v - min) / (max - min)``：本项目的取值恒为 ``1 … n_max`` 的
    整数（数据生成器与全部 160 种算法都遵守这一点），所以
    ``(v - 1) / (n_max - 1)`` 就是「该元素在**最终有序序列**中的名次比例」。

    为什么不用当前数组的实测 min/max：

    * 主数组与辅助数组必须共用同一个参照系，分屏时两栏的高低才能互相比对；
    * 排序完成的瞬间 ``norm_i`` 恰好等于 ``i / (N - 1)`` —— 织布机的所有
      斜线才会「同时立正」，捕梦网的弦才会「全部缩回圆周」，偏差收缩环的
      点才会「全部贴到外圈」。差一个 ``1/n_max`` 的偏移在小 N 下肉眼可见，
      那些「完成」瞬间就不成立了。
    """
    return np.clip((np.asarray(values, dtype=np.float64) - 1.0)
                   / max(1.0, float(n_max) - 1.0), 0.0, 1.0)


def _paint_marks(colors: np.ndarray, marks: Dict[str, set], n: int) -> None:
    """把状态标记逐层盖到颜色数组上（层序即优先级）。"""
    if not marks:
        return
    for role, col in ROLE_COLORS:
        ids = marks.get(role)
        if not ids:
            continue
        arr = np.fromiter((i for i in ids if 0 <= i < n), dtype=np.int64)
        if arr.size:
            colors[arr] = col


def _paint_hot(colors: np.ndarray, hot: Dict[int, str], n: int) -> None:
    """把「正在比较 / 正在交换」的高亮盖到颜色数组上（最高优先级）。"""
    if not hot:
        return
    by_kind: Dict[str, List[int]] = {}
    for i, kind in hot.items():
        if 0 <= i < n:
            by_kind.setdefault(kind, []).append(i)
    if not by_kind:
        return
    for kind, col in HOT_COLORS.items():
        ids = by_kind.get(kind)
        if not ids:
            continue
        idx = np.asarray(ids, dtype=np.int64)
        if kind == "flip":
            # 翻转不是「两根柱子交换」，而是整段镜像。若像 SWAP 那样整段刷成
            # 纯玫红，一次翻 24 根就把整幅画面的数据层次全抹平了 —— 观众只
            # 看到「屏幕闪了一下粉色」。改成 45% 着色叠加后，区间一眼可见，
            # 每根柱子的高低与色相依然读得出来。
            colors[idx] = np.clip(
                colors[idx].astype(np.float64) * 0.55
                + np.array(col, dtype=np.float64) * 0.45,
                0, 255).astype(_U8)
        else:
            colors[idx] = col


_C_SORTED_ROW = np.array(C_SORTED, dtype=_U8)[None, :]

#: 「全部就位」时使用的翠绿渐变两端：深绿 → 亮绿。
#:
#: 早期版本在排序完成时把整条数组刷成**同一个** ``C_SORTED``，语义没错，但
#: 圆环 / 花瓣 / 矩阵这些样式一完成后就变成一块纯色饼，什么结构都看不出来。
#: 改成按位置做深浅渐变后，画面整体仍是绿色（表达「全部就位」），同时保留
#: 由低到高的层次，花瓣环、螺旋带、色块矩阵都能在完成瞬间呈现漂亮的渐层。
_C_SORTED_LO = np.array((0x00, 0x6B, 0x38), dtype=np.float64)
_C_SORTED_HI = np.array((0x4A, 0xFF, 0xA8), dtype=np.float64)


def _looks_sorted(values: np.ndarray) -> bool:
    """``values`` 是否已经非降序（给「全部就位」兜底做最后一道校验）。"""
    n = values.size
    return n <= 1 or bool(np.all(values[1:] >= values[:-1]))


def _sorted_colors(n: int) -> np.ndarray:
    """整条数组一律按「已就位」翠绿着色（由深到浅的绿渐变）。"""
    n = max(0, int(n))
    if n == 0:
        return np.zeros((0, 3), dtype=_U8)
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)[:, None]
    return np.clip(_C_SORTED_LO + (_C_SORTED_HI - _C_SORTED_LO) * t,
                   0, 255).astype(_U8)


def _element_colors(values: np.ndarray, n_max: int, mode: str,
                    marks: Dict[str, set], hot: Dict[int, str]) -> np.ndarray:
    colors = palette_for(max(1, int(n_max)), mode)[_index_of(values, n_max)].copy()
    _paint_marks(colors, marks, values.size)
    _paint_hot(colors, hot, values.size)
    return colors


def _aux_colors(values: np.ndarray, marks: Dict[str, set],
                hot: Dict[int, str]) -> np.ndarray:
    """辅助数组配色：统一偏青，但**保留标记与高亮**，让数据流动一目了然。"""
    n = values.size
    if n == 0:
        return np.zeros((0, 3), dtype=_U8)
    vmax = int(values.max()) if n else 1
    base = palette_for(max(1, vmax), "gradient")[_index_of(values, vmax)]
    tint = (base.astype(np.float64) * 0.40
            + np.array(C_AUX, dtype=np.float64) * 0.60)
    colors = np.clip(tint, 0, 255).astype(_U8)
    _paint_marks(colors, marks, n)
    _paint_hot(colors, hot, n)
    return colors


# --------------------------------------------------------------------------
# 3. 渲染帧
# --------------------------------------------------------------------------
@dataclass
class VizFrame:
    """一帧需要渲染的全部信息（与算法、与 Qt 都无关）。"""

    values: Sequence[int] = ()
    aux: Sequence[int] = ()
    aux_active: bool = False
    marks: Dict[str, set] = field(default_factory=dict)
    hot: Dict[int, str] = field(default_factory=dict)
    hot_aux: Dict[int, str] = field(default_factory=dict)
    n_max: int = 1
    palette: str = "white"
    sweep: float = 0.0            # SORTED 翠绿扫光进度 0~1（0 表示不扫）
    #: 是否已播放到指令流末尾（排序完成）。为 True 时整个主数组一律按
    #: 「已就位」着色 —— 见 :meth:`StyleRenderer._array_colors` 的说明。
    done: bool = False
    #: 当前指令流步号（-1 表示「不提供」）。
    #:
    #: 只有 ``waterfall``（时空瀑布流）需要它：那种样式维护一块滚动历史
    #: 缓冲，必须能识别「用户把进度条往回拖了」或「倒带到 0 重新播放」，
    #: 否则旧轨迹会一直留在画面上，看起来像残影。其余样式完全忽略该字段。
    step: int = -1

    #: 动画相位（秒）。
    #:
    #: 全息双螺旋要自转、极光要飘动、切片模式的激光扫描要来回扫 —— 这些
    #: 「与数据无关、只随时间走」的动效都需要一个时间基准。导出时由
    #: ``帧号 / fps`` 给出（因此成片完全确定性、可重放），实时预览时由画布
    #: 用单调时钟给出。
    t: float = 0.0

    #: 视角偏航角（弧度），由鼠标在画布上横向拖拽产生。
    #: 只有 ``helix3d``（全息双螺旋）真正使用它 —— 拖一下就能绕着模型转。
    yaw: float = 0.0

    def main_array(self) -> np.ndarray:
        return np.asarray(self.values, dtype=np.float64)

    def aux_array(self) -> np.ndarray:
        return np.asarray(self.aux, dtype=np.float64)


# --------------------------------------------------------------------------
# 4. 渲染内核基类
# --------------------------------------------------------------------------
class StyleRenderer:
    """所有几何样式的公共基类：持有一块可复用的 RGB 缓冲。"""

    key = "base"
    #: 「横轴 = 数组下标」的样式，画布会在底部补画向上三角指示标。
    hot_markers = False

    def __init__(self, width: int, height: int) -> None:
        self.w = 0
        self.h = 0
        self._buf = np.zeros((1, 1, 3), dtype=_U8)
        #: 预渲染的纯背景层。每帧用一次整块 ``memcpy`` 复位，比逐元素填充
        #: ``buf[:, :] = (13, 14, 18)`` 快 4~5 倍（后者要走广播机制）。
        self._bg = np.zeros((1, 1, 3), dtype=_U8)
        self._rows: Dict[Tuple[int, int], np.ndarray] = {}
        #: 参考圆的采样点缓存（外圈环、轮毂环）。圆只与画布尺寸有关，
        #: 每帧重算一圈三角函数属于纯浪费。
        self._circle_cache: Dict[tuple, Tuple[np.ndarray, np.ndarray]] = {}
        #: 动态余晖缓冲（1/4 分辨率的 float32 累积层）。见 :meth:`_compose_trail`。
        self._trail: Optional[np.ndarray] = None
        self._trail_n = -1
        self._trail_step = -1
        self.resize(width, height)

    # ---- 尺寸 ------------------------------------------------------------
    def resize(self, width: int, height: int) -> None:
        width = max(32, int(width))
        height = max(32, int(height))
        if width == self.w and height == self.h:
            return
        self.w, self.h = width, height
        self._buf = np.zeros((height, width, 3), dtype=_U8)
        self._bg = np.empty((height, width, 3), dtype=_U8)
        self._bg[:, :] = C_BG
        self._rows.clear()
        self._circle_cache.clear()
        self._trail = None
        self._trail_n = -1
        self._trail_step = -1
        self._on_resize()

    def _row_index(self, y0: int, y1: int) -> np.ndarray:
        """缓存 ``arange(y0, y1)[:, None]``，避免每帧重复分配行下标。"""
        key = (y0, y1)
        hit = self._rows.get(key)
        if hit is None:
            hit = np.arange(y0, y1, dtype=np.int64)[:, None]
            if len(self._rows) > 12:
                self._rows.clear()
            self._rows[key] = hit
        return hit

    def _on_resize(self) -> None:
        """钩子：子类可在此预计算与画布尺寸相关的缓存。"""

    # ---- 主入口 ----------------------------------------------------------
    def render(self, frame: VizFrame) -> np.ndarray:
        buf = self._buf
        buf[:] = self._bg                     # 整块 memcpy 复位背景
        main, aux = frame.main_array(), frame.aux_array()
        split = bool(frame.aux_active) and aux.size > 0

        if split:
            divider = 6
            main_h = max(24, int((self.h - divider) * 0.65))   # 规范书：上 65%
            aux_h = self.h - main_h - divider
            if aux_h < 16:
                main_h = max(24, self.h - divider - 16)
                aux_h = self.h - main_h - divider
            if main_h + divider + aux_h <= self.h and aux_h > 0:
                self._paint_array(buf, 0, main_h, main, frame, False)
                buf[main_h:main_h + divider, :] = C_DIVIDER
                self._paint_array(buf, main_h + divider, aux_h, aux, frame, True)
            else:                                              # 太小则不分屏
                self._paint_array(buf, 0, self.h, main, frame, False)
        else:
            self._paint_array(buf, 0, self.h, main, frame, False)

        self._apply_sweep(buf, frame.sweep)
        self._compose_trail(buf, frame)
        return buf

    # ---- 子类实现 --------------------------------------------------------
    def _paint_array(self, buf: np.ndarray, y0: int, bh: int,
                     values: np.ndarray, frame: VizFrame, aux: bool) -> None:
        raise NotImplementedError

    def _array_colors(self, values: np.ndarray, frame: VizFrame,
                      aux: bool) -> np.ndarray:
        if aux:
            return _aux_colors(values, frame.marks or {}, frame.hot_aux or {})
        if frame.done and values.size > 1 and _looks_sorted(values):
            # 排序完成后把整条数组统一铺成「已就位」翠绿。
            #
            # **为什么不能只靠算法自己 mark**：像冒泡排序这种「每趟把未排序区
            # 最大值送到末尾」的写法，循环体里只 ``mark(n - 1 - i, SORTED)``，
            # 而 ``i`` 最多取到 ``n - 2``，于是下标 0 那个位置从来没被显式标记
            # 过 —— 它是靠「只剩它一个」推导出来的。画面定格后第一个元素就仍是
            # 常规配色（白色），看着像没排好。这类写法在 160 种算法里很普遍，
            # 用户自己用 C / Java / Python 写的外部算法更无法约束。
            # 所以这里按「已播放到末尾 + 数据确实非降序」统一兜底，一次覆盖全部。
            return _sorted_colors(values.size)
        return _element_colors(values, frame.n_max, frame.palette,
                               frame.marks or {}, frame.hot or {})

    # ---- 降采样 ----------------------------------------------------------
    def _pick(self, n: int, limit: int, frame: VizFrame, aux: bool
              ) -> np.ndarray:
        """挑出「这一帧要真正画出来」的元素下标。

        ``N ≤ limit`` 时全画。超过则按**均匀步长**降采样（``s = ⌈N/limit⌉``），
        但**强制保留所有正被高亮的索引** —— 否则会出现「明明在做比较，
        画面上的高亮却被抽掉了」这种荒谬情况。

        这条规则只对「每元素一根线 / 一个节点」的样式生效；柱状图、折线图
        走的是「按屏幕列聚合」的路径，本身就与 N 无关，不需要降采样。
        """
        if n <= limit:
            return np.arange(n, dtype=np.int64)
        step = int(math.ceil(n / float(limit)))
        idx = np.arange(0, n, step, dtype=np.int64)
        hot = (frame.hot_aux if aux else frame.hot) or {}
        if hot:
            extra = np.fromiter((i for i in hot if 0 <= i < n), dtype=np.int64)
            if extra.size > limit:      # 整段 FLIP 之类的超大高亮，先自己抽稀
                extra = extra[::int(math.ceil(extra.size / float(limit)))]
            if extra.size:
                idx = np.union1d(idx, extra)
        return idx

    @staticmethod
    def _hot_flags(idx: np.ndarray, frame: VizFrame, aux: bool) -> np.ndarray:
        """``idx`` 中哪些下标当前处于高亮状态。"""
        hot = (frame.hot_aux if aux else frame.hot) or {}
        if not hot or idx.size == 0:
            return np.zeros(idx.size, dtype=bool)
        keys = np.fromiter((i for i in hot), dtype=np.int64)
        return np.isin(idx, keys)

    # ---- 参考圆 ----------------------------------------------------------
    def _circle_points(self, cx: float, cy: float, r: float
                       ) -> Tuple[np.ndarray, np.ndarray]:
        """圆周采样点 ``(xs, ys)``（带缓存）。

        用「按弧长取步数」保证大圆不会画成多边形、小圆不会浪费点数。
        """
        r = max(1.0, float(r))
        steps = int(min(4096, max(96, r * 3.4)))
        key = (round(float(cx), 1), round(float(cy), 1), round(r, 1), steps)
        hit = self._circle_cache.get(key)
        if hit is None:
            th = np.linspace(0.0, 2.0 * math.pi, steps, dtype=np.float32)
            hit = (np.rint(cx + r * np.cos(th)).astype(np.int64),
                   np.rint(cy + r * np.sin(th)).astype(np.int64))
            if len(self._circle_cache) > 24:
                self._circle_cache.clear()
            self._circle_cache[key] = hit
        return hit

    def _ring(self, sub: np.ndarray, cx: float, cy: float, r: float,
              color: RGB = C_RING) -> None:
        xs, ys = self._circle_points(cx, cy, r)
        _blit_dots(sub, xs, ys,
                   np.tile(np.array(color, dtype=_U8), (xs.size, 1)), 1)

    # ---- 公共工具 --------------------------------------------------------
    def _grid(self, buf: np.ndarray, y0: int, bh: int, lines: int = 6) -> None:
        """横向网格辅助线（纯切片赋值，无循环绘制）。"""
        for k in range(1, lines):
            y = y0 + bh * k // lines
            if 0 <= y < buf.shape[0]:
                buf[y, :] = C_GRID

    def _column_bars(self, values: np.ndarray, n_max: int
                     ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """把 n 个元素映射到 ``w`` 个屏幕列。

        返回 ``(每列的高度比例, 每列归属的元素下标, 每列是否落在柱体内)``。
        稀疏走「一柱多列」，稠密走「按列聚合最大值」。
        """
        n = values.size
        w = self.w
        if n == 0:
            return (np.zeros(w), np.zeros(w, dtype=np.int64),
                    np.zeros(w, dtype=bool))

        scale = max(1.0, float(n_max))
        if n <= w:
            edges = np.linspace(0.0, float(w), n + 1)
            x0 = np.floor(edges[:-1]).astype(np.int64)
            x1 = np.maximum(np.floor(edges[1:]).astype(np.int64), x0 + 1)
            gap = 1 if (w / n) >= 3.0 else 0
            xa = np.minimum(x0 + gap, w - 1)
            xb = np.minimum(np.maximum(x1 - gap, xa + 1), w)
            cols = np.arange(w)
            col = np.clip(np.searchsorted(xa, cols, side="right") - 1, 0, n - 1)
            inbar = (cols >= xa[col]) & (cols < xb[col])
            return np.clip(values[col] / scale, 0.0, 1.0), col, inbar

        # 稠密：每列聚合若干元素的最大值，柱宽自然退化为 1 像素
        col_of = (np.arange(n) * w) // n
        starts = np.clip(np.searchsorted(col_of, np.arange(w), side="left"),
                         0, n - 1)
        colmax = np.maximum.reduceat(values, starts)
        return np.clip(colmax / scale, 0.0, 1.0), starts, np.ones(w, dtype=bool)

    def _fill_bars(self, buf: np.ndarray, y0: int, bh: int,
                   ratio: np.ndarray, colcolors: np.ndarray,
                   inbar: np.ndarray, min_px: int = 1) -> None:
        """按列填充柱体：一次二维掩码 + 一次 ``np.copyto`` 批量赋值。

        早期版本用 ``buf[mask] = broadcast(...)[mask]`` 的花式索引，在
        1920x1080 下要 39 ms；换成 ``np.copyto(..., where=)`` 后只要 13 ms，
        在真实窗口尺寸（约 1180x620）下更是只有 4.4 ms。
        """
        if bh < 4:
            return
        base_y = y0 + bh - 1
        usable = bh - 2
        bar_h = np.maximum(min_px, np.rint(ratio * usable).astype(np.int64))
        tops = base_y - bar_h + 1
        rows = self._row_index(y0 + 1, base_y + 1)
        mask = (rows >= tops[None, :]) & inbar[None, :]
        sub = buf[y0 + 1:base_y + 1]
        np.copyto(sub, colcolors[None, :, :], where=mask[:, :, None])

    def _apply_sweep(self, buf: np.ndarray, sweep: float) -> None:
        """翠绿扫光校验动画：一条柔和的竖直光带自左向右掠过。

        光带用 **smoothstep 横向衰减**，而不是早期的「硬边等宽矩形」——
        硬边在 1080P 导出里就是一根突兀的纯绿柱，把整幅画面切断；改成
        中间最亮、两侧平滑收尾之后，看起来才像一道光扫过去。
        """
        if sweep <= 0.0:
            return
        w = self.w
        band = max(6, w // 16)
        # 光带的行程要比画布**宽出两个 band**：sweep=0 时整条光带停在左边界
        # 之外，sweep=1 时停在右边界之外。早期直接拿 ``sweep × w`` 当中心，
        # 扫到 100% 时半条绿带就永远钉在画布右缘，排序完成后右侧一直挂着
        # 一道突兀的绿色竖条。
        x = int(round(-band + float(min(max(sweep, 0.0), 1.0)) * (w + 2 * band)))
        x0 = max(0, x - band)
        x1 = min(w, x + band + 1)
        if x1 <= x0:
            return
        xs = np.arange(x0, x1, dtype=np.float32)
        k = np.clip(1.0 - np.abs(xs - np.float32(x)) / float(band), 0.0, 1.0)
        k = (k * k * (3.0 - 2.0 * k)) * 0.62          # smoothstep 衰减
        k = k[None, :, None]
        region = buf[:, x0:x1].astype(np.float32)
        col = np.array(C_SORTED, dtype=np.float32)
        buf[:, x0:x1] = np.clip(region * (1.0 - k) + col * k,
                                0, 255).astype(_U8)

    # ---- 画质管线 A：动态余晖 / 运动残影 --------------------------------
    def _compose_trail(self, buf: np.ndarray, frame: VizFrame) -> None:
        """动态余晖层（Motion Trail / Afterimage）。

        **为什么放在渲染内核、而不是画布控件的 QPixmap 上**：本项目的一条
        硬规矩是「屏上所见 = 导出所得」。如果残影只活在 ``CanvasWidget`` 的
        一个 ``QPixmap`` 里，那么导出 MP4 时就完全没有这套光轨 —— 同一套
        参数出来的视频和预览会变成两种画风。放进内核之后，界面与离屏导出
        走的是**同一行代码**，残影是「画面的一部分」而不是「控件特效」。

        实现上没有用「整张画布 ``DestinationIn`` 叠一层 215/255 的衰减
        遮罩」，因为这个语义（每帧 alpha ×0.843，8~12 帧内淡出）在 NumPy
        里等价于一个乘法，而**整画布**做这件事在 1080P 下每帧要 5~6 ms、
        4K 下接近 20 ms。这里改成：

        * 缓冲按 ``1/4`` 分辨率维护（``(H/4, W/4, 3) float32``）—— 残影本来
          就该是柔光，缩小后上采样反而更像辉光扩散；
        * 只把「当前帧里颜色恰好等于 CMP 黄 / SWAP 红」的像素当作热源，
          且只在 1/4 分辨率上比对（约 4.5 万格子），耗时 0.2~0.4 ms；
        * 最后只在热源的**包围盒**内上采样叠加，而不是整画布。

        净效果与规范书要求的一致（高光拖出 8~12 帧的丝滑光轨，彻底消除
        单帧闪烁），但代价从 ~6 ms 降到 ~0.4 ms。
        """
        n = int(len(frame.values))
        step = int(frame.step)
        # 换算法 / 换数据量 / 把进度条拖回 0 或往回拖 —— 旧光轨必须丢掉
        if (self._trail is None or n != self._trail_n
                or step == 0 or (step >= 0 and 0 <= step < self._trail_step)):
            th = max(1, (self.h + _TRAIL_SHRINK - 1) // _TRAIL_SHRINK)
            tw = max(1, (self.w + _TRAIL_SHRINK - 1) // _TRAIL_SHRINK)
            self._trail = np.zeros((th, tw, 3), dtype=np.float32)
            self._trail_n = n
        self._trail_step = step if step >= 0 else self._trail_step

        tr = self._trail
        tr *= _TRAIL_DECAY                      # 等价于 DestinationIn 的 215/255
        kinds = set((frame.hot or {}).values())
        kinds |= set((frame.hot_aux or {}).values())
        # FLIP 用的是 45% 混色，像素值不等于原色，逐像素比对抓不到；
        # 它本身又覆盖一大段区间，本来也不需要「残影」来增强存在感。
        kinds.discard("flip")
        if kinds:
            # 热源检测再降一档采样（1/8 分辨率）：逐像素等值比对是这里唯一
            # 的全画布级运算，1180×620 下按 1/4 采样要 0.9 ms/色，按 1/8
            # 只要 0.2 ms/色。残影本来就是柔光，粗一档采样反而更像辉光。
            s2 = _TRAIL_SHRINK * 2
            r2 = (self.h + s2 - 1) // s2
            c2 = (self.w + s2 - 1) // s2
            sub = buf[:r2 * s2:s2, :c2 * s2:s2]
            dst = tr[:r2 * 2:2, :c2 * 2:2]
            for kind in kinds:
                col = HOT_COLORS.get(kind)
                c8 = _HOT_U8.get(kind)
                if col is None or c8 is None:
                    continue
                m = np.all(sub == c8, axis=2)
                if m.any():
                    dst[m] += np.asarray(col, dtype=np.float32) * _TRAIL_GAIN
            # 软上限：稳态亮度本应是 ``gain / (1 - decay) ≈ 5.0``，即 1275，
            # 但小数组排序时热源会连续十几帧钉在同一格（相邻比较反复命中），
            # 累积到 1100 就是一坨死白的方斑，把柱体本身的形状都吃掉。
            # 封顶在 _TRAIL_CAP（略高于 255）—— 保留「中心过曝成白芯」的观感，
            # 又不会漫出来；历史帧强度远低于此值，衰减曲线完全不受影响。
            if float(tr.max()) > _TRAIL_CAP:
                np.minimum(tr, _TRAIL_CAP, out=tr)

        act = tr.max(axis=2) > 1.5
        if not act.any():
            return
        rows = np.flatnonzero(act.any(axis=1))
        cols = np.flatnonzero(act.any(axis=0))
        r0, r1 = int(rows[0]), int(rows[-1]) + 1
        c0, c1 = int(cols[0]), int(cols[-1]) + 1
        block = tr[r0:r1, c0:c1]
        up = np.repeat(np.repeat(block, _TRAIL_SHRINK, axis=0),
                       _TRAIL_SHRINK, axis=1)
        y, x = r0 * _TRAIL_SHRINK, c0 * _TRAIL_SHRINK
        hh = min(up.shape[0], self.h - y)
        ww = min(up.shape[1], self.w - x)
        if hh <= 0 or ww <= 0:
            return
        chunk = buf[y:y + hh, x:x + ww].astype(np.float32)
        chunk += up[:hh, :ww]
        np.clip(chunk, 0, 255, out=chunk)
        buf[y:y + hh, x:x + ww] = chunk.astype(_U8)

    def reset_trail(self) -> None:
        """清空余晖层（切换算法 / 重新录制时由外部调用）。"""
        self._trail = None
        self._trail_n = -1
        self._trail_step = -1

    # ---- 画质管线 B：黑曜石镜面倒影 --------------------------------------
    def _content_bottom(self, buf: np.ndarray, y0: int, stage: int) -> int:
        """在 ``[y0, y0+stage)`` 内找出「最后一个有内容」的行（相对 stage 的偏移）。

        圆形样式的外轮廓半径随数据变化（鹦鹉螺的螺线外沿、偏差环的塌陷点
        都不到理论半径），所以倒影的贴附位置**必须实测**而不是拿 rmax 算。
        按 2 行 / 3 列抽样，1080P 下约 0.4 ms，比整幅比对便宜一个数量级。
        """
        if stage <= 8:
            return stage
        sub = buf[y0:y0 + stage:2, ::3]
        bg = np.array(C_BG, dtype=_U8)
        rows = np.flatnonzero(np.any(sub != bg, axis=(1, 2)))
        if rows.size == 0:
            return stage
        return int(min(stage, int(rows[-1]) * 2 + 2))

    def _reflect_floor(self, buf: np.ndarray, y0: int, bh: int, stage: int,
                       bottom: Optional[int] = None, gain: float = 0.62) -> None:
        """把舞台区底部 ``fh`` 行镜像翻转到地面，并向下渐隐。

        用于所有「圆形 / 半圆舞台」样式的收尾：上方是主绘图区，下方是黑曜石
        地面。倒影按 ``a = gain·t²`` 衰减到底色 :data:`C_FLOOR`，因此不会抢
        主体；再加一条地平线辉光把它「钉」在地上，画面立刻从「浮在黑底上的
        图」变成「摆在黑曜石台上的装置」。

        ``bottom`` 是**物体真正的底边**（圆盘最下沿）。反射必须贴着物体底边
        开始，而不是贴在地面分界线上 —— 否则圆盘与倒影之间会空出一条黑缝，
        倒影看着像另一件悬浮的东西，镜面感立刻崩掉。
        """
        b = stage if bottom is None else int(min(max(bottom, 8), bh - 4))
        fh = min(bh - b, b)
        if fh < 6:
            return
        src = buf[y0 + b - fh:y0 + b][::-1]
        dst = buf[y0 + b:y0 + b + fh]
        if dst.shape != src.shape:
            return
        t = np.linspace(1.0, 0.0, fh, dtype=np.float32)[:, None, None]
        a = (gain * t * t).astype(np.float32)
        out = src.astype(np.float32) * a + np.array(C_FLOOR, np.float32) * (1.0 - a)
        dst[:] = out.astype(_U8)
        yh = y0 + b
        if 0 <= yh < buf.shape[0]:
            buf[yh] = C_HORIZON
        if 0 <= yh - 1 < buf.shape[0]:
            buf[yh - 1] = np.maximum(buf[yh - 1], np.array(
                (0x1E, 0x26, 0x33), dtype=_U8))


#: 余晖缓冲的降采样倍数（1/4 分辨率 → 上采样后天然带柔光扩散）
_TRAIL_SHRINK = 4
#: 每帧 alpha 衰减系数，等价于规范书里的 ``215/255``；0.843^10 ≈ 0.18
_TRAIL_DECAY = 215.0 / 255.0
#: 热源注入强度。稳态亮度 ≈ gain /(1 - decay) = 0.78/0.157 ≈ 5.0，
#: 中心自然过曝成白芯、外圈留下彩色拖尾 —— 正是霓虹灯管的样子。
_TRAIL_GAIN = 0.78
#: 累积层软上限。热源长时间钉在同一格时（小 N 相邻比较）会冲上 1100+
#: 糊成死白方斑；封顶在略高于 255 处，白芯保留、漫射收住。
_TRAIL_CAP = 300.0
#: 热源颜色（只用于「逐像素等值比对」找高光像素）
_HOT_U8: Dict[str, np.ndarray] = {
    k: np.array(v, dtype=_U8) for k, v in HOT_COLORS.items()}


# --------------------------------------------------------------------------
# 5. 点阵批绘工具
# --------------------------------------------------------------------------
def _blit_dots(sub: np.ndarray, xs: np.ndarray, ys: np.ndarray,
               colors: np.ndarray, size: int) -> None:
    """把 n 个 ``size×size`` 方点批量写入子缓冲（一次花式索引赋值）。

    通过「行偏移 ⊗ 列偏移」构造出 ``(n, size, size)`` 的扁平下标矩阵，
    完全避免在 Python 层逐点绘制。
    """
    n = xs.size
    if n == 0:
        return
    h, w = sub.shape[0], sub.shape[1]
    if size <= 1:
        np.clip(xs, 0, w - 1, out=xs)
        np.clip(ys, 0, h - 1, out=ys)
        sub[ys, xs] = colors
        return
    off = np.arange(size) - size // 2
    px = np.clip(xs[:, None] + off[None, :], 0, w - 1)        # (n, size)
    py = np.clip(ys[:, None] + off[None, :], 0, h - 1)        # (n, size)
    flat = (py[:, :, None] * w + px[:, None, :]).reshape(-1)
    sub.reshape(-1, 3)[flat] = np.repeat(colors, size * size, axis=0)


def _blend_dots(sub: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                colors: np.ndarray, alpha: int = 255, size: int = 1) -> None:
    """同 :func:`_blit_dots`，但支持半透明混合（弦线、牵引线要用）。

    仍是一次花式索引批量读写 —— 重复落点采用「后写覆盖」而不是逐次累积，
    视觉上足以表达交叠（弦网越密越亮），但省掉了 ``np.add.at`` 那种
    慢一个数量级的散射累加。
    """
    if xs.size == 0:
        return
    h, w = sub.shape[0], sub.shape[1]
    if size > 1:
        off = np.arange(size, dtype=np.int64) - size // 2
        px = xs[:, None] + off[None, :]
        py = ys[:, None] + off[None, :]
        np.clip(px, 0, w - 1, out=px)
        np.clip(py, 0, h - 1, out=py)
        flat = (py[:, :, None] * w + px[:, None, :]).reshape(-1)
        col = np.repeat(colors, size * size, axis=0)
    else:
        flat = ys * w + xs
        col = colors
    view = sub.reshape(-1, 3)
    if alpha >= 255:
        view[flat] = col
        return
    a = max(0.0, min(1.0, alpha / 255.0))
    view[flat] = (view[flat].astype(np.float32) * (1.0 - a)
                  + col.astype(np.float32) * a).astype(_U8)


def _draw_segments(sub: np.ndarray, x0: np.ndarray, y0: np.ndarray,
                   x1: np.ndarray, y1: np.ndarray, colors: np.ndarray,
                   alpha: int = 255, thick: int = 1,
                   max_points: int = 240_000) -> None:
    """批量绘制 ``n`` 条线段（矢量化的「采样填充」，无 Python 逐线循环）。

    每条线段按它在屏幕上的**像素跨度**决定采样点数（最少 2 个端点、最多
    384 个），保证采样步长不超过 1 像素 —— 少一格就会画成虚线，而织布机
    与捕梦网恰恰靠「丝线是否连续」来表达信息，虚线会让整幅图失去质感。

    采样总数超过 ``max_points`` 时按比例整体降密度。这一步是有意的取舍：
    这时线会略微变稀（仍不会断），但绝不会掉帧。
    """
    n = int(x0.size)
    if n == 0:
        return
    h, w = sub.shape[0], sub.shape[1]
    x0 = np.asarray(x0, dtype=np.float32)
    y0 = np.asarray(y0, dtype=np.float32)
    x1 = np.asarray(x1, dtype=np.float32)
    y1 = np.asarray(y1, dtype=np.float32)
    dx = x1 - x0
    dy = y1 - y0
    span = np.maximum(np.abs(dx), np.abs(dy))

    # 采样点数按 8 像素一档量化。**为什么值得量化**：量化之后同一个桶里的
    # 线段共用一个 K，于是全部坐标可以一次性整形成 ``(m, K)`` 做纯向量
    # 运算，彻底免掉 ``repeat`` / ``cumsum`` 那几个十几万元素的大数组分配 ——
    # 实测这一步原来占了整条线段绘制 55% 的时间。
    #
    # 量化误差只会让线段「多采几个点」，多出来的样本落在终点上重复写一次，
    # 肉眼完全看不出来；而采样步长始终保持在 1 像素上下，绝不会画成虚线。
    kq = np.clip(np.ceil((span + 2.0) / 8.0).astype(np.int64) * 8, 8, 384)
    total = int(kq.sum())
    if total > max_points:
        # 总量超预算：整体降一档（仍保持 8 的倍数），线会略稀但不会断
        factor = max_points / float(total)
        kq = np.maximum(8, (kq * factor).astype(np.int64) // 8 * 8)

    if alpha < 255:
        # **关键优化**：线段下面一律是均匀的深空黑背景，所以「半透明色叠在
        # 背景上」的结果对每一段都是常量 —— 与其对二十万个像素逐点做一次
        # float 混合，不如先把颜色和背景按 alpha 预乘一次（只有 n ≤ 512 次），
        # 然后完全不透明地刷上去。视觉差异仅在「线与线交叠处不再累加亮度」，
        # 而那本来就不是这里要表达的语义。
        a = max(0.0, min(1.0, alpha / 255.0))
        colors = np.clip(
            colors.astype(np.float32) * a
            + np.array(C_BG, dtype=np.float32) * (1.0 - a),
            0, 255).astype(_U8)
        alpha = 255

    for k in np.unique(kq):
        k = int(k)
        sel = kq == k
        u = np.linspace(0.0, 1.0, k, dtype=np.float32)[None, :]
        px = np.rint(x0[sel][:, None] + dx[sel][:, None] * u
                     ).astype(np.int64).reshape(-1)
        py = np.rint(y0[sel][:, None] + dy[sel][:, None] * u
                     ).astype(np.int64).reshape(-1)
        np.clip(px, 0, w - 1, out=px)
        np.clip(py, 0, h - 1, out=py)
        _blend_dots(sub, px, py, np.repeat(colors[sel], k, axis=0), alpha, thick)


_DISC_CACHE: Dict[int, np.ndarray] = {}


def _disc_offsets(radius: int) -> np.ndarray:
    """半径 ``radius`` 的实心圆覆盖偏移 ``(k, 2)``（``dy, dx``），带缓存。"""
    radius = max(1, min(24, int(radius)))
    hit = _DISC_CACHE.get(radius)
    if hit is None:
        r = radius
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        mask = (yy * yy + xx * xx) <= (r * r + r * 0.7)
        hit = np.stack([yy[mask], xx[mask]], axis=1).astype(np.int64)
        _DISC_CACHE[radius] = hit
    return hit


def _blit_discs(sub: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                colors: np.ndarray, radii: np.ndarray) -> None:
    """批量绘制半径各异的**实心圆**（二叉树节点用）。

    圆盘偏移按整数半径分桶 —— 一帧里通常只有 6~9 种半径，于是整幅图
    只需要 6~9 次批量索引赋值，而不是逐节点画圆。
    """
    if xs.size == 0:
        return
    h, w = sub.shape[0], sub.shape[1]
    rs = np.clip(np.rint(radii).astype(np.int64), 1, 24)
    for r in np.unique(rs):
        sel = rs == r
        off = _disc_offsets(int(r))
        k = off.shape[0]
        px = np.clip(xs[sel][:, None] + off[None, :, 1], 0, w - 1)
        py = np.clip(ys[sel][:, None] + off[None, :, 0], 0, h - 1)
        flat = (py * w + px).reshape(-1)
        sub.reshape(-1, 3)[flat] = np.repeat(colors[sel], k, axis=0)


# --------------------------------------------------------------------------
# 6. 十二种 NumPy 光栅样式
# --------------------------------------------------------------------------
class BarsRenderer(StyleRenderer):
    """经典垂直柱状图：自适应间隙与宽度。"""

    key = "bars"
    hot_markers = True

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        self._grid(buf, y0, bh, 4 if aux else 6)
        n = values.size
        if n == 0:
            return
        if not aux:
            self._paint_flip_band(buf, y0, bh, frame, n)
        ratio, col, inbar = self._column_bars(values, frame.n_max)
        colors = self._array_colors(values, frame, aux)
        colcolors = colors[col]
        if not aux and n > self.w:
            # 稠密模式下列归属只取到「该列首个元素」的颜色，
            # 因此把被标记 / 高亮的元素按其所属屏幕列显式覆盖一次。
            special: Dict[int, RGB] = {}
            for role, c in ROLE_COLORS:
                for i in (frame.marks or {}).get(role, ()):
                    if 0 <= i < n:
                        special[i] = c
            for i, kind in (frame.hot or {}).items():
                if 0 <= i < n:
                    special[i] = HOT_COLORS.get(kind, C_CMP)
            for i, c in special.items():
                p = min(self.w - 1, (i * self.w) // n)
                colcolors[p] = c
        self._fill_bars(buf, y0, bh, ratio, colcolors, inbar)

    def _paint_flip_band(self, buf, y0, bh, frame, n: int) -> None:
        """给「整段翻转」的区间铺一条暗紫底色带。

        FLIP 是煎饼排序家族唯一的写操作，一次就把一段柱子整体镜像。光靠
        「区间内每根柱子变玫红」在 N 大、速度快时根本来不及看，于是观众
        只觉得画面「莫名抖了一下」。这里在柱体背后先铺一条暗紫底色，
        把「哪一段被翻过来了」变成**静态可读的范围标记**：柱子长什么样
        先不管，范围先立在那儿。
        """
        hot = frame.hot or {}
        idx = [i for i, k in hot.items() if k == "flip"]
        if len(idx) < 2:
            return
        lo_i, hi_i = min(idx), max(idx)
        x0 = int(lo_i * self.w / max(1, n))
        x1 = int((hi_i + 1) * self.w / max(1, n))
        x1 = max(x0 + 1, min(self.w, x1))
        if 0 <= y0 + 1 and y0 + bh - 1 <= buf.shape[0]:
            buf[y0 + 1:y0 + bh - 1, x0:x1] = C_FLIP_BED


class _PolarBase(StyleRenderer):
    """极坐标样式的公共内核：把「每像素的角度 / 半径 / 扇区归属」全预计算掉。

    半径、角度、扇区归属、「圆内 ∧ 扇区缝隙」掩码、轮毂描边**全部只与画布
    尺寸和 ``n`` 有关，与数据无关**，所以一次性算完并按 ``(尺寸, n)`` 缓存。
    每帧只剩三件事：按数值算外沿半径、一次 gather 取色、一次掩码协拷贝。

    早期版本把这些都放在每帧里算，1080P 下光两次全画布布尔运算就要 10 ms
    以上 —— 这就是径向样式「一开就卡」的根源。

    子类只需给几个常数：

    * ``_RIN``  —— 内轮毂半径占 ``rmax`` 的比例；
    * ``_GAP``  —— 扇区之间的缝隙（占单个扇区角度的比例）；
    * ``_DISC`` —— ``rmax`` 相对 ``min(w, bh) / 2`` 的收缩系数。
    """

    _RIN = 0.30
    _GAP = 0.18
    _DISC = 1.0
    _EDGE_OUTER = True
    #: 底部黑曜石地面占比（圆形视图统一启用，见基类 ``_reflect_floor``）
    _FLOOR = 0.22
    #: 沿半径方向的角向扭转量（弧度）。0 = 笔直的放射瓣（花瓣环）；
    #: 非 0 时每根瓣会随半径向外逐渐偏转，长成真正的螺线（鹦鹉螺）。
    _TWIST = 0.0

    def __init__(self, width: int, height: int) -> None:
        self._polar_cache: Dict[Tuple[str, int, int, int], tuple] = {}
        self._gather_buf: Optional[np.ndarray] = None
        super().__init__(width, height)

    def _polar(self, bh: int, n: int) -> tuple:
        """返回 ``(rr, rg, base, edge, rmax, rin, lo, hi, lo_c, hi_c)``。"""
        key = (self.key, self.w, bh, n)
        hit = self._polar_cache.get(key)
        if hit is not None:
            return hit
        w = self.w
        ys = np.arange(bh, dtype=np.float32)[:, None] - np.float32((bh - 1) / 2.0)
        xs = np.arange(w, dtype=np.float32)[None, :] - np.float32((w - 1) / 2.0)
        r = np.sqrt(xs * xs + ys * ys)
        rmax = max(10.0, min(w, bh) / 2.0 - 6.0) * self._DISC
        rin = max(3.0, rmax * self._RIN)
        ang = np.arctan2(ys, xs)
        ang = np.where(ang < 0.0, ang + np.float32(2.0 * math.pi), ang)
        # 从 12 点钟方向起算（顺时针）：这样「索引 0」永远在正上方，
        # 有序时首尾相接的那道「悬崖」落在表盘 12 点，看起来像刻度起点
        # 而不是随机的一道缺口。
        ang = ang + np.float32(math.pi * 0.5)
        if self._TWIST:
            # 角向扭转：半径每增大一格，扇区编号就往后挪一点。于是「笔直的
            # 放射瓣」被拧成一道螺线 —— 这是鹦鹉螺样式与径向花瓣环在**形态**
            # 上真正的区别（否则两者只是内环大小不同，看着像同一个东西）。
            # 扭转量与半径线性相关，仍然只依赖尺寸，可以整体进缓存。
            ang = ang - np.float32(self._TWIST) * (
                (r - np.float32(rin)) / np.float32(max(1.0, rmax - rin)))
        t = np.mod(ang * np.float32(n / (2.0 * math.pi)), np.float32(n))
        ring = np.clip(t.astype(np.int32), 0, n - 1)
        seg = t - ring                                # 扇区内位置 0~1
        inside = (r >= rin) & (r <= rmax * 1.002)
        if n <= 240:
            g = self._GAP * 0.5
            base = inside & (seg > g) & (seg < 1.0 - g)
        else:
            # 扇区窄到不足 1.5° 时再留缝就成了摩尔纹，直接连成整圈
            base = inside
        edge = inside & (np.abs(r - rin) <= 1.0)
        if self._EDGE_OUTER:
            edge |= inside & (np.abs(r - rmax) <= 1.0)

        cy = (bh - 1) / 2.0
        cx = (w - 1) / 2.0
        lo = max(0, int(math.floor(cy - rmax)))
        hi = min(bh, int(math.ceil(cy + rmax)) + 1)
        # 圆盘在水平方向也只覆盖 ``2·rmax`` 列，宽屏画布上左右各有大块死区。
        # 只把这一块裁出来算，1080P（1920 宽、圆盘仅 1068 列）能再省 45%
        # 的带宽 —— 这是径向样式从 30 ms 压到 17 ms 的关键一步。
        lo_c = max(0, int(math.floor(cx - rmax)))
        hi_c = min(w, int(math.ceil(cx + rmax)) + 1)
        payload = (r[lo:hi, lo_c:hi_c], ring[lo:hi, lo_c:hi_c],
                   base[lo:hi, lo_c:hi_c], edge[lo:hi, lo_c:hi_c],
                   np.float32(rmax), np.float32(rin), lo, hi, lo_c, hi_c)
        if len(self._polar_cache) > 4:
            self._polar_cache.clear()
        self._polar_cache[key] = payload
        return payload

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        # 圆形视图统一让出底部 22% 给「黑曜石镜面地面」（规范书第一节第 4 条）。
        # 分屏的 AUX 栏本来就只有两百来像素高，再切一刀会把圆压成一条缝，
        # 所以只对高度足够的区域启用。
        floor = self._FLOOR if (self._FLOOR and bh >= 200 and not aux) else 0.0
        stage = bh - int(round(bh * floor))
        (rr, rg, base, edge, rmax, rin,
         lo, hi, lo_c, hi_c) = self._polar(stage, n)
        if hi <= lo or hi_c <= lo_c:
            return
        colors = self._array_colors(values, frame, aux)
        # 每个扇区的外沿半径：从内环按名次比例向外延伸
        rad = (rin + _norm01(values, frame.n_max)
               * (rmax - rin)).astype(np.float32)

        hh = hi - lo
        hw = hi_c - lo_c
        if self._gather_buf is None or self._gather_buf.shape != (hh, hw, 3):
            self._gather_buf = np.empty((hh, hw, 3), dtype=_U8)
        np.take(colors, rg, axis=0, out=self._gather_buf)

        mask = base & (rr <= rad[rg])
        view = buf[y0 + lo:y0 + hi, lo_c:hi_c]
        np.copyto(view, self._gather_buf, where=mask[:, :, None])

        # 轮毂（与最外缘）各描一圈暗灰，给这朵花一个「画框」
        view[edge] = C_RULER
        if floor > 0.0:
            # 倒影贴着**实测**的圆盘下沿开始，中间绝不空出黑缝
            self._reflect_floor(buf, y0, bh, stage,
                                bottom=self._content_bottom(buf, y0, stage))


class WheelRenderer(_PolarBase):
    """径向花瓣环：360° 均分索引，瓣长 = 数值。

    旧版把「半径 = 数值」画成一根根自圆心射出的针：乱序像一只刺猬，有序则
    糊成一整块实心圆饼 —— 两种状态都读不出信息，而且圆盘直径只用掉画布
    短边的 55%，四周全是空的。

    新版把可视区改成「内轮毂 + 外缘」之间的**单向花瓣**：每个元素独占一个
    固定角度的扇区，扇区里只填「内圆 → 瓣长」这一段，瓣与瓣之间留一道缝。

    * 乱序 → 一圈长短参差的梳齿，一眼看出哪里高哪里低；
    * 有序 → 由短到长均匀舒展的一朵花，排序进程一目了然。
    """

    key = "wheel"
    _RIN = 0.30          # 内轮毂半径占 rmax 的比例
    _GAP = 0.18          # 瓣间缝隙（占单个扇区角度的比例）


class NautilusRenderer(_PolarBase):
    """极坐标鹦鹉螺放射柱（Sunburst Corona）。

    与花瓣环的差别在**比例**，观感完全不同：

    * 内环收到 ``0.12·min(W, H)``，薄薄一圈，中央留出大片呼吸空间；
    * 放射柱最远只伸到 ``0.46·min``，即 ``R_inner + norm × 0.34·min``；
    * 扇区缝隙更窄（10%），柱体连成一片连续的频谱。

    乱序是一圈参差的赛博朋克放射频谱；排好后外缘由短到长顺时针平滑展开，
    轮廓正好是一枚黄金鹦鹉螺壳。
    """

    key = "nautilus"
    #: ``R_inner = 0.12·min``，而 ``rmax = 0.46·min``，比值即 0.12 / 0.46
    _RIN = 0.12 / 0.46
    _GAP = 0.10
    _DISC = 0.92         # rmax = 0.92 × (min/2) ≈ 0.46·min
    _EDGE_OUTER = False  # 外缘是长短不一的柱尖，描一圈反而像给频谱加了个盖子
    _TWIST = 2.1         # ≈120° 的螺线扭转，出来就是一枚鹦鹉螺壳

class ScatterRenderer(StyleRenderer):
    """峰谷折线图：横轴 = 索引，纵轴 = 数值。

    旧版是「纯散点」：每个元素只是一个 1~3 像素的暗点，N 稍大就退化成一片
    几乎看不见的灰尘，乱序与有序在观感上毫无差别 —— 这正是「其他视图不太
    行」的核心原因。

    新版分三层叠加：

    1. 折线下方按列做**低饱和填充**，形成有体积感的山脊；
    2. 相邻顶点的竖直像素段连成**连续折线**，陡坡处自动补满，永不掉线；
    3. 顶点画方点，保留「散点」抓手（N 不大时）。

    乱序是一道剧烈起伏的山脊，有序收敛成一条平缓上升的斜坡 —— 排序进度、
    数据形态、元素位置三者同时可读。
    """

    key = "scatter"
    hot_markers = True
    #: 折线下方填充的混合系数（0 = 纯背景，1 = 与折线同色）。
    #: 取值要够低：填充一旦过重，整幅图就退化成「没有缝的柱状图」，
    #: 折线与峰谷全被淹在里面；但也不能太低，否则在深色背景上填充会
    #: 彻底黑掉，山脊失去体量感。
    _FILL_MIX = 0.20

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        self._grid(buf, y0, bh, 4 if aux else 5)

        pad_x, pad_y = 4, 5
        ih = max(3, bh - 2 * pad_y)
        iw = max(3, self.w - 2 * pad_x)
        scale = max(1.0, float(frame.n_max))
        ratio = np.clip(values / scale, 0.0, 1.0)
        ys = (ih - 1) - np.rint(ratio * (ih - 1)).astype(np.int64)   # 0 = 顶

        cols = np.arange(iw, dtype=np.int64)
        if n <= iw:
            # 稀疏：线性插值，但元素中心列强制回到真实值（顶点不能偏）
            xe = np.rint(np.linspace(0.0, iw - 1, n)).astype(np.int64)
            yc = np.interp(cols, xe, ys)
            yc[xe] = ys
            # 每一屏幕列归属「左边最近的那个元素」——颜色要按列取，不是按元素取
            col_at = np.clip(np.searchsorted(xe, cols, side="right") - 1, 0, n - 1)
        else:
            # 稠密：每列聚合该列所有元素的**最大值**（y 取最小），不丢尖峰
            col_of = (np.arange(n) * iw) // n
            starts = np.clip(np.searchsorted(col_of, cols, side="left"), 0, n - 1)
            yc = np.minimum.reduceat(ys, starts).astype(np.float64)
            col_at = starts

        yc = np.clip(np.rint(yc).astype(np.int64), 0, ih - 1)
        colors = self._array_colors(values, frame, aux)
        colcolors = colors[col_at]

        sub = buf[y0 + pad_y:y0 + pad_y + ih, pad_x:pad_x + iw]
        rows = np.arange(ih, dtype=np.int64)[:, None]

        # 1. 山脊填充
        fill = (colcolors.astype(np.float64) * self._FILL_MIX
                + np.array(C_BG, dtype=np.float64) * (1.0 - self._FILL_MIX))
        np.copyto(sub, np.clip(fill, 0, 255).astype(_U8)[None, :, :],
                  where=(rows >= yc[None, :])[:, :, None])

        # 2. 连续折线：把「本列顶 → 右邻列顶」之间的像素段整段点亮。
        # 大画布（导出 1080P 及以上）补一列写成 2 像素宽，否则细线在视频里
        # 几乎看不见；窗口实时播放时只写一列 —— 多一次全画布掩码拷贝在
        # 1600×880 下要多花 8 ms，实时帧率会从 50 掉到 35。
        if iw > 1:
            top = np.minimum(yc[:-1], yc[1:])
            bot = np.maximum(yc[:-1], yc[1:])
            line = (rows >= top[None, :]) & (rows <= bot[None, :])
            np.copyto(sub[:, :-1], colcolors[None, :-1, :],
                      where=line[:, :, None])
            if self.w * self.h >= 1_500_000:
                np.copyto(sub[:, 1:], colcolors[None, 1:, :],
                          where=line[:, :, None])

        # 3. 顶点（只在稀疏模式下画；稠密时点会盖住折线）
        if 0 < n <= iw:
            _blit_dots(sub, xe, np.clip(ys, 0, ih - 1), colors,
                       3 if n <= 220 else 2)


class MirrorRenderer(StyleRenderer):
    """对称声波图（Mirrored Audio Waveform）。

    以可视区水平中轴 ``y_mid = y0 + H/2`` 为镜像面，每个元素画一根**上下
    对称**的声波柱：半高 ``h_i = max(2, norm_i × 0.46H)``。

    相比普通柱状图，这种画法的好处是「信息密度翻倍」—— 一屏之内同时能看
    到上下两半的起伏包络，有序时收敛成一只平滑对称的梭形号角，视觉上比
    单侧柱状图更像「完成」。
    """

    key = "mirror"
    hot_markers = True
    _HALF = 0.46

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        self._grid(buf, y0, bh, 4 if aux else 6)
        ratio, col, inbar = self._column_bars(values, frame.n_max)
        colors = self._array_colors(values, frame, aux)
        colcolors = colors[col]

        half = np.maximum(1.5, ratio * (self._HALF * bh))
        rows = np.arange(bh, dtype=np.float32)[:, None]
        dist = np.abs(rows - np.float32((bh - 1) * 0.5))
        mask = (dist <= half[None, :]) & inbar[None, :]
        sub = buf[y0:y0 + bh]
        np.copyto(sub, colcolors[None, :, :], where=mask[:, :, None])

        # 中轴基准线：声波图的「零位」，也是上下对称的视觉锚点。
        # 用比网格线更亮的灰 —— 这是「对称」这一信息唯一的载体，
        # 若与背景几乎同色，整幅图看上去就和普通柱状图没区别。
        mid = bh // 2
        if 0 <= mid < bh:
            sub[mid, :] = C_RING

        # 高亮元素在上下两个端点各点一颗「灯」，快放时也能锁定是谁在动
        hot = frame.hot or {}
        if hot and n <= 4096:
            idx = np.fromiter((i for i in hot if 0 <= i < n), dtype=np.int64)
            if idx.size:
                xs = np.clip(np.rint((idx + 0.5) * self.w / n).astype(np.int64),
                             0, self.w - 1)
                hh = np.maximum(
                    2.0, _norm01(values[idx], frame.n_max) * (self._HALF * bh))
                cy = (bh - 1) * 0.5
                lamp = colors[idx]
                _blit_dots(sub,
                           np.concatenate([xs, xs]),
                           np.rint(np.concatenate([cy - hh, cy + hh])
                                   ).astype(np.int64),
                           np.concatenate([lamp, lamp]), 3)


class DisparityRenderer(StyleRenderer):
    """极坐标偏差收缩环（Disparity Ring / Radial Error Dots）。

    圆周角 = 当前索引 ``i``，半径 = **当前位置与有序位置的距离误差**：

    ``err_i = min(|i - t_i|, N - |i - t_i|) / (N/2)``
    ``r_i = R_max × (1 - 0.82 × err_i)``

    于是「站错位置」的元素会向圆心塌陷，站对的贴在圆周上。画面上直接读得出
    「还有多少元素没回到自己的位置」—— 这是柱状图给不了的信息。

    外圈画暗色参考环，每个点再从圆周锚点拉一条半透明牵引线到实际位置，
    乱序时是一圈向内收束的细丝，排好后细丝全部缩成 0 长、整圈归一。
    """

    key = "disparity"
    _RFRAC = 0.44
    _MAX_LINE = 512
    _MAX_DOT = 3072
    _FLOOR = 0.22

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        floor = self._FLOOR if (bh >= 200 and not aux) else 0.0
        stage = bh - int(round(bh * floor))
        sub = buf[y0:y0 + stage]
        cx = (self.w - 1) * 0.5
        cy = (stage - 1) * 0.5
        # 规范书：R_max = 0.44·min(W, H)（**不是** 0.44 倍的半径），
        # 直径 0.88·min 刚好在竖直方向留出一线边距。
        R = max(10.0, min(self.w, stage) * self._RFRAC)
        self._ring(sub, cx, cy, R)

        norm = _norm01(values, frame.n_max)
        tgt = norm * (n - 1)
        i = np.arange(n, dtype=np.float64)
        d = np.abs(i - tgt)
        d = np.minimum(d, n - d) / max(1.0, n * 0.5)
        err = np.clip(d, 0.0, 1.0)
        rad = (R * (1.0 - 0.82 * err)).astype(np.float32)

        theta = (2.0 * math.pi * i / n - math.pi * 0.5).astype(np.float32)
        ct, st = np.cos(theta), np.sin(theta)
        px = cx + rad * ct
        py = cy + rad * st
        ax = cx + R * ct
        ay = cy + R * st

        colors = self._array_colors(values, frame, aux)
        li = self._pick(n, self._MAX_LINE, frame, aux)
        # N 小的时候每根牵引线都细得像根汗毛，整幅图会只剩一把看不见的粉。
        # 小 N 提高透明度、大 N 压低，保证两种规模下「向心收束」都读得出来。
        _draw_segments(sub, ax[li], ay[li], px[li], py[li],
                       colors[li], alpha=150 if n <= 256 else 92)

        di = self._pick(n, self._MAX_DOT, frame, aux)
        _blit_dots(sub, np.rint(px[di]).astype(np.int64),
                   np.rint(py[di]).astype(np.int64), colors[di],
                   4 if di.size <= 160 else (3 if di.size <= 900 else 2))
        if floor > 0.0:
            self._reflect_floor(buf, y0, bh, stage,
                                bottom=self._content_bottom(buf, y0, stage))


class PyramidRenderer(StyleRenderer):
    """居中金字塔堆叠图（Centered Horizontal Pyramid）。

    从上到下按索引 ``0 → N-1`` 堆水平横条，沿水平中轴左右对称：
    ``y_i = y0 + i·H/N``，半宽 ``w_i = max(2, norm_i × 0.45W)``。

    它是一个「侧放的柱状图」，但正因为横条是居中的，乱序时读起来像一枝
    参差生长的芦苇，有序时收敛成一面严整的三角帆 —— 形态变化比竖向柱状图
    更强烈，也更容易在竖屏 / 分屏布局里用满空间。
    """

    key = "pyramid"
    _HALF = 0.45

    def _row_bands(self, ratio: np.ndarray, bh: int) -> tuple:
        """把 n 个元素映射到 ``bh`` 个屏幕行（与 ``_column_bars`` 镜像）。"""
        n = ratio.size
        if n <= bh:
            edges = np.linspace(0.0, float(bh), n + 1)
            r0 = np.floor(edges[:-1]).astype(np.int64)
            r1 = np.maximum(np.floor(edges[1:]).astype(np.int64), r0 + 1)
            gap = 1 if (bh / max(1, n)) >= 3.0 else 0
            ra = np.minimum(r0 + gap, bh - 1)
            rb = np.minimum(np.maximum(r1 - gap, ra + 1), bh)
            rows = np.arange(bh)
            elem = np.clip(np.searchsorted(ra, rows, side="right") - 1, 0, n - 1)
            inrow = (rows >= ra[elem]) & (rows < rb[elem])
            return ratio[elem], elem, inrow

        start_of = (np.arange(n) * bh) // n
        starts = np.clip(np.searchsorted(start_of, np.arange(bh), side="left"),
                         0, n - 1)
        return (np.maximum.reduceat(ratio, starts), starts,
                np.ones(bh, dtype=bool))

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        self._grid(buf, y0, bh, 4 if aux else 6)
        ratio = _norm01(values, frame.n_max)
        rowr, elem, inrow = self._row_bands(ratio, bh)
        colors = self._array_colors(values, frame, aux)

        half = np.maximum(1.5, rowr * (self._HALF * self.w))
        xm = (self.w - 1) * 0.5
        cols = np.arange(self.w, dtype=np.float32)[None, :]
        mask = ((cols >= (xm - half)[:, None])
                & (cols <= (xm + half)[:, None])
                & inrow[:, None])
        sub = buf[y0:y0 + bh]
        np.copyto(sub, colors[elem][:, None, :], where=mask[:, :, None])

        # 中轴：横条是左右对称铺开的，没有这根线的话「居中」这件事读不出来，
        # 看上去就像一堆左端参差、右端也参差的横线。
        xm_i = int(min(self.w - 1, max(0, xm)))
        sub[:, xm_i] = C_RING


class ResidualRenderer(StyleRenderer):
    """残差位移火柴图（Displacement Error Stems）。

    先画一条「完全有序时的理想对角线」，再把每个元素当前位置到理想位置的
    垂直偏差画成一根火柴杆：

    ``y_ideal,i = y0 + 0.95H - i/(N-1) · 0.90H``
    ``y_actual,i = y0 + 0.95H - norm_i · 0.90H``

    杆越长 = 错得越远。排好序时**所有杆长同时缩为 0**，圆头严丝合缝落在
    对角线上 —— 这是所有样式里「完成」语义最强的一个。
    """

    key = "residual"
    hot_markers = True
    _MAXN = 1024

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        self._grid(buf, y0, bh, 4 if aux else 6)
        sub = buf[y0:y0 + bh]
        pad = 8
        top_y = float(pad)
        bot_y = float(max(pad + 4, bh - pad))
        span = bot_y - top_y
        colors = self._array_colors(values, frame, aux)
        idx = self._pick(n, self._MAXN, frame, aux)
        m = idx.size
        denom = float(max(1, n - 1))
        norm = _norm01(values[idx], frame.n_max)

        xs = np.clip(np.rint((idx + 0.5) * self.w / n).astype(np.int64),
                     0, self.w - 1)
        y_ideal = bot_y - (idx / denom) * span
        y_actual = bot_y - norm * span

        # 理想对角线：细暗线，作为「排好后该长什么样」的参照系
        dx = np.arange(self.w, dtype=np.int64)
        dy = np.rint(bot_y - (dx.astype(np.float64)
                              / max(1.0, float(self.w - 1))) * span
                     ).astype(np.int64)
        _blit_dots(sub, dx, dy,
                   np.tile(np.array(C_RING, dtype=_U8), (self.w, 1)), 1)

        # 同一屏幕列可能落多个元素（N > 画布宽）：按列取极值合成一根杆
        order = np.argsort(xs, kind="stable")
        uniq, starts = np.unique(xs[order], return_index=True)
        lo_s = np.minimum(y_actual[order], y_ideal[order])
        hi_s = np.maximum(y_actual[order], y_ideal[order])
        ylo = np.minimum.reduceat(lo_s, starts)
        yhi = np.maximum.reduceat(hi_s, starts)
        rows = np.arange(bh, dtype=np.int64)[:, None]
        band = (rows >= ylo[None, :]) & (rows <= yhi[None, :])
        yy, cc = np.nonzero(band)
        if yy.size:
            flat = yy * self.w + uniq[cc]
            sub.reshape(-1, 3)[flat] = colors[order][starts][cc]

        # 实际位置的圆头：完成时所有圆头连成一条线
        _blit_dots(sub, xs, np.rint(y_actual).astype(np.int64), colors[idx],
                   4 if m <= 256 else (3 if m <= 512 else 2))


class WaterfallRenderer(StyleRenderer):
    """时空瀑布流 / 历史轨迹图（Spacetime Waterfall / Kymograph）。

    上方 78% 是一块**随时间滚动**的二维历史图（横轴 = 数组索引，纵轴 =
    时间帧），下方 22% 是当前实时迷你柱状图。

    每推进一帧就往缓冲底部压入一行「这一刻每个索引是什么颜色」，旧行整体
    上移。于是一眼就能看到整场排序的**演化形状**：

    * 快速排序 → 分形的三角形（每次划分把区间切成两半）
    * 归并排序 → 规则的编织水波（自底向上逐层变宽）
    * 基数排序 → 水平分层色带（每趟按一位重新分桶）
    * 希尔排序 → 斜向条纹（间隔序列决定的交错轨迹）

    实现要点：不用 ``np.roll``（每帧都要整块重新分配、拷贝 4 MB），而是
    维护一个**环形缓冲 + 写指针**，展开时只做两段连续切片拷贝。这样 1080P
    下单帧开销稳定在 1 ms 左右。
    """

    key = "waterfall"
    #: 上方历史区的占比
    _SPLIT = 0.78

    def __init__(self, width: int, height: int) -> None:
        self._hist: Optional[np.ndarray] = None
        self._hist_key: Optional[Tuple[int, int]] = None
        self._head = 0
        self._last_step = -1
        self._last_n = -1
        super().__init__(width, height)

    def _on_resize(self) -> None:
        self._hist = None
        self._hist_key = None

    def reset(self) -> None:
        """丢掉历史缓冲（切换算法 / 重新开始时由外部调用）。"""
        self._hist = None
        self._hist_key = None
        self._head = 0
        self._last_step = -1
        self._last_n = -1

    def _history(self, hist_h: int) -> np.ndarray:
        key = (self.w, hist_h)
        if self._hist is None or self._hist_key != key:
            self._hist = np.empty((hist_h, self.w, 3), dtype=_U8)
            self._hist[:, :] = C_BG
            self._hist_key = key
            self._head = 0
            self._last_step = -1
        return self._hist

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        ratio, col, inbar = self._column_bars(values, frame.n_max)
        colors = self._array_colors(values, frame, aux)

        if aux:
            # 辅助数组没有「历史」概念，老老实实画一条实时柱状图
            self._grid(buf, y0, bh, 3)
            self._fill_bars(buf, y0, bh, ratio, colors[col], inbar)
            return

        hist_h = min(bh - 4, max(8, int(round(bh * self._SPLIT))))
        mini_h = bh - hist_h - 3
        hist = self._history(hist_h)

        step = int(frame.step)
        if (n != self._last_n or step == 0
                or (step >= 0 and self._last_step >= 0 and step < self._last_step)):
            # 换算法 / 回到 0 / 往回拖进度条 —— 旧轨迹必须丢掉，
            # 否则会和新轨迹拼在一起，看着像残影。
            hist[:, :] = C_BG
            self._head = 0
        self._last_n = n
        if step >= 0:
            self._last_step = step

        row = colors[col].astype(np.float32)
        # 亮度随数值走：高值列亮、低值列暗。否则每一行都是同一条彩虹，
        # 瀑布会退化成毫无信息量的横条纹。
        row *= (0.30 + 0.70 * ratio)[:, None]
        hot = frame.hot or {}
        if hot:
            for i, kind in hot.items():
                if 0 <= i < n:
                    p = min(self.w - 1, (i * self.w) // n)
                    row[p] = HOT_COLORS.get(kind, C_CMP)
        hist[self._head] = np.clip(row, 0, 255).astype(_U8)
        self._head = (self._head + 1) % hist_h

        # 环形缓冲按「旧 → 新」展开成自上而下的瀑布（两段连续拷贝）
        view = buf[y0:y0 + hist_h]
        k = self._head
        if k:
            view[:hist_h - k] = hist[k:]
            view[hist_h - k:] = hist[:k]
        else:
            view[:] = hist

        if mini_h >= 6:
            sep = y0 + hist_h
            if 0 <= sep < buf.shape[0]:
                buf[sep, :] = C_DIVIDER
            my0 = sep + 1
            self._grid(buf, my0, mini_h, 3)
            self._fill_bars(buf, my0, mini_h, ratio, colors[col], inbar)


class LoomRenderer(StyleRenderer):
    """平行双轨织布机 / 逆序对连线图（Parallel Loom）。

    上半导轨按**当前索引**排布，下半导轨按**目标有序位置**排布，每个元素画
    一条从 ``(x_curr, y_top)`` 到 ``(x_target, y_bot)`` 的丝线。
    **两线的每一个交叉点 = 一对逆序元素**，逆序对数量直接变成画面上的
    线的缠绕程度。

    乱序时是一台织出漫天斜丝的织布机；每次交换都会解开一处交叉；完全排好
    序时 ``x_curr = x_target``，所有斜线瞬间立正，化作一排严格垂直的平行
    光柱。这是所有样式里「逆序对」这个概念最直观的一次视觉化。
    """

    key = "loom"
    _MAXN = 512

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        sub = buf[y0:y0 + bh]
        colors = self._array_colors(values, frame, aux)
        idx = self._pick(n, self._MAXN, frame, aux)
        m = idx.size
        norm = _norm01(values[idx], frame.n_max)
        denom = float(max(1, n - 1))

        pad = 0.04 * self.w
        span = 0.92 * self.w
        ytop = 0.15 * bh
        ybot = 0.85 * bh

        # 两条导轨
        ti = int(round(ytop))
        bi = int(round(ybot))
        if 0 <= ti < bh:
            sub[ti, :] = C_RULER
        if 0 <= bi < bh:
            sub[bi, :] = C_RULER

        xc = (pad + (idx.astype(np.float32) / denom) * span).astype(np.float32)
        xt = (pad + norm * span).astype(np.float32)
        top = np.full(m, ytop, dtype=np.float32)
        bot = np.full(m, ybot, dtype=np.float32)

        flags = self._hot_flags(idx, frame, aux)
        cool = ~flags
        if cool.any():
            _draw_segments(sub, xc[cool], top[cool], xt[cool], bot[cool],
                           colors[idx][cool], alpha=140)
        if flags.any():
            _draw_segments(sub, xc[flags], top[flags], xt[flags], bot[flags],
                           colors[idx][flags], alpha=255, thick=2)

        _blit_dots(sub, np.rint(xc).astype(np.int64),
                   np.rint(top).astype(np.int64), colors[idx],
                   4 if m <= 96 else 3)


class DreamcatcherRenderer(StyleRenderer):
    """圆环错位捕梦网（Circular Disparity Chords / Dreamcatcher Web）。

    在半径 ``R = 0.44·min(W, H)`` 的圆周上取两点：起点是元素的**当前角**
    ``θ_curr = 2πi/N``，终点是它的**目标角** ``θ_target = 2π·norm_i``，
    两点之间拉一条半透明彩色弦。

    弦的长度就是「这个元素偏离目标位置有多远」。未排序时圆环内部交织出一
    整张几何万花筒弦网；随着排序推进，弦不断向圆周收缩；排好序时
    ``θ_curr = θ_target``，内部网格彻底消失，只剩一圈纯净圆环。
    """

    key = "dreamcatcher"
    _MAXN = 512
    _RFRAC = 0.44
    _FLOOR = 0.22

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        floor = self._FLOOR if (bh >= 200 and not aux) else 0.0
        stage = bh - int(round(bh * floor))
        sub = buf[y0:y0 + stage]
        cx = (self.w - 1) * 0.5
        cy = (stage - 1) * 0.5
        # 规范书：R_max = 0.44·min(W, H)（**不是** 0.44 倍的半径），
        # 直径 0.88·min 刚好在竖直方向留出一线边距。
        R = max(10.0, min(self.w, stage) * self._RFRAC)
        self._ring(sub, cx, cy, R)

        colors = self._array_colors(values, frame, aux)
        idx = self._pick(n, self._MAXN, frame, aux)
        m = idx.size
        norm = _norm01(values[idx], frame.n_max)

        th_c = (2.0 * math.pi * idx / n - math.pi * 0.5).astype(np.float32)
        th_t = (2.0 * math.pi * norm - math.pi * 0.5).astype(np.float32)
        x1 = cx + R * np.cos(th_c)
        y1 = cy + R * np.sin(th_c)
        x2 = cx + R * np.cos(th_t)
        y2 = cy + R * np.sin(th_t)

        flags = self._hot_flags(idx, frame, aux)
        cool = ~flags
        if cool.any():
            _draw_segments(sub, x1[cool], y1[cool], x2[cool], y2[cool],
                           colors[idx][cool], alpha=110)
        if flags.any():
            _draw_segments(sub, x1[flags], y1[flags], x2[flags], y2[flags],
                           colors[idx][flags], alpha=255, thick=2)

        _blit_dots(sub, np.rint(x1).astype(np.int64),
                   np.rint(y1).astype(np.int64), colors[idx],
                   4 if m <= 96 else 3)
        if floor > 0.0:
            self._reflect_floor(buf, y0, bh, stage,
                                bottom=self._content_bottom(buf, y0, stage))


class TreeRenderer(StyleRenderer):
    """隐式完全二叉树拓扑图（Implicit Binary Tree / Heap Topology）。

    把下标 ``0 … M-1``（``M = min(N, 255)``，恰好 8 层满树）映射成完全
    二叉树：父节点 ``⌊(i-1)/2⌋``，层 ``d = ⌊log2(i+1)⌋``，层内第
    ``k = i - (2^d - 1)`` 个。

    先画所有父子连线（堆排序的下沉 / 上浮路径就是沿这些边走），再画实心
    圆节点，半径 ``3 + norm_i × 6``。

    这是唯一一个「把堆的物理结构画出来」的样式：堆排序里每一次
    ``sift-down`` 都能看到高亮沿树边一层层向下渗透，二叉堆不再是抽象概念。
    """

    key = "tree"
    _MAXN = 255

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        n = values.size
        if n == 0:
            return
        m = int(min(n, self._MAXN))
        if m < 1:
            return
        sub = buf[y0:y0 + bh]
        colors = self._array_colors(values, frame, aux)[:m]

        nodes = np.arange(m, dtype=np.int64)
        d = np.floor(np.log2(nodes + 1.0)).astype(np.int64)
        depth = max(1, int(d[-1]) + 1)
        cap = (1 << d).astype(np.float64)
        k = (nodes - (cap - 1)).astype(np.float64)

        xs = ((k + 0.5) / cap * self.w).astype(np.float32)
        ys = (0.08 * bh + (d.astype(np.float32) / float(max(1, depth - 1)))
              * 0.84 * bh).astype(np.float32)

        # 1. 父子连线（正常暗灰；两端任意一端高亮则染成该元素的色并加粗）
        if m > 1:
            par = (nodes[1:] - 1) // 2
            flags = self._hot_flags(nodes, frame, aux)
            act = flags[1:] | flags[par]
            if (~act).any():
                cnt = int((~act).sum())
                _draw_segments(sub, xs[par[~act]], ys[par[~act]],
                               xs[1:][~act], ys[1:][~act],
                               np.tile(np.array(C_RULER, dtype=_U8), (cnt, 1)))
            if act.any():
                _draw_segments(sub, xs[par[act]], ys[par[act]],
                               xs[1:][act], ys[1:][act],
                               colors[1:][act], thick=2)

        # 2. 节点圆盘（半径随数值 3 → 9 像素）
        rad = 3.0 + _norm01(values[:m], frame.n_max) * 6.0
        # 半径还要按「同层横向间距」封顶：8 层满树最底层有 128 个节点，
        # 640 px 画布上间距只有 5 px，若照 3 + norm·6 硬画，那一层会糊成
        # 一条连续色带，节点和树边全都消失。
        rad = np.minimum(rad, np.maximum(1.4, (self.w / cap) * 0.42))
        _blit_discs(sub, np.rint(xs).astype(np.int64),
                    np.rint(ys).astype(np.int64), colors, rad)

# --------------------------------------------------------------------------
# 6. 次世代矢量绘制层（Instruction3 第一节「四大高清画质管线」）
# --------------------------------------------------------------------------
# 为什么要有这一层
# ----------------
# 前面 12 种样式是「NumPy 光栅管线」：把成千上万个同构图元（柱子、点、线）
# 一次性算成坐标再按掩码整块写缓冲。它快得离谱（N=10000 也能 100+ FPS），
# 但它**画不了**抗锯齿曲线、渐变、半透明叠加 —— 而这些恰恰是「高清感」的
# 全部来源。硬用 NumPy 手写 AA 贝塞尔是给自己挖坑。
#
# 所以新增这一层：把绘图区包成一张 ``ARGB32_Premultiplied`` 的 QImage
# （**直接指向 NumPy 缓冲，零拷贝**），交给 QPainter 用真正的矢量光栅器去画，
# 收尾时再一次性转回 RGB888 交给屏幕 / FFmpeg。于是：
#
# * 抗锯齿、渐变、加色混合全部白拿，且都是 C++ 速度；
# * 导出器仍然只认 ``(H, W, 3) uint8``，**"屏上所见 = 导出所得"这条规矩不破**；
# * 选 ``ARGB32_Premultiplied`` 而不是 ``RGB888`` 是有原因的：QPainter 的
#   光栅引擎原生格式就是它，直接往 RGB888 上画会被 Qt 内部先转成 ARGB 再
#   转回来，一帧多两次全画布转换（1080P 下约 8 ms）。
#
# 代价是每帧末尾一次 ARGB→RGB 的三通道拷贝：1180×620 约 0.6 ms，
# 1920×1080 约 2.0 ms —— 完全在预算内。
_BG_U32 = 0xFF000000 | (C_BG[0] << 16) | (C_BG[1] << 8) | C_BG[2]

_QCACHE: Dict[int, QColor] = {}
_QCACHE_A: Dict[Tuple[int, int], QColor] = {}


def _qc(rgb: Sequence[int]) -> QColor:
    """``(r, g, b)`` → QColor（带缓存）。"""
    k = (int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2])
    c = _QCACHE.get(k)
    if c is None:
        if len(_QCACHE) > 4096:
            _QCACHE.clear()
        c = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
        _QCACHE[k] = c
    return c


def _qca(rgb: Sequence[int], alpha: int) -> QColor:
    """带 alpha 的 QColor（带缓存）—— 光晕层每帧要用几百次。"""
    a = int(max(0, min(255, alpha)))
    k = ((int(rgb[0]) << 16) | (int(rgb[1]) << 8) | int(rgb[2]), a)
    c = _QCACHE_A.get(k)
    if c is None:
        if len(_QCACHE_A) > 4096:
            _QCACHE_A.clear()
        c = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
        c.setAlpha(a)
        _QCACHE_A[k] = c
    return c


def _mix(rgb: Sequence[int], k: float) -> RGB:
    """按比例缩放亮度（>1 提亮 / <1 压暗），结果夹在 0~255。"""
    return (int(max(0, min(255, rgb[0] * k))),
            int(max(0, min(255, rgb[1] * k))),
            int(max(0, min(255, rgb[2] * k))))


class VectorRenderer(StyleRenderer):
    """矢量绘制基类：QPainter 直接往 NumPy 缓冲上画。"""

    hot_markers = False
    #: 底部留给「黑曜石镜面地面」的比例（0 = 不启用）
    _FLOOR = 0.0

    def __init__(self, width: int, height: int) -> None:
        self._argb: Optional[np.ndarray] = None
        self._argb_u8: Optional[np.ndarray] = None
        self._qimg: Optional[QImage] = None
        super().__init__(width, height)

    def _on_resize(self) -> None:
        h, w = self.h, self.w
        self._argb = np.empty((h, w), dtype=np.uint32)
        self._argb[:, :] = _BG_U32
        self._argb_u8 = self._argb.view(np.uint8).reshape(h, w, 4)
        self._qimg = QImage(self._argb.data, w, h, w * 4,
                            QImage.Format_ARGB32_Premultiplied)
        self._on_vector_resize()

    def _on_vector_resize(self) -> None:
        """钩子：子类可在此预计算与画布尺寸相关的锚点。"""

    def _paint_array(self, buf, y0, bh, values, frame, aux) -> None:
        if values.size == 0 or self._qimg is None or bh < 6:
            return
        p = QPainter()
        if not p.begin(self._qimg):
            return
        # 规范书要求的三项渲染提示，一个不能少：
        # Antialiasing         —— 所有矢量边缘抗锯齿
        # TextAntialiasing     —— HUD / 标注文字灰度抗锯齿
        # SmoothPixmapTransform—— 位图缩放走双线性而不是最近邻
        p.setRenderHints(QPainter.Antialiasing
                         | QPainter.TextAntialiasing
                         | QPainter.SmoothPixmapTransform)
        p.translate(0.0, float(y0))
        p.setClipRect(QRectF(0.0, 0.0, float(self.w), float(bh)))
        # ARGB 缓冲跨帧复用，必须先整块复位，否则上一帧的图形会透出来
        p.fillRect(QRectF(0.0, 0.0, float(self.w), float(bh)), _qc(C_BG))
        try:
            self._paint_vector(p, bh, values, frame, aux)
        finally:
            p.end()
        u8 = self._argb_u8[y0:y0 + bh]
        dst = buf[y0:y0 + bh]
        dst[:, :, 0] = u8[:, :, 2]
        dst[:, :, 1] = u8[:, :, 1]
        dst[:, :, 2] = u8[:, :, 0]
        if self._FLOOR > 0.0:
            self._reflect_floor(buf, y0, bh, self._stage(bh, self._FLOOR))

    def _paint_vector(self, p: QPainter, bh: int, values: np.ndarray,
                      frame: VizFrame, aux: bool) -> None:
        raise NotImplementedError

    # ---- 公共小工具 ------------------------------------------------------
    @staticmethod
    def _stage(bh: int, floor: float = 0.0) -> int:
        """主绘图区高度（底部 ``floor`` 比例留给镜面地面）。"""
        if floor <= 0.0:
            return bh
        return max(8, int(round(bh * (1.0 - floor))))


class SliceRenderer(VectorRenderer):
    """特殊模式 1：高清图像切片还原（HD Image Slice / Glitch Restoration）。

    把一张高清画作切成 N 条竖切片，**第 i 个位置显示第 rank_i 号切片**。
    因为切片内容本身就带着「应该待在哪儿」的信息，所以：

    * 乱序时是一幅被拦腰切断、错位重排的故障艺术画；
    * 排序完成时，所有切片各归其位，整幅画**完美复原**。

    这是全部 18 种视图里唯一一个「完成态不是几何图形、而是一张画」的模式，
    演示时的冲击力最强。竖切宽度很窄时（N 大）单条切片只有 1~2 像素，
    因此拼接本身用一次 NumPy 花式索引整块完成，只有「故障错位」「激光扫描」
    这些特效才逐个走 QPainter。
    """

    key = "slice"
    #: 一次最多给几个切片做故障错位（再多就是纯烧性能了）
    _MAX_GLITCH = 4

    def _on_vector_resize(self) -> None:
        self._rows_cache: Tuple[Tuple[int, int], np.ndarray] = ((0, 0),
                                                               np.zeros(1, int))
        self._qsrc: Optional[QImage] = None
        self._qsrc_key: Optional[int] = None

    def _rows_for(self, bh: int, sh: int) -> np.ndarray:
        key = (bh, sh)
        if self._rows_cache[0] != key:
            self._rows_cache = (key,
                                np.rint(np.linspace(0, sh - 1, bh)).astype(np.int64))
        return self._rows_cache[1]

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        src = slice_source_array()
        if src is None:
            return
        sh, sw = int(src.shape[0]), int(src.shape[1])
        n = int(values.size)
        rows = self._rows_for(bh, sh)
        cols = np.arange(self.w, dtype=np.int64)
        # 每个屏幕列归属哪个元素（与 _column_bars 同一套切分口径）
        elem = np.minimum(n - 1, (cols * n) // self.w)
        rank = _index_of(values, frame.n_max).astype(np.float64)
        denom = float(max(1, int(frame.n_max)))
        # **片内也要保留横向细节**：规范书给的写法是每片拷贝一个宽度为
        # ``img_w / N`` 的源矩形，而不是「一片只取源图的一列」。后者在
        # N < 画布列数时会把一条切片拉成一条纯色竖条，整幅画看上去就是
        # 一堆色带 + 锯齿状的硬边。这里用 ``rank + 片内相对位置`` 做连续
        # 采样，等价于逐片 drawPixmap，但仍然是**一次**花式索引。
        slot = self.w / float(n)
        frac = (cols - elem * slot) / slot
        scols = np.clip(np.rint((rank[elem] + frac) * (sw / max(1.0, denom))),
                        0, sw - 1).astype(np.int64)
        tile = np.ascontiguousarray(src[rows[:, None], scols[None, :]])
        qi = QImage(tile.data, self.w, bh, self.w * 3, QImage.Format_RGB888)
        p.drawImage(QRectF(0.0, 0.0, float(self.w), float(bh)), qi)
        self._paint_glitch(p, bh, n, frame, aux, qi)

    def _paint_glitch(self, p: QPainter, bh: int, n: int, frame: VizFrame,
                      aux: bool, qi: QImage) -> None:
        hot = (frame.hot_aux if aux else frame.hot) or {}
        items = [(i, k) for i, k in hot.items() if 0 <= i < n]
        if not items:
            return
        items = items[: self._MAX_GLITCH]
        ph = float(frame.t) * 0.55 % 1.0
        for i, kind in items:
            col = HOT_COLORS.get(kind, C_CMP)
            x0 = i * self.w / float(n)
            slot = max(2.0, self.w / float(n))
            # 1) 纵向激光扫描罩：一条从暗到亮再到暗的霓虹光带
            g = QLinearGradient(0.0, 0.0, 0.0, float(bh))
            g.setColorAt(0.0, _qca(col, 0))
            g.setColorAt(max(0.02, ph - 0.20), _qca(col, 24))
            g.setColorAt(ph, _qca(col, 118))
            g.setColorAt(min(0.98, ph + 0.20), _qca(col, 24))
            g.setColorAt(1.0, _qca(col, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(x0, 0.0, slot, float(bh)))
            # 2) 故障艺术：把这条切片整体上下错开 8 px 再贴一次
            off = 8.0 if i % 2 == 0 else -8.0
            p.setOpacity(0.88)
            p.drawImage(QRectF(x0, off, slot, float(bh)), qi,
                        QRectF(x0, 0.0, slot, float(bh)))
            p.setOpacity(1.0)
            # 3) 霓虹描边：让「正在动的是哪一条」一眼可见
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qca(col, 180), 1))
            p.drawLine(QPointF(x0 + 0.5, 0.0), QPointF(x0 + 0.5, float(bh)))
            p.drawLine(QPointF(x0 + slot - 0.5, 0.0),
                       QPointF(x0 + slot - 0.5, float(bh)))


class ArcRenderer(VectorRenderer):
    """特殊模式 2：霓虹拱桥光弧与镜面交响（Neon Bezier Arcs）。

    参照《The Shape of Song》的数据艺术手法：全部元素是站在一条发光基准弦
    上的晶体节点，**元素与它的目标位置之间架一道半圆霓虹拱桥**，桥的跨度
    就是「这个东西偏离了多远」。

    乱序时满屏是层层叠叠的彩色光弧，像一座跨海大桥群；排序推进时弧线一根
    根塌缩成点；排好序时整屏只剩一条笔直的发光弦和 N 颗安静的灯。
    "最近 20 次操作"另外维护成一条高频光弧队列 —— 它保证即便在 2000x 的
    快放档下，你也能看清「刚刚是哪两根在动」。
    """

    key = "arcs"
    _MAXN = 128
    _KEEP = 20
    _DISP = 40

    def __init__(self, width: int, height: int) -> None:
        self._recent: List[Tuple[int, int, str]] = []
        self._last_step = -1
        self._last_n = -1
        super().__init__(width, height)

    def reset_trail(self) -> None:                      # noqa: D102 (见基类)
        self._recent.clear()
        self._last_step = -1
        self._last_n = -1
        super().reset_trail()

    def _track(self, frame: VizFrame, n: int) -> None:
        """把「刚刚发生的那一次操作」压进最近光弧队列。"""
        step = int(frame.step)
        if n != self._last_n or step == 0 or (0 <= step < self._last_step):
            self._recent.clear()
            self._last_n = n
        hot = frame.hot or {}
        if step != self._last_step and len(hot) >= 2:
            ks = list(hot.items())
            kind = ks[0][1]
            if all(k == kind for _, k in ks):
                idx = [i for i, _ in ks]
                self._recent.append((min(idx), max(idx), kind))
                if len(self._recent) > self._KEEP:
                    del self._recent[0]
        self._last_step = step

    @staticmethod
    def _arc(p: QPainter, xa: float, y: float, xb: float, h: float,
             up: bool, rgb: Sequence[int], alpha: int, width: int) -> None:
        """半椭圆拱桥。控制点取 ``4/3·h`` 是三次贝塞尔逼近半圆的标准系数。"""
        if abs(xb - xa) < 1.0:
            return
        path = QPainterPath(QPointF(xa, y))
        cy = y - h * 1.3333 if up else y + h * 1.3333
        c1 = xa + (xb - xa) * 0.28
        c2 = xa + (xb - xa) * 0.72
        path.cubicTo(c1, cy, c2, cy, xb, y)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qca(rgb, alpha), width))
        p.drawPath(path)

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        n = int(values.size)
        self._track(frame, n)
        stage = 0.70 * bh
        pad = 0.035 * self.w
        span = self.w - 2.0 * pad
        denom = float(max(1, n - 1))
        colors = self._array_colors(values, frame, aux)

        def xpos(t: np.ndarray) -> np.ndarray:
            return pad + np.asarray(t, dtype=np.float64) / denom * span

        # ---- 1. 基准弦（发光横线，中间最亮）----
        g = QLinearGradient(0.0, 0.0, float(self.w), 0.0)
        g.setColorAt(0.0, _qca(C_BOUNDARY, 26))
        g.setColorAt(0.45, _qca(C_BOUNDARY, 170))
        g.setColorAt(0.55, _qca(C_BOUNDARY, 170))
        g.setColorAt(1.0, _qca(C_BOUNDARY, 26))
        p.setPen(QPen(QBrush(g), 1))
        p.drawLine(QPointF(0.0, stage), QPointF(float(self.w), stage))

        idx = self._pick(n, self._MAXN, frame, aux)
        norm = _norm01(values[idx], frame.n_max)
        tpos = norm * denom
        dev = np.abs(idx.astype(np.float64) - tpos)

        # ---- 2. 位移拱桥（挑偏离最远的 40 个画，跨度即误差）----
        order = np.argsort(-dev)[: self._DISP]
        for k in order:
            if dev[k] < 1.1:
                continue
            xa = float(xpos(np.float64(idx[k])))
            xb = float(xpos(np.float64(tpos[k])))
            h_arc = min(0.62 * bh, 0.48 * abs(xb - xa))
            if h_arc < 3.0:
                continue
            c = colors[idx[k]]
            self._arc(p, xa, stage, xb, h_arc, True, c, 120, 1)
            # 水面倒影拱：控制点只取 0.35 倍拱高，透明度再压到 28%
            self._arc(p, xa, stage, xb, h_arc * 0.35, False, c, 34, 1)

        # ---- 3. 最近操作队列（高频光弧 + 加色辉光）----
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for k, (a, b, kind) in enumerate(self._recent):
            if not (0 <= a < n and 0 <= b < n):
                continue
            xa = float(xpos(np.float64(a)))
            xb = float(xpos(np.float64(b)))
            h_arc = min(0.62 * bh, 0.48 * abs(xb - xa))
            if h_arc < 3.0:
                continue
            col = HOT_COLORS.get(kind, C_CMP)
            age = len(self._recent) - k
            if age <= 5:                      # 最新的 5 根：宽画笔 Bloom + 白芯
                self._arc(p, xa, stage, xb, h_arc, True, col, 42, 5)
                self._arc(p, xa, stage, xb, h_arc, True, (255, 255, 255), 235, 1)
            else:
                self._arc(p, xa, stage, xb, h_arc, True, col,
                          max(48, 205 - age * 13), 1)
            self._arc(p, xa, stage, xb, h_arc * 0.35, False, col, 30, 1)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # ---- 4. 晶体节点 ----
        sx = xpos(idx.astype(np.float64))
        for k in range(idx.size):
            r = 2.0 + float(norm[k]) * 5.0
            p.setPen(Qt.NoPen)
            p.setBrush(_qc(colors[idx[k]]))
            p.drawEllipse(QPointF(float(sx[k]), stage), r, r)
        # 高亮节点加一圈加色光晕，「谁在动」在快放时也能锁定
        hot = frame.hot or {}
        if hot:
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            for i, kind in hot.items():
                if not (0 <= i < n):
                    continue
                xi = float(xpos(np.float64(i)))
                col = HOT_COLORS.get(kind, C_CMP)
                rg = QRadialGradient(xi, stage, 26.0)
                rg.setColorAt(0.0, _qca(col, 150))
                rg.setColorAt(0.45, _qca(col, 60))
                rg.setColorAt(1.0, _qca(col, 0))
                p.setBrush(QBrush(rg))
                p.drawEllipse(QPointF(xi, stage), 26.0, 26.0)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)


class HelixRenderer(VectorRenderer):
    """特殊模式 3：3D 全息透视立体柱阵 / DNA 双螺旋。

    这是全部视图里唯一真正做**三维坐标变换**的一个：

    ``u = i/(N-1) - 0.5``，``α = 4πu + φ + (i 为奇数 ? π : 0)``
    ``X = u·0.86W``，``Z = sin α·R``，``Y = cos α·0.42R``

    ``(X, Y, Z)`` 经透视投影 ``s = fov/(fov + Z + D_cam)`` 压平到屏幕，
    再按 ``Z`` 从远到近排序（画家算法）逐个绘制**三面立体棱柱**：
    顶面提亮到 130%、正面 100%、右侧面压到 65%。

    双螺旋的两股由「下标奇偶各占一股」构成，相位差 π，于是自动缠绕成交叉
    的双链。φ 随时间缓慢自转（导出时按帧号推进，完全确定性），鼠标横向
    拖拽还能手动加一个 Yaw 偏角。
    """

    key = "helix3d"
    _MAXN = 168

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        n = int(values.size)
        idx = self._pick(n, self._MAXN, frame, aux)
        m = int(idx.size)
        if m < 1:
            return
        colors = self._array_colors(values, frame, aux)
        norm = _norm01(values[idx], frame.n_max)
        phi = float(frame.t) * 1.15 + float(frame.yaw)
        u = idx.astype(np.float64) / max(1.0, n - 1.0) - 0.5
        alpha = (4.0 * math.pi * u + phi
                 + np.where(idx % 2 == 1, math.pi, 0.0))
        r3 = 0.23 * min(self.w, bh)
        cx = self.w * 0.5
        base_y = bh * 0.66
        # 透视**只修正纵深方向**：Z 引起的缩放系数被夹在 0.75~1.4 之间，
        # 所以画面横向仍然铺满 0.72W。早期版本把 s 也乘到 X 上且落在
        # 0.33~0.68 区间，结果整座双螺旋缩成画面正中一小团 —— 这才是
        # 「3D 立体→看不清」的真正原因。
        X = u * self.w * 0.72
        Z = np.sin(alpha) * r3 * 1.40
        # Y 振幅取 0.58R（规范书写的是 0.25R）：0.25 时整条链的上下起伏只有
        # ±17 px，在一屏几百像素高的柱阵里根本读不出「螺旋」，看起来就是
        # 一排高度不等的普通柱子。抬到 0.58 才让两股交替的缠绕关系显形，
        # 同时仍小于 Z 振幅，保持「沿 X 轴穿行的椭圆螺旋」这个整体形态。
        Y = np.cos(alpha) * r3 * 0.58
        dcam = r3 * 6.0
        s = dcam / (dcam + Z)
        px = cx + X * s
        py = base_y + Y * s
        hgt = np.maximum(2.0, norm * bh * 0.40 * s)
        bw = np.clip(0.010 * self.w * s, 2.0, 15.0)
        dep = bw * 0.52

        hot = frame.hot or {}
        # ---- 1. 两条螺旋骨链（先画，作为背景）----
        for strand in (0, 1):
            sel = np.flatnonzero(idx % 2 == strand)
            if sel.size < 2:
                continue
            pts = [QPointF(float(px[k]), float(py[k])) for k in sel]
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_qca((0x5A, 0x7C, 0xA8), 110), 1))
            p.drawPolyline(pts)

        # ---- 2. 画家算法：远（Z 大）先画 ----
        order = np.argsort(-Z)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for k in order:
            k = int(k)
            i = int(idx[k])
            c = colors[i]
            x = float(px[k])
            y = float(py[k])
            h = float(hgt[k])
            w = float(bw[k])
            d = float(dep[k])
            front = _qc(c)
            side = _qc(_mix(c, 0.62))
            top = _qc(_mix(c, 1.30))
            p.setPen(Qt.NoPen)
            # 正面
            p.setBrush(front)
            p.drawPolygon(QPolygonF([
                QPointF(x - w / 2, y), QPointF(x + w / 2, y),
                QPointF(x + w / 2, y - h), QPointF(x - w / 2, y - h)]))
            # 右侧面（受光少，压暗）
            p.setBrush(side)
            p.drawPolygon(QPolygonF([
                QPointF(x + w / 2, y), QPointF(x + w / 2 + d, y - d),
                QPointF(x + w / 2 + d, y - h - d), QPointF(x + w / 2, y - h)]))
            # 顶面（朝上受光最多，提亮）
            p.setBrush(top)
            p.drawPolygon(QPolygonF([
                QPointF(x - w / 2, y - h), QPointF(x + w / 2, y - h),
                QPointF(x + w / 2 + d, y - h - d),
                QPointF(x - w / 2 + d, y - h - d)]))
            # 正在比较 / 交换的棱柱：加色体积光
            if i in hot:
                col = HOT_COLORS.get(hot[i], C_CMP)
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                # 光晕半径必须封顶：柱子高的时候 ``h`` 能到 300 px，照它取
                # 半径会在画面上糊出一整块直径 600 px 的黄斑，把周围十几根
                # 柱子全吃掉。60 px 是「看得出在发光」与「不遮数据」的折中。
                gr = min(58.0, max(16.0, h * 0.45))
                rg = QRadialGradient(x, y - h, gr)
                rg.setColorAt(0.0, _qca(col, 130))
                rg.setColorAt(0.5, _qca(col, 42))
                rg.setColorAt(1.0, _qca(col, 0))
                p.setBrush(QBrush(rg))
                p.drawEllipse(QPointF(x, y - h), gr, gr)
                p.setBrush(_qc(col))
                p.drawPolygon(QPolygonF([
                    QPointF(x - w / 2, y), QPointF(x + w / 2, y),
                    QPointF(x + w / 2, y - h), QPointF(x - w / 2, y - h)]))
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)


class AuroraRenderer(VectorRenderer):
    """特殊模式 4：流体极光丝带图（Aurora Smooth Spline Ribbons）。

    彻底抛弃「一根一根柱子」，改用**三段相位错开的连续样条曲面**。曲线用
    Catmull-Rom 转三次贝塞尔（切线 = 前后点差 /6），因此整条边界是 C¹ 连续的
    —— 没有任何折角，也就没有任何颗粒感。

    每条丝带用纵向 ``QLinearGradient`` 填充（顶部 alpha 180 的高饱和霓虹，
    底部 alpha 10 融进背景），顶部再用 1 px 亮线勾边，看起来就是一匹悬在
    空中的丝绸。发生 CMP/SWAP 的位置在波峰上绽开一颗径向发光球。
    """

    key = "aurora"
    _M = 72
    _FLOOR = 0.0
    _LAYERS = ((0x00, 0xF5, 0xD4), (0xB5, 0x37, 0xF2), (0xFF, 0xC8, 0x5A))

    def _anchors(self, values: np.ndarray, frame: VizFrame) -> np.ndarray:
        """把 N 个元素按滑动窗口压成 ``_M`` 个平滑锚点。"""
        n = int(values.size)
        m = self._M
        vals = np.asarray(values, dtype=np.float64)
        if n <= m:
            return _norm01(vals, frame.n_max)
        cells = (np.arange(m + 1) * n) // m
        sums = np.add.reduceat(vals, cells[:-1])
        cnt = np.maximum(1, np.diff(cells))
        return _norm01(sums / cnt, frame.n_max)

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        norm = self._anchors(values, frame)
        m = int(norm.size)
        if m < 3:
            return
        xs = np.linspace(0.0, float(self.w), m)
        base = bh * 0.88
        span = bh * 0.60
        t = float(frame.t)

        for li, col in enumerate(self._LAYERS):
            # 三层不能共用一个形状：形状完全相同而只是略微上下错开的三条带子，
            # 实际上就是一条「厚带子」，加色混合后中段直接过曝成白。给后两层
            # 分别做相位平移 + 幅度衰减，三条带子才会像真正的极光那样相互穿插。
            shift = int(round(m * 0.17 * li)) % m
            shape = np.roll(norm, shift)
            amp = 1.0 - li * 0.28
            drift = math.sin(t * 0.62 + li * 1.7) * 0.05
            ys = base - (shape * amp + drift) * span - li * bh * 0.13
            ys = np.clip(ys, bh * 0.05, bh * 0.80)
            # Catmull-Rom 切线（端点用单侧差分，避免甩尾）
            tang = np.empty_like(ys)
            tang[1:-1] = (ys[2:] - ys[:-2]) / 6.0
            tang[0] = (ys[1] - ys[0]) / 3.0
            tang[-1] = (ys[-1] - ys[-2]) / 3.0

            # 丝带是**有厚度的带子**，不是一直垂到底的幕布。
            # 早期版本从波峰直接填到基线，三层叠在一起就把下半屏糊成一片
            # 灰蒙蒙的色块 —— 既不像极光，也彻底盖住了背景。
            thick = bh * (0.115 - li * 0.012)
            yb = np.minimum(ys + thick, bh * 0.96)
            path = QPainterPath(QPointF(xs[0], float(ys[0])))
            for k in range(m - 1):
                c1x = float(xs[k] + (xs[k + 1] - xs[k]) / 3.0)
                c2x = float(xs[k + 1] - (xs[k + 1] - xs[k]) / 3.0)
                path.cubicTo(c1x, float(ys[k] + tang[k]),
                             c2x, float(ys[k + 1] - tang[k + 1]),
                             float(xs[k + 1]), float(ys[k + 1]))
            path.lineTo(float(xs[-1]), float(yb[-1]))
            # 回程沿下边界倒着走一遍，闭合出一条厚度恒定的丝带
            for k in range(m - 2, -1, -1):
                c1x = float(xs[k + 1] - (xs[k + 1] - xs[k]) / 3.0)
                c2x = float(xs[k] + (xs[k + 1] - xs[k]) / 3.0)
                path.cubicTo(c1x, float(yb[k + 1] - tang[k + 1]),
                             c2x, float(yb[k] + tang[k]),
                             float(xs[k]), float(yb[k]))
            path.closeSubpath()

            # 顶部亮边**不描边**，而是让渐变在最顶端就冲到接近不透明。
            # 这是被实测逼出来的决定：QPainter 的 AA 描边器处理「上百段三次
            # 贝塞尔组成的长曲线」极慢（72 锚点、3 层、2 px 笔实测 165 ms），
            # 而同样几何的填充只要十几毫秒。用渐变的 0.0 停靠点做出高亮边缘，
            # 视觉效果几乎等同于描边，代价是 0。
            # 三层丝带互为「加色光源」：叠在一起时变亮、不叠时各自通透。
            # 若用 SourceOver，青/紫/金三种互补色在中段重叠会把画面糊成
            # 一块灰（实测重叠区 (95,87,93)）—— 那是「颜料」的混合方式，
            # 而极光是**发光体**，必须用加色混合。
            g = QLinearGradient(0.0, float(ys.min()), 0.0, float(yb.max()))
            g.setColorAt(0.00, _qca(_mix(col, 1.30), 214))
            g.setColorAt(0.12, _qca(col, 116))
            g.setColorAt(0.46, _qca(col, 40))
            g.setColorAt(1.00, _qca(col, 0))
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawPath(path)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # ---- 波峰光球：正在比较 / 交换的位置绽放径向光 ----
        hot = frame.hot or {}
        n = int(values.size)
        if hot and n > 1:
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            for i, kind in hot.items():
                if not (0 <= i < n):
                    continue
                k = int(round(i / max(1.0, n - 1.0) * (m - 1)))
                col = HOT_COLORS.get(kind, C_CMP)
                vx = float(xs[k])
                vy = float(base - norm[k] * span)
                r = 24.0
                rg = QRadialGradient(vx, vy, r)
                rg.setColorAt(0.0, _qca(col, 190))
                rg.setColorAt(0.35, _qca(col, 80))
                rg.setColorAt(1.0, _qca(col, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(rg))
                p.drawEllipse(QPointF(vx, vy), r, r)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)


class OrbRenderer(VectorRenderer):
    """特殊模式 5：3D 高光玻璃球与抛物线飞跃（Glossy Spheres & Parabolic Flight）。

    每颗球用四段停靠的 ``QRadialGradient`` 伪造玻璃材质：左上角一点纯白高光
    → 球体主色 → 边缘暗部 → 透明收边。这套 stop 表是标准的「塑料球」光照
    模型，一眼就能看出是立体的球而不是圆点。

    交换发生时，两颗球之间会画出上下对称的两条抛物线，并沿抛物线各留 5 颗
    半透明残影 —— 于是「A 飞过去、B 飞过来」这件事被画成了两条看得见的轨道。
    """

    key = "orbs"
    _MAXN = 168
    _GHOST = 5

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        n = int(values.size)
        idx = self._pick(n, self._MAXN, frame, aux)
        m = int(idx.size)
        if m < 1:
            return
        colors = self._array_colors(values, frame, aux)
        norm = _norm01(values[idx], frame.n_max)
        pad = 0.035 * self.w
        span = self.w - 2.0 * pad
        base = bh * 0.92
        hmax = bh * 0.74
        # 单排铺 N 颗球时，N=200 在 900 px 画布上球心间距只有 4.4 px，
        # 半径被压到 2 px —— 渐变、高光、暗部全糊成一个点，「玻璃球」这个
        # 概念也就不成立了。改成**奇偶双排交错**：横向间距直接翻倍，半径
        # 才有 5~6 px 可用，球体材质真正看得出来；同时两排错开高度，
        # 读起来是一条起伏的珍珠链而不是两条平行线。
        row = idx % 2
        per = max(1, (m + 1) // 2)
        slot = np.where(row == 0, idx // 2, (idx - 1) // 2)
        xs = pad + slot / float(max(1, per - 1)) * span
        ys = base - norm * hmax - row * bh * 0.055
        # 规范书半径公式 W/(1.8N) 的本意是「按排布间距定尺寸」，这里按
        # **每排球数**计算，并夹在 4~18 px
        rad = float(min(18.0, max(4.0, 0.62 * span / max(1.0, per - 1))))
        # 球太密时退化成实心点（径向渐变每颗约 19 µs）
        graded = rad >= 4.5

        # ---- 1. 飞跃抛物线（先画在球底下，避免压住球体）----
        hot = frame.hot or {}
        pair = [i for i, k in hot.items()
                if k in ("swap", "set", "cmp") and 0 <= i < n]
        if len(pair) >= 2:
            a, b = pair[0], pair[1]
            ia = int(np.argmin(np.abs(idx - a)))
            ib = int(np.argmin(np.abs(idx - b)))
            if ia != ib:
                xa, ya = float(xs[ia]), float(ys[ia])
                xb, yb = float(xs[ib]), float(ys[ib])
                col = HOT_COLORS.get(hot[a], C_SWAP)
                dist = math.hypot(xb - xa, yb - ya)
                lift = max(24.0, min(0.45 * bh, 0.55 * dist))
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                for sign in (-1.0, 1.0):
                    ctl = QPointF((xa + xb) * 0.5, (ya + yb) * 0.5 + sign * lift)
                    path = QPainterPath(QPointF(xa, ya))
                    path.quadTo(ctl, QPointF(xb, yb))
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(_qca(col, 50), 5))
                    p.drawPath(path)
                    p.setPen(QPen(_qca((255, 255, 255), 210), 1))
                    p.drawPath(path)
                    for g in range(1, self._GHOST + 1):
                        u = g / float(self._GHOST + 1)
                        gx = ((1 - u) ** 2) * xa + 2 * (1 - u) * u * ctl.x() + u * u * xb
                        gy = ((1 - u) ** 2) * ya + 2 * (1 - u) * u * ctl.y() + u * u * yb
                        gr = rad * (0.28 + 0.34 * (1.0 - u))
                        p.setPen(Qt.NoPen)
                        p.setBrush(_qca(col, int(150 * (1.0 - 0.65 * u))))
                        p.drawEllipse(QPointF(gx, gy), gr, gr)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # ---- 2. 球体 ----
        for k in range(m):
            x = float(xs[k])
            y = float(ys[k])
            c = colors[int(idx[k])]
            if graded:
                g = QRadialGradient(x - 0.30 * rad, y - 0.30 * rad, 1.30 * rad)
                g.setColorAt(0.00, QColor(255, 255, 255, 240))
                g.setColorAt(0.35, _qca(c, 236))
                g.setColorAt(0.85, _qca(_mix(c, 0.34), 232))
                g.setColorAt(1.00, _qca(_mix(c, 0.18), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(x, y), rad, rad)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(_qc(c))
                p.drawEllipse(QPointF(x, y), max(1.4, rad * 0.55),
                              max(1.4, rad * 0.55))
            if int(idx[k]) in hot:
                col = HOT_COLORS.get(hot[int(idx[k])], C_CMP)
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                rg = QRadialGradient(x, y, rad * 3.2)
                rg.setColorAt(0.0, _qca(col, 170))
                rg.setColorAt(0.5, _qca(col, 55))
                rg.setColorAt(1.0, _qca(col, 0))
                p.setBrush(QBrush(rg))
                p.drawEllipse(QPointF(x, y), rad * 3.2, rad * 3.2)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)


class CrystalRenderer(VectorRenderer):
    """特殊模式 6：低多边形宝石晶格网（Low-Poly Crystal Mesh）。

    把数组聚合成 ``R×C`` 个网格顶点，每个顶点按「当前名次 − 有序名次」的
    偏差在屏幕上**发生位移**：乱序时整张网被拧成一团锯齿状的晶体，
    排好序时偏差全部归零，网格回归成一枚工整的宝石切面。

    每个格子拆成两颗三角形切面，颜色取三顶点均值的调色板色，明暗取三角形
    在屏幕上的有向面积（近似法线 Z 分量）。填充关闭抗锯齿 —— 一是因为
    相邻切面共享顶点、本来就没有接缝，二是因为 AA 填充的吞吐只有
    ~90M px/s，整屏铺一遍就是 8 ms，会把帧率直接打穿；真正需要锐利感的
    「明暗断层边」再单独开 AA 描一遍。
    """

    key = "crystal"
    _ROWS = 9
    _COLS = 16
    _EDGE_DELTA = 0.22
    _MAX_EDGES = 110

    def _paint_vector(self, p, bh, values, frame, aux) -> None:
        n = int(values.size)
        R, C = self._ROWS, self._COLS
        if n < 4 or bh < 32 or self.w < 48:
            return
        cell = _pool_grid(values, R, C)
        n_max = max(2, int(frame.n_max))
        denom = float(n_max - 1)
        vnorm = _pool_vertex(cell, denom)

        gx = np.linspace(0.03 * self.w, 0.97 * self.w, C + 1)
        gy = np.linspace(0.08 * bh, 0.92 * bh, R + 1)
        X, Y = np.meshgrid(gx, gy)
        # 有序度参照系：顶点在「排好序的网格」里应处的名次比例
        tgt = np.arange((R + 1) * (C + 1), dtype=np.float64
                        ).reshape(R + 1, C + 1) / float((R + 1) * (C + 1) - 1)
        dev = vnorm - tgt
        ii, jj = np.meshgrid(np.arange(R + 1), np.arange(C + 1), indexing="ij")
        sg = np.where((ii + jj) % 2 == 0, 1.0, -1.0)
        cw = self.w / float(C + 1)
        ch = bh / float(R + 1)
        Xd = X + dev * sg * cw * 0.78
        Yd = Y - dev * (1.5 - 0.55 * sg) * ch * 0.60

        tab = palette_for(n_max, frame.palette)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(Qt.NoPen)
        light = np.zeros((R, C), dtype=np.float64)
        area_ref = max(1e-6, cw * ch)
        for r in range(R):
            for c in range(C):
                x0, y0 = float(Xd[r, c]), float(Yd[r, c])
                x1, y1 = float(Xd[r, c + 1]), float(Yd[r, c + 1])
                x2, y2 = float(Xd[r + 1, c]), float(Yd[r + 1, c])
                x3, y3 = float(Xd[r + 1, c + 1]), float(Yd[r + 1, c + 1])
                m01 = 0.5 * (vnorm[r, c] + vnorm[r, c + 1])
                m12 = 0.5 * (vnorm[r + 1, c] + vnorm[r + 1, c + 1])
                light[r, c] = 0.5 * (m01 + m12)
                for tri, vm in ((((x0, y0), (x1, y1), (x3, y3)),
                                 (vnorm[r, c] + vnorm[r, c + 1]
                                  + vnorm[r + 1, c + 1]) / 3.0),
                                (((x0, y0), (x3, y3), (x2, y2)),
                                 (vnorm[r, c] + vnorm[r + 1, c + 1]
                                  + vnorm[r + 1, c]) / 3.0)):
                    ax, ay = tri[0]
                    bx, by = tri[1]
                    cx2, cy2 = tri[2]
                    cross = (bx - ax) * (cy2 - ay) - (cx2 - ax) * (by - ay)
                    shade = 0.60 + 0.55 * min(1.6, abs(cross) / area_ref)
                    k = int(min(n_max - 1, max(0, round(vm * denom))))
                    cr, cg, cb = int(tab[k][0]), int(tab[k][1]), int(tab[k][2])
                    p.setBrush(QColor(min(255, int(cr * shade)),
                                      min(255, int(cg * shade)),
                                      min(255, int(cb * shade)),
                                      214))
                    p.drawPolygon(QPolygonF([QPointF(*tri[0]), QPointF(*tri[1]),
                                             QPointF(*tri[2])]))
        # ---- 明暗断层边：只给对比强的地方描 AA 亮线，避免锯齿又不过烧 ----
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        lw = max(1, int(round(min(self.w, bh) / 620.0)))
        edges = 0
        for r in range(R):
            for c in range(C):
                if edges >= self._MAX_EDGES:
                    break
                l0 = light[r, c]
                for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if not (0 <= rr < R and 0 <= cc < C):
                        continue
                    if abs(l0 - light[rr, cc]) < self._EDGE_DELTA:
                        continue
                    ax, ay = float(Xd[r + 1, c + 1]), float(Yd[r + 1, c + 1])
                    bx, by = (float(Xd[r + 1, c]), float(Yd[r + 1, c])) if cc == c \
                        else (float(Xd[r, c + 1]), float(Yd[r, c + 1]))
                    p.setPen(QPen(_qca((0xD8, 0xF4, 0xFF), 130), lw))
                    p.drawLine(QPointF(ax, ay), QPointF(bx, by))
                    edges += 1
        p.setRenderHint(QPainter.Antialiasing, True)
        # ---- 高亮切面：正在比较 / 交换的格子整片点亮 ----
        hot = frame.hot or {}
        if hot and n > 1:
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            for i, kind in hot.items():
                if not (0 <= i < n):
                    continue
                k = int(min(R * C - 1, i * R * C // n))
                r, c = divmod(k, C)
                col = HOT_COLORS.get(kind, C_CMP)
                poly = QPolygonF([
                    QPointF(float(Xd[r, c]), float(Yd[r, c])),
                    QPointF(float(Xd[r, c + 1]), float(Yd[r, c + 1])),
                    QPointF(float(Xd[r + 1, c + 1]), float(Yd[r + 1, c + 1])),
                    QPointF(float(Xd[r + 1, c]), float(Yd[r + 1, c]))])
                p.setPen(Qt.NoPen)
                p.setBrush(_qca(col, 78))
                p.drawPolygon(poly)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _pool_grid(values: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """把 N 个元素聚合成 ``(rows, cols)`` 的均值网格（N 再大也只有这么多个格）。"""
    n = int(values.size)
    cells = rows * cols
    vals = np.asarray(values, dtype=np.float64)
    if n >= cells:
        edges = (np.arange(cells + 1) * n) // cells
        sums = np.add.reduceat(vals, edges[:-1])
        cnt = np.maximum(1, np.diff(edges))
        out = sums / cnt
    else:
        pick = np.clip((np.arange(cells) * n) // cells, 0, n - 1)
        out = vals[pick]
    return out.reshape(rows, cols)


def _pool_vertex(cell: np.ndarray, denom: float) -> np.ndarray:
    """格点值 → 顶点值（相邻四格均值），保证网格连续、不撕裂。"""
    rows, cols = cell.shape
    big = np.pad(cell, 1, mode="edge")
    # big[i][j] 对应 cell[i-1][j-1]，于是顶点 (i, j) 的四邻格正好是
    # big[i..i+1][j..j+1]，切片形状一律 (rows+1, cols+1)。
    v = (big[0:rows + 1, 0:cols + 1] + big[1:rows + 2, 0:cols + 1]
         + big[0:rows + 1, 1:cols + 2] + big[1:rows + 2, 1:cols + 2]) * 0.25
    return np.clip((v - 1.0) / max(1.0, denom), 0.0, 1.0)


# --------------------------------------------------------------------------
# 6.1 切片还原模式的图源（内置高清合成画 + 外部图片导入）
# --------------------------------------------------------------------------
_SLICE_SRC: Dict[str, object] = {"arr": None, "path": None, "name": None}


def reset_slice_source() -> None:
    """丢弃当前图源，下次渲染时重新生成内置画面。"""
    _SLICE_SRC["arr"] = None
    _SLICE_SRC["path"] = None
    _SLICE_SRC["name"] = None


def slice_source_name() -> str:
    """当前图源的显示名（界面状态栏 / 提示用）。"""
    return str(_SLICE_SRC.get("name") or "内置 · 赛博朋克落日星云")


def slice_source_array() -> Optional[np.ndarray]:
    """返回 ``(h, w, 3) uint8`` 的图源；首次调用时生成内置画。"""
    arr = _SLICE_SRC.get("arr")
    if isinstance(arr, np.ndarray) and arr.ndim == 3:
        return arr
    try:
        arr = _build_default_slice_image()
    except Exception:                                   # pragma: no cover
        return None
    _SLICE_SRC["arr"] = arr
    _SLICE_SRC["name"] = _SLICE_SRC.get("name") or "内置 · 赛博朋克落日星云"
    return arr


def set_slice_source(path: str) -> Optional[str]:
    """导入本地图片作为切片还原模式图源。成功返回 ``None``，失败返回原因。"""
    try:
        img = QImage(str(path))
        if img.isNull():
            return "无法读取该图片（格式不支持或文件损坏）"
        if img.width() > 2400:
            img = img.scaledToWidth(2400, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_RGB888)
        w, h = int(img.width()), int(img.height())
        bpl = int(img.bytesPerLine())
        raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h)
        arr = raw.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3).copy()
        _SLICE_SRC["arr"] = arr
        _SLICE_SRC["path"] = str(path)
        _SLICE_SRC["name"] = str(path).replace("\\", "/").rsplit("/", 1)[-1]
        return None
    except Exception as exc:                            # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def _qimage_to_rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = int(img.width()), int(img.height())
    bpl = int(img.bytesPerLine())
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h)
    return raw.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3).copy()


def _build_default_slice_image(w: int = 1600, h: int = 900) -> np.ndarray:
    """用 QPainter + 多重渐变现场合成一张「赛博朋克落日星云与几何山脉」。"""
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0x08, 0x06, 0x16))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    try:
        _paint_default_slice(p, w, h)
    finally:
        p.end()
    return _qimage_to_rgb(img)


def _paint_default_slice(p: QPainter, w: int, h: int) -> None:
    """内置画卷的绘制过程：天空 → 星云 → 星点 → 落日 → 山脉 → 地平线。"""
    rng = np.random.default_rng(20261017)
    p.setPen(Qt.NoPen)

    # ---- 1. 天空：从深空紫到洋红再到熔金，最后坠入黑色前景 ----
    g = QLinearGradient(0.0, 0.0, 0.0, float(h))
    g.setColorAt(0.00, QColor(0x05, 0x04, 0x10))
    g.setColorAt(0.28, QColor(0x1B, 0x0A, 0x33))
    g.setColorAt(0.50, QColor(0x4A, 0x12, 0x59))
    g.setColorAt(0.63, QColor(0xA0, 0x25, 0x58))
    g.setColorAt(0.70, QColor(0xE8, 0x5A, 0x3A))
    g.setColorAt(0.75, QColor(0xFF, 0xB4, 0x58))
    g.setColorAt(0.80, QColor(0x6B, 0x1E, 0x4A))
    g.setColorAt(0.88, QColor(0x18, 0x09, 0x20))
    g.setColorAt(1.00, QColor(0x05, 0x03, 0x0C))
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))

    # ---- 2. 星云团：四个大半径径向渐变 ----
    for cx, cy, r, col in ((0.17, 0.22, 0.32, (0x4E, 0x2C, 0xC8)),
                           (0.74, 0.15, 0.27, (0xC8, 0x2C, 0x8A)),
                           (0.46, 0.36, 0.23, (0x2C, 0xC8, 0xB4)),
                           (0.90, 0.46, 0.21, (0xE0, 0x8A, 0x2C))):
        rg = QRadialGradient(cx * w, cy * h, r * w)
        rg.setColorAt(0.0, QColor(col[0], col[1], col[2], 88))
        rg.setColorAt(0.55, QColor(col[0], col[1], col[2], 26))
        rg.setColorAt(1.0, QColor(col[0], col[1], col[2], 0))
        p.setBrush(QBrush(rg))
        p.drawEllipse(QPointF(cx * w, cy * h), r * w, r * w)

    # ---- 3. 星点 ----
    for _ in range(380):
        x = float(rng.uniform(0.0, 1.0)) * w
        y = float(rng.uniform(0.0, 0.58)) * h
        s = float(rng.uniform(0.6, 1.9))
        p.setBrush(QColor(255, 255, 255, int(rng.uniform(60, 235))))
        p.drawEllipse(QPointF(x, y), s, s)

    # ---- 4. 落日：外光晕 + 本体 + 赛博切分条 ----
    sx, sy, sr = 0.665 * w, 0.735 * h, 0.125 * w
    halo = QRadialGradient(sx, sy, sr * 2.7)
    halo.setColorAt(0.00, QColor(0xFF, 0xD9, 0x8A, 190))
    halo.setColorAt(0.26, QColor(0xFF, 0x8A, 0x3C, 108))
    halo.setColorAt(0.62, QColor(0xE0, 0x2A, 0x66, 58))
    halo.setColorAt(1.00, QColor(0xE0, 0x2A, 0x66, 0))
    p.setBrush(QBrush(halo))
    p.drawEllipse(QPointF(sx, sy), sr * 2.7, sr * 2.7)
    disc = QRadialGradient(sx, sy - sr * 0.26, sr * 1.16)
    disc.setColorAt(0.00, QColor(0xFF, 0xF5, 0xD0))
    disc.setColorAt(0.52, QColor(0xFF, 0xC2, 0x5E))
    disc.setColorAt(1.00, QColor(0xFF, 0x68, 0x3A))
    p.setBrush(QBrush(disc))
    p.drawEllipse(QPointF(sx, sy), sr, sr)
    p.setBrush(QColor(0x1A, 0x06, 0x1E, 232))
    band_y, thick, k = sy + sr * 0.04, sr * 0.040, 0
    while band_y < sy + sr and k < 24:
        p.drawRect(QRectF(sx - sr * 1.02, band_y, sr * 2.04, thick))
        band_y += thick + sr * 0.088 - k * sr * 0.0038
        thick *= 1.17
        k += 1

    # ---- 5. 三层几何山脉 ----
    for base, amp, c0, c1 in ((0.735, 0.150, QColor(0x5E, 0x1C, 0x46),
                               QColor(0x2A, 0x08, 0x22)),
                              (0.815, 0.125, QColor(0x2A, 0x10, 0x33),
                               QColor(0x12, 0x05, 0x18)),
                              (0.905, 0.095, QColor(0x13, 0x07, 0x1A),
                               QColor(0x05, 0x02, 0x0A))):
        path = QPainterPath(QPointF(0.0, float(h)))
        path.lineTo(0.0, base * h)
        xs = np.linspace(0.0, 1.0, 27)
        ys = base * h - (amp * h) * (rng.random(27) ** 1.7)
        for t in range(27):
            path.lineTo(float(xs[t]) * w, float(ys[t]))
        path.lineTo(float(w), base * h)
        path.lineTo(float(w), float(h))
        path.closeSubpath()
        gg = QLinearGradient(0.0, (base - amp) * h, 0.0, float(h))
        gg.setColorAt(0.0, c0)
        gg.setColorAt(0.52, c1)
        gg.setColorAt(1.0, QColor(0x02, 0x01, 0x06))
        p.setBrush(QBrush(gg))
        p.drawPath(path)

    # ---- 6. 地平线辉光 ----
    hg = QLinearGradient(0.0, 0.835 * h, 0.0, 0.885 * h)
    hg.setColorAt(0.0, QColor(0xFF, 0x8A, 0x50, 0))
    hg.setColorAt(0.5, QColor(0xFF, 0xC8, 0x8A, 120))
    hg.setColorAt(1.0, QColor(0xFF, 0x8A, 0x50, 0))
    p.setBrush(QBrush(hg))
    p.drawRect(QRectF(0, 0.835 * h, w, 0.05 * h))


_RENDERERS = {
    # ---- 基础三式 ----
    "bars": BarsRenderer,
    "wheel": WheelRenderer,
    "scatter": ScatterRenderer,
    # ---- 核心特色四式 ----
    "mirror": MirrorRenderer,
    "disparity": DisparityRenderer,
    "pyramid": PyramidRenderer,
    "residual": ResidualRenderer,
    # ---- 高概念创意五式 ----
    "waterfall": WaterfallRenderer,
    "loom": LoomRenderer,
    "nautilus": NautilusRenderer,
    "dreamcatcher": DreamcatcherRenderer,
    "tree": TreeRenderer,
    # ---- 次世代高画质六式（Instruction3）----
    "slice": SliceRenderer,
    "arcs": ArcRenderer,
    "helix3d": HelixRenderer,
    "aurora": AuroraRenderer,
    "orbs": OrbRenderer,
    "crystal": CrystalRenderer,
}


def make_renderer(style: str, width: int = 640, height: int = 360
                  ) -> StyleRenderer:
    return _RENDERERS.get(style, BarsRenderer)(width, height)


def render_frame_to_array(frame: VizFrame, width: int, height: int,
                          style: str = "bars",
                          renderer: Optional[StyleRenderer] = None
                          ) -> np.ndarray:
    """离屏渲染一帧，返回 ``(height, width, 3) uint8``。

    Batch 6 的视频导出器直接调用本函数即可，无需创建任何 Qt 控件。
    """
    r = renderer if renderer is not None else make_renderer(style, width, height)
    r.resize(width, height)
    return r.render(frame)


# --------------------------------------------------------------------------
# 7. Qt 画布控件
# --------------------------------------------------------------------------
class CanvasWidget(QWidget):
    """把 :class:`StyleRenderer` 的位图**一次性 BitBlt** 到屏幕的 Qt 控件。

    重绘路径上只有三步：一次 NumPy 渲染、一次 ``QImage`` 包装、一次
    ``drawImage``。只有 CMP 指示三角标这类**数量极少**的装饰才走 ``QPainter``，
    因此 N=10,000 时也不会退化。
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 style: str = "bars") -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._frame = VizFrame(values=(2, 5, 3, 8, 1, 6), n_max=8)
        self._style = style
        self._renderer: Optional[StyleRenderer] = None
        self._qimage: Optional[QImage] = None
        self._img_src: Optional[np.ndarray] = None
        self._placeholder = "选择左侧算法后点击 ▶ 播放"
        self._show_labels = True
        self._last_ms = 0.0
        #: 动画时钟原点。规范书要求的「余晖残影 / 全息自转」都要一个时间基准。
        self._t0 = time.perf_counter()
        #: 鼠标横向拖拽累计的视角偏航角（全息双螺旋专用）
        self._yaw = 0.0
        self._drag_x: Optional[float] = None
        self._drag_yaw = 0.0

    # ---- 属性 ------------------------------------------------------------
    @property
    def style(self) -> str:
        return self._style

    def set_style(self, style: str) -> None:
        if style == self._style:
            return
        self._style = style
        self._renderer = None
        self._qimage = None
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def set_show_labels(self, on: bool) -> None:
        self._show_labels = bool(on)
        self.update()

    @property
    def last_render_ms(self) -> float:
        return self._last_ms

    def set_frame(self, frame: VizFrame) -> None:
        # 时间与视角由画布统一注入：调用方（主窗口 / 赛马窗格）只管数据，
        # 不必关心「这一帧该用第几秒」。
        if frame.t <= 0.0:
            frame.t = time.perf_counter() - self._t0
        frame.yaw = self._yaw
        self._frame = frame
        self.update()

    def frame(self) -> VizFrame:
        return self._frame

    # ---- 交互：横向拖拽改变视角 ------------------------------------------
    def mousePressEvent(self, event) -> None:       # noqa: N802 (Qt 命名)
        if event.button() == Qt.LeftButton:
            self._drag_x = float(event.position().x())
            self._drag_yaw = self._yaw
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:        # noqa: N802 (Qt 命名)
        if self._drag_x is not None:
            dx = float(event.position().x()) - self._drag_x
            self._yaw = self._drag_yaw + dx * 0.012
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:     # noqa: N802 (Qt 命名)
        if self._drag_x is not None and event.button() == Qt.LeftButton:
            self._drag_x = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def reset_view(self) -> None:
        """把视角偏航角归零（切换视图 / 双击画布时调用）。"""
        self._yaw = 0.0
        self._t0 = time.perf_counter()
        self.update()

    # ---- 尺寸变化 --------------------------------------------------------
    def _ensure(self) -> Optional[np.ndarray]:
        w = max(32, self.width())
        h = max(32, self.height())
        if (self._renderer is None or self._renderer.w != w
                or self._renderer.h != h):
            self._renderer = make_renderer(self._style, w, h)
            self._qimage = None
        arr = self._renderer.render(self._frame)
        # QImage 不持有内存所有权，因此必须让它始终指向同一块 NumPy 缓冲；
        # 缓冲只在 resize 时重新分配，此时 _qimage 也会被同步重建。
        # self._img_src 持有该缓冲的强引用，防止被 GC 回收后 QImage 悬空。
        if self._qimage is None or self._qimage.width() != w:
            self._img_src = arr
            self._qimage = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
        return arr

    # ---- 绘制 ------------------------------------------------------------
    def paintEvent(self, event) -> None:            # noqa: N802 (Qt 命名)
        t0 = time.perf_counter()
        painter = QPainter(self)
        # 规范书第一节第 1 条：全抗锯齿 + 平滑位图变换一律打开。
        # 位图主体是按像素精确光栅化的 NumPy 缓冲，抗锯齿对它没有副作用；
        # 真正的受益者是底部的三角指示标、MAIN/AUX 标签以及霓虹光晕。
        painter.setRenderHints(QPainter.Antialiasing
                               | QPainter.TextAntialiasing
                               | QPainter.SmoothPixmapTransform)
        arr = self._ensure()
        if arr is None or self._qimage is None:
            painter.fillRect(self.rect(), QColor(*C_BG))
            painter.end()
            return
        painter.drawImage(0, 0, self._qimage)
        self._paint_hot_markers(painter)
        if self._show_labels:
            self._paint_labels(painter)
        self._last_ms = (time.perf_counter() - t0) * 1000.0
        painter.end()

    def _split_geometry(self) -> Tuple[bool, int]:
        frame = self._frame
        split = bool(frame.aux_active) and len(frame.aux) > 0
        if not split:
            return False, self.height()
        main_h = max(24, int((self.height() - 6) * 0.65))
        aux_h = self.height() - main_h - 6
        if aux_h < 16:
            return False, self.height()
        return True, main_h

    def _paint_hot_markers(self, painter: QPainter) -> None:
        """在正在比较 / 交换的柱子**底部**绘制向上指示三角标（规范书 5.1）。

        只在「横轴 = 数组下标」的样式里画（见 :data:`HOT_MARKER_STYLES`）。
        花瓣环 / 鹦鹉螺 / 金字塔 / 二叉树里元素按角度、行或层级分布，底部
        三角标会指向完全无关的位置，纯粹是噪声 —— 那些样式里「元素本身
        被染色」已经足够表达高亮；织布机与捕梦网则用「连线加粗 + 不透明」
        表达，也不需要三角标。
        """
        frame = self._frame
        if not frame.hot and not frame.hot_aux:
            return
        if self._style not in HOT_MARKER_STYLES:
            return
        split, main_h = self._split_geometry()
        painter.setPen(Qt.NoPen)

        n = len(frame.values)
        if frame.hot and n > 0:
            base_y = main_h - 2
            half = max(2.0, min(7.0, self.width() / max(1.0, n * 2.4)))
            # 霓虹灯管质感：先用 6 px / alpha 45 的宽画笔叠一层外发光
            # （加色混合），再用 1 px / alpha 240 画白芯。三角标本来就只有
            # 几像素，这么一叠立刻从「一个色块」变成「一盏亮着的灯」。
            for kind in sorted({k for k in frame.hot.values() if k != "flip"}):
                col = HOT_COLORS.get(kind, C_CMP)
                ids = [i for i, k in frame.hot.items()
                       if k == kind and 0 <= i < n]
                if not ids:
                    continue
                painter.setBrush(Qt.NoBrush)
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
                painter.setPen(QPen(_qca(col, 45), 6))
                for i in ids:
                    cx = (i + 0.5) * self.width() / n
                    painter.drawPolygon(QPolygonF([
                        QPointF(cx - half, base_y),
                        QPointF(cx + half, base_y),
                        QPointF(cx, base_y - half * 1.8)]))
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                painter.setPen(Qt.NoPen)
                painter.setBrush(_qca(col, 240))
                for i in ids:
                    cx = (i + 0.5) * self.width() / n
                    painter.drawPolygon(QPolygonF([
                        QPointF(cx - half * 0.86, base_y),
                        QPointF(cx + half * 0.86, base_y),
                        QPointF(cx, base_y - half * 1.6)]))
            painter.setBrush(Qt.NoBrush)

        na = len(frame.aux)
        if split and frame.hot_aux and na > 0:
            half = max(2.0, min(7.0, self.width() / max(1.0, na * 2.4)))
            base_y = self.height() - 2
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*C_AUX_HOT))
            for i in frame.hot_aux:
                if not (0 <= i < na):
                    continue
                cx = (i + 0.5) * self.width() / na
                painter.drawPolygon(QPolygonF([
                    QPointF(cx - half, base_y),
                    QPointF(cx + half, base_y),
                    QPointF(cx, base_y - half * 1.8)]))

    def _paint_labels(self, painter: QPainter) -> None:
        split, main_h = self._split_geometry()
        if not split:
            return
        painter.setPen(QColor(0x6E, 0x7A, 0x8C))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(8, 15, "MAIN")
        painter.drawText(8, main_h + 20, "AUX")

    # ---- 离屏导出 --------------------------------------------------------
    @staticmethod
    def render_to_array(frame: VizFrame, width: int, height: int,
                        style: str = "bars") -> np.ndarray:
        return render_frame_to_array(frame, width, height, style)
