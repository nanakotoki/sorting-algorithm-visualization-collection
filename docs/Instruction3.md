# 视觉引擎次世代升级指令：告别低画质像素感，实现高清矢量光影与 6 种特殊可视化形态

当前的可视化画面存在明显的“低画质像素/简陋几何感”（线条生硬、缺乏抗锯齿与光影过渡、像素缓冲区放大模糊、表现形式局限于传统 2D 图表）。
请对 `ui/canvas_widget.py` 与 `ui/main_window.py` 进行全面视觉升级：首先实装**“四大高清矢量画质管线”**，随后新增 **6 种彻底跳出传统图表的特殊可视化模式**。

---

## 一、 底层画质管线强制升级 (HD Vector Rendering Pipeline)

在所有视图的绘制过程中，必须全局启用以下 4 项高质量渲染技术，严禁使用低分辨率 `uint8` 像素图直接暴力拉伸：

1. **全抗锯齿与平滑矢量变换**：
   ```python
   painter.setRenderHints(
       QPainter.RenderHint.Antialiasing |
       QPainter.RenderHint.TextAntialiasing |
       QPainter.RenderHint.SmoothPixmapTransform
   )
   ```
2. **动态余晖残影缓冲层 (Motion Trail / Afterimage Buffer)**：
   - 在 `CanvasWidget` 中维护一个与窗口同尺寸的透明离屏图层 `self.trail_pixmap = QPixmap(width, height)`。
   - 每一帧渲染时，不要对 `trail_pixmap` 直接 `fill(Qt.black)`，而是使用 `CompositionMode_DestinationIn` 叠加一层透明度为 `215/255` 的衰减遮罩（或半透明深色覆盖），让上一帧的 `CMP`（亮黄）与 `SWAP`（珊瑚红）高光自然留下持续 8~12 帧的**丝滑动态残影光轨**，彻底消除刺眼的单帧闪烁。
3. **霓虹辉光叠加模式 (Additive Neon Glow)**：
   - 在绘制高亮连线、贝塞尔光弧、粒子光晕时，切换混合模式为 `painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)`。
   - 先使用宽画笔（`width=6, alpha=45`）绘制底层外发光晕（Bloom），再用细画笔（`width=1.8, alpha=240`）绘制高亮白芯，形成真实的霓虹灯管质感。
4. **黑曜石舞台镜面倒影 (Obsidian Floor Reflection)**：
   - 在非全屏圆形视图中，将主绘图区置于画布上方 `78%` 区域，底部 `22%` 作为黑曜石反射地面：绘制一条发光地平线，并将上方主视图底部元素以 `alpha=60` 结合纵向线性渐变遮罩（`QLinearGradient` 从半透明迅速衰减至纯黑 `#0B0C10`）向下绘制倒影。

---

## 二、 新增 6 种特殊表现方式 (6 Next-Gen Special Modes)

请在视图选择菜单中新增以下 **6 种高画质特殊模式**（并支持在界面上点击按钮“导入自定义图片”用于模式 1）：

### 特殊模式 1：高清图像切片还原 (HD Image Slice / Glitch Restoration)
- **核心概念**：将一张高清图片切分为 $N$ 个纵向切片（Vertical Strips），用图像的拼合还原代替枯燥的数字排序。
- **实现细节**：
  - **内置高清画作生成 + 外部图片导入**：支持用户通过 `QFileDialog` 导入任意本地图片（JPG/PNG）；若未导入，则在初始化时使用 `QPainter` + 多重 `QLinearGradient` / `QRadialGradient` 动态生成一张 1920x1080 的高清【赛博朋克落日星云与几何山脉】合成画卷缓存为 `self.source_hd_pixmap`。
  - **切片映射**：设数组元素值归一化排名为 `rank_i in [0, N-1]`。当前索引 `i` 处应绘制原图中第 `rank_i` 号纵向切片：
    - 源矩形 `src_rect = QRectF(rank_i * (img_w / N), 0, img_w / N, img_h)`
    - 目标矩形 `dst_rect = QRectF(x0 + i * (W / N), y0, W / N + 0.5, H)`
    - 调用 `painter.drawPixmap(dst_rect, self.source_hd_pixmap, src_rect)`。
  - **故障艺术与激光扫描特效**：
    - 正在发生 `CMP` 或 `SWAP` 的切片上方，绘制一道半透明霓虹激光扫描罩，并将被交换的切片做轻微纵向错位偏移（Glitch Offset $\pm 8\text{px}$），排序完成后整张高清大图完美复原！

### 特殊模式 2：霓虹拱桥光弧与镜面交响 (Neon Bezier Arcs & Mirror Floor)
- **核心概念**：用跨越空间的平滑贝塞尔半圆霓虹拱桥表现元素之间的交互与距离，打造类似《The Shape of Song》的数据艺术效果。
- **实现细节**：
  - 在画布垂直位置 $y_{\text{stage}} = y_0 + 0.68 H$ 处绘制一条水平发光基准弦，所有数组元素在基准弦上表现为发光晶体节点（颜色映射数值色相，大小映射数值）。
  - **实时拱桥与余晖光弧**：
    - 维护一个最近 $K = 45$ 次操作的队列 `recent_arcs`（记录 `(idx_a, idx_b, op_type, age)`）。
    - 对队列中的每次操作及当前每个元素偏离目标位置的跨度 $(i \to t_i)$，使用 `QPainterPath` 绘制连接 $x_a$ 与 $x_b$ 的平滑半椭圆/三次贝塞尔拱桥：
      - 跨度 $d = \vert{}x_b - x_a\vert{}$，拱高 $h_{\text{arc}} = \min(0.62 H, \ 0.48 \times d)$。
      - 上方主光拱控制点位于 $y_{\text{stage}} - h_{\text{arc}}$（使用 `CompositionMode_Plus` 发光叠加绘制双层霓虹弧）。
      - 下方镜面倒影拱控制点位于 $y_{\text{stage}} + 0.35 h_{\text{arc}}$（透明度乘以 `0.28`，营造水面反射感）。

### 特殊模式 3：3D 全息透视立体柱阵 / DNA 双螺旋 (3D Isometric Hologram & Helix)
- **核心概念**：脱离二维平面，使用真实的三维坐标变换与立体三面光影（顶面、正面、右侧面）渲染 3D 悬浮螺旋或立体柱阵。
- **实现细节**：
  - 引入旋转角相位 $\phi(t)$（随帧时间缓慢自转，或支持鼠标水平拖拽改变视角 Yaw 角）。
  - 将元素排列在 3D 空间中的双螺旋轨道（或 3D 斜向透视画廊）上：
    - 对索引 $i$，归一化位置 $u = \frac{i}{N} - 0.5 \in [-0.5, 0.5]$，螺旋角 $\alpha_i = 4\pi u + \phi$。
    - 3D 坐标：$X_i = u \times W \times 0.85$，$Z_i = \sin(\alpha_i) \times R_{3D}$，$Y_i = \cos(\alpha_i) \times 0.25 R_{3D}$。
    - 透视投影缩放系数：$s_i = \frac{\text{fov}}{\text{fov} + Z_i + D_{\text{cam}}}$。
  - **画家算法深度排序（Painter's Algorithm）**：按 $Z_i$ 从远到近排序后，使用 `QPolygonF` 为每个元素绘制具有**顶面高光（亮度 130%）、正面渐变（亮度 100%）、侧面阴影（亮度 65%）**的 3D 立体棱柱，正在比较/交换的棱柱发出高亮体积光。

### 特殊模式 4：流体极光丝带图 (Aurora Smooth Spline Ribbons)
- **核心概念**：用连续丝滑的多层样条曲面（Catmull-Rom / Cubic Bezier Spline）取代离散的柱子，完全消除颗粒感。
- **实现细节**：
  - 若 $N > 180$，对数组按滑动窗口提取 $M = 120$ 个平滑锚点，计算对应的屏幕坐标 $(x_k, y_k)$。
  - 使用三次贝塞尔曲线平滑算法（计算相邻点切线控制点 $C_1, C_2$）构造连续闭合的 `QPainterPath`。
  - 绘制 3 层相位与高度略有错位的极光波浪带，内部使用垂直 `QLinearGradient`（顶部为高亮青/紫/金霓虹色 `alpha=180`，底部渐变为透明 `alpha=10`）进行丝绸般的曲面填充，顶部边缘用 `2.5px` 亮线勾勒。
  - 发生 `CMP/SWAP` 的位置在极光波峰处綻放径向发光光球（`QRadialGradient`）。

### 特殊模式 5：3D 高光玻璃球与抛物线飞跃 (3D Glossy Spheres & Parabolic Flight)
- **核心概念**：每个元素是一颗具有立体高光反射的 3D 玻璃球，且在交换时具有平滑的抛物线飞行轨迹与彗星尾迹。
- **实现细节**：
  - **球体材质渲染**：对每个元素球心 $(x_i, y_i)$、半径 $r_i = \text{clip}(W / (1.8 N), 4, 18)$，使用 `QRadialGradient(cx - 0.3*r, cy - 0.3*r, 1.3*r)`：
    - `stop(0.0)` 为纯白高光点 `#FFFFFF`；
    - `stop(0.35)` 为元素主色相；
    - `stop(0.85)` 为深色球体边缘暗部；
    - `stop(1.0)` 为透明边缘。
  - **飞跃轨迹**：当 `i` 和 `j` 正在发生交换时，绘制连接两球心的上下对称发光抛物线轨迹与 5 个残影小球，直观呈现两颗玻璃球在空中交错换位的动感。

### 特殊模式 6：低多边形宝石晶格网 (Low-Poly Crystal Mesh)
- **核心概念**：将元素映射为二维空间中的晶格顶点，构建带有切面光影渐变的三角/四边形宝石网格。
- **实现细节**：
  - 将数组索引映射为 $R \times C$ 网格（或沿对角线分布的波浪带顶点），每个顶点的坐标偏移量由当前元素与有序位置的偏差 $(\text{norm}_i - i/N)$ 决定：乱序时顶点剧烈扭曲交错，排好序时恢复为工整匀称的晶格。
  - 连接相邻顶点构成三角形切面 `(A, B, C)`，根据三个顶点的数值均值计算切面颜色与法线明暗度，使用 `QPainter.drawPolygon` 填充半透明宝石切面并用细亮线描边。

---

## 请立即执行以下修改：
1. 在 `ui/canvas_widget.py` 中全面启用抗锯齿、残影缓冲层（`trail_pixmap`）、发光叠加模式（`CompositionMode_Plus`）以及上述 **6 种次世代特殊视图**。
2. 在 `ui/main_window.py` 的工具栏中更新视图选择下拉框，并新增一个 **“导入自定义图片 (用于切片还原模式)”** 按钮。
3. 请直接输出修改后的完整代码，确保无任何省略或占位符号。