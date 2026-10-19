# UI 可视化引擎全面升级指令：构建 9 种高表现力特色可视化视图

请在 `ui/canvas_widget.py` 与 `ui/main_window.py` 中升级可视化渲染引擎。移除原有的“普通阿基米德螺旋图”和“二维色块矩阵”，在保留基础视图（经典柱状图、极坐标色环、散点图）的同时，完整实现以下 **9 种特色可视化样式**（包含之前确认的 4 种 + 全新扩充的 5 种创意视图）。

---

## 全局渲染与性能约束 (Performance & Color Rules)
1. **颜色语义统一**：所有视图必须严格遵循状态着色——默认元素使用 HSV 彩虹色相（$\text{Hue} = 300^\circ \times \text{norm\_i}$）或纯净白；`CMP` 比较高亮为亮柠檬黄 `#FFEA00`；`SWAP/SET` 交换写入高亮为珊瑚红 `#FF2A55`；`PIVOT` 基准高亮为霓虹紫 `#B537F2`；`SORTED` 已就位高亮为翠绿 `#00E676`。
2. **向量化与降采样防卡顿保护**：
   - 坐标计算必须使用 `NumPy` 向量化运算，绘图调用 `QPainter.drawLines` / `drawRects` / `drawPoints` 批量接口。
   - 对于涉及密集连线或树节点的视图（如双轨织布机、捕梦网弦图、完全二叉树），当 $N > 512$ 时，自动启用**均匀步长降采样（Downsampling Step $s = \lceil N / 512 \rceil$）**，同时强制保留所有当前正处于 `CMP / SWAP / PIVOT` 高亮状态的索引，确保在 $N = 10,000$ 下依然稳如磐石地跑满 60 FPS。

---

## 第一组：已确认保留的 4 种核心特色视图

### 样式 1：对称声波图 (Mirrored Audio Waveform)
- **几何原理**：以画布垂直中心线 $y_{\text{mid}} = y_0 + H / 2$ 为轴，每个元素上下对称绘制垂直声波柱。
- **坐标公式**（设归一化值 $\text{norm}_i = \frac{\text{val}_i - \text{min}}{\text{max} - \text{min}} \in [0, 1]$）：
  - $x_i = x_0 + (i + 0.5) \times \frac{W}{N}$，半高 $h_i = \max\left(2.0, \text{norm}_i \times 0.46 H\right)$。
  - 纵向线段/柱体区间：$[y_{\text{mid}} - h_i, \ y_{\text{mid}} + h_i]$。
- **视觉增强**：中心绘制暗灰基准轴；高亮元素的上下端点附加发光圆点，排好序后收敛为平滑对称的梭形号角。

### 样式 2：极坐标偏差收缩环 (Disparity Ring / Radial Error Dots)
- **几何原理**：圆周角表示当前索引 $i$，半径表示当前位置与目标有序位置之间的距离误差（误差越大越向圆心收缩，排对位置则贴合最外圈）。
- **坐标公式**：
  - 圆心 $(c_x, c_y) = (x_0 + W/2, y_0 + H/2)$，$R_{\max} = 0.44 \min(W, H)$。
  - 角度 $\theta_i = 2\pi \frac{i}{N} - \frac{\pi}{2}$，目标归一化排名 $t_i = \text{norm}_i \times (N - 1)$。
  - 归一化环向最短距离误差 $\text{err}_i = \frac{\min(\vert{}i - t_i\vert{}, \ N - \vert{}i - t_i\vert{})}{N / 2} \in [0, 1]$。
  - 实际半径 $r_i = R_{\max} \times (1.0 - 0.82 \times \text{err}_i)$，坐标 $(x_i, y_i) = (c_x + r_i \cos\theta_i, \ c_y + r_i \sin\theta_i)$。
- **视觉增强**：先画暗色外圈 $R_{\max}$，再画从外圈锚点指向实际点 $(x_i, y_i)$ 的半透明径向牵引细线与高亮圆点。

### 样式 3：居中金字塔堆叠图 (Centered Horizontal Pyramid)
- **几何原理**：从上到下按索引 $0 \sim N-1$ 堆叠水平横条，沿水平中轴线 $x_{\text{mid}} = x_0 + W / 2$ 左右对称居中。
- **坐标公式**：
  - $y_i = y_0 + i \times \frac{H}{N}$，半宽 $w_i = \max\left(2.0, \text{norm}_i \times 0.45 W\right)$。
  - 横向区间：$[x_{\text{mid}} - w_i, \ x_{\text{mid}} + w_i]$。

### 样式 4：残差位移火柴图 (Displacement Error Stems)
- **几何原理**：以理想有序对角线为基准，绘制每个元素当前实际高度到理想高度的垂直偏差火柴杆。
- **坐标公式**：
  - $x_i = x_0 + (i + 0.5) \times \frac{W}{N}$。
  - 理想纵坐标 $y_{\text{ideal}, i} = y_0 + 0.95 H - \frac{i}{N - 1} \times 0.90 H$。
  - 实际纵坐标 $y_{\text{actual}, i} = y_0 + 0.95 H - \text{norm}_i \times 0.90 H$。
- **视觉增强**：绘制连接 $(x_i, y_{\text{ideal}, i})$ 与 $(x_i, y_{\text{actual}, i})$ 的垂直线段，并在 $(x_i, y_{\text{actual}, i})$ 绘制圆头。排好序时所有杆长缩为 0，圆头严丝合缝落在对角线上。

---

## 第二组：全新扩充的 5 种高概念创意视图

### 样式 5：时空瀑布流 / 历史轨迹图 (Spacetime Waterfall / Kymograph)
- **几何原理**：将画布分为上下两部分——**上方 78% 为滚动的二维时空历史瀑布（横轴为数组索引 $i$，纵轴为时间帧 $t$）**，**下方 22% 为当前实时迷你柱状图**。
- **实现机制**：
  - 维护一个固定尺寸（例如宽 $W_{\text{tex}} = \min(N, 1024)$、高 $H_{\text{tex}} = 360$）的 `NumPy uint8 RGB` 环形滚动图像缓冲区 `waterfall_buf`。
  - 每推进一帧渲染，将 `waterfall_buf` 整体向上平移 1 行（`np.roll(buf, -1, axis=0)`），并将当前帧数组各元素的颜色（按数值映射彩虹色，正在 `CMP/SWAP` 的位置涂成纯白/亮黄亮点）写入最后一行。
  - 使用 `QImage` 将 `waterfall_buf` 缩放绘制在画布上方 78% 区域。
- **视觉效果**：观众可以直观看到快速排序的分形三角洲、归并排序的编织水波、基数排序的分层色带以及希尔排序的斜向条纹随时间演化的全过程。

### 样式 6：平行双轨织布机 / 逆序对连线图 (Parallel Loom / Inversion Threads)
- **几何原理**：利用二部图连线直观展示**“逆序对（Inversions）”**——两条线的每一个交叉点即代表一对逆序元素。
- **坐标公式**：
  - 上导轨（当前位置轨）：$y_{\text{top}} = y_0 + 0.15 H$，当前横坐标 $x_{\text{curr}, i} = x_0 + 0.04 W + \frac{i}{N - 1} \times 0.92 W$。
  - 下导轨（目标有序轨）：$y_{\text{bot}} = y_0 + 0.85 H$，目标横坐标 $x_{\text{target}, i} = x_0 + 0.04 W + \text{norm}_i \times 0.92 W$。
  - 对每个元素绘制一条连接 $(x_{\text{curr}, i}, y_{\text{top}})$ 到 $(x_{\text{target}, i}, y_{\text{bot}})$ 的彩色抗锯齿直线（透明度 `Alpha = 140`，正在 `CMP/SWAP` 的元素连线加粗且 `Alpha = 255` 置顶绘制）。
- **视觉效果**：乱序时如交错纠缠的彩色丝线织布机；每次交换都会解开交叉的线条；当完全排好序时，$x_{\text{curr}, i} = x_{\text{target}, i}$，所有斜线瞬间全部立正，化作一排严格垂直的平行光柱！

### 样式 7：极坐标鹦鹉螺放射柱 (Radial Nautilus / Sunburst Corona)
- **几何原理**：以圆心内环 $R_{\text{inner}} = 0.12 \min(W, H)$ 为起点，每个元素沿角度 $\theta_i$ 向外发射一根长度与数值成正比的放射能量柱。
- **坐标公式**：
  - 角度 $\theta_i = 2\pi \frac{i}{N} - \frac{\pi}{2}$。
  - 外端半径 $R_{\text{outer}, i} = R_{\text{inner}} + \text{norm}_i \times 0.34 \min(W, H)$。
  - 绘制从 $(c_x + R_{\text{inner}}\cos\theta_i, c_y + R_{\text{inner}}\sin\theta_i)$ 到 $(c_x + R_{\text{outer}, i}\cos\theta_i, c_y + R_{\text{outer}, i}\sin\theta_i)$ 的径向粗线段。
- **视觉效果**：中心绘制发光暗环，乱序时呈赛博朋克放射频谱；排好序后外边缘顺时针由短到长平滑展开，形成黄金鹦鹉螺壳轮廓。

### 样式 8：圆环错位捕梦网 (Circular Disparity Chords / Dreamcatcher Web)
- **几何原理**：在半径为 $R = 0.44 \min(W, H)$ 的圆周上，连接每个元素的“当前索引角度 $\theta_{\text{curr}, i}$”与“目标有序角度 $\theta_{\text{target}, i}$”。
- **坐标公式**：
  - $\theta_{\text{curr}, i} = 2\pi \frac{i}{N} - \frac{\pi}{2}$，$\theta_{\text{target}, i} = 2\pi \cdot \text{norm}_i - \frac{\pi}{2}$。
  - 起点 $P_1 = (c_x + R\cos\theta_{\text{curr}, i}, \ c_y + R\sin\theta_{\text{curr}, i})$，终点 $P_2 = (c_x + R\cos\theta_{\text{target}, i}, \ c_y + R\sin\theta_{\text{target}, i})$。
  - 在圆周 $P_1$ 处绘制元素高亮点，并在 $P_1$ 与 $P_2$ 之间绘制半透明彩色弦线（`Alpha = 110`，高亮元素 `Alpha = 255` 且线宽加倍）。
- **视觉效果**：未排序时圆环内部交织出华丽的几何万花筒弦网；随着排序进行，弦线不断向圆周边缘收缩，排好序时内部网格彻底消失，化作一圈纯净圆环。

### 样式 9：隐式完全二叉树拓扑图 (Implicit Binary Tree / Heap Topology)
- **几何原理**：将数组索引 $0 \dots M-1$（其中 $M = \min(N, 255)$，取前 8 层完全二叉树以保证节点清晰不重叠）映射为完全二叉树结构，父节点为 $\lfloor (i-1)/2 \rfloor$。
- **坐标公式**：
  - 总层数 $D = \lfloor \log_2(M) \rfloor + 1$。
  - 对每个节点 $i \in [0, M-1]$：
    - 所在层级 $d = \lfloor \log_2(i + 1) \rfloor$，层内偏移 $k = i - (2^d - 1)$，该层总容量 $2^d$。
    - 节点横坐标：$x_i = x_0 + \frac{k + 0.5}{2^d} \times W$。
    - 节点纵坐标：$y_i = y_0 + 0.08 H + \frac{d}{\max(1, D - 1)} \times 0.84 H$。
  - **绘制层级**：
    1. 先绘制所有父子节点之间的连线 $(x_{\text{parent}}, y_{\text{parent}}) \to (x_i, y_i)$（若父子双方正在发生 `CMP` 或 `SWAP`，连线染成亮黄或亮红色并加粗，直观展示堆的下沉 Sift-Down 与上浮 Sift-Up 路径）。
    2. 再在每个 $(x_i, y_i)$ 处绘制实心圆节点，节点颜色按数值映射彩虹色或状态高亮色，节点半径 $r_i = 3 + \text{norm}_i \times 6$。

---

## 请立即执行以下更新：
1. 在 `ui/canvas_widget.py` 中完整实现上述全部可视化样式的向量化渲染方法，并维护好样式 5 的 `waterfall_buf` 状态重置逻辑。
2. 在 `ui/main_window.py` 的视图下拉菜单中注册全部样式名称（支持在排序运行过程中随时无缝切换）。
3. 直接输出更新后的完整代码，严禁使用占位符省略实现。