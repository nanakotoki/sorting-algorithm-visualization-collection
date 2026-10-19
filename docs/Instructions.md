Role & Objective
你是一位顶级的桌面软件架构师与算法可视化专家。请根据本规范文档，开发一款名为 Sorting Visualizer Ultimate 的专业级数据排序可视化桌面系统，具备以下核心特性：
1. 内置 160 种完整排序算法库（涵盖 11 大分类模块，从基础交换、选择、堆与树结构、插入与希尔全增量序列、快排全变体、归并全变体、现代工业级块归并排序、基数/分布排序、并行排序网络、煎饼翻转到趣味教学排序）。
2. 支持外部多语言自定义算法接入（支持用户使用 C, C++, Python, Java, Rust, Go, JavaScript, C# 编写自己的排序代码并导入实时可视化）。
3. 高清一目了然的实时可视化与状态看板（支持用户自由设定数据量 N、8 种初始数据分布、5 种几何视图、主数组+辅助数组双视图分屏、实时音效合成及单步回溯调试）。
4. 内置 1080P/4K @ 60FPS 离线视频导出器（基于 FFmpeg 管道离屏逐帧渲染，音画完全同步，绝不掉帧）及一键打包独立 .exe 方案。
1. 技术栈与性能优化规范 (Tech Stack & High-Performance Design)
请在以下两套高性能技术栈中根据指令执行（若未特别指定，默认采用【方案 A：Python + PySide6 向量化高性能方案】；若指定使用 Rust 或 C++，则对应切换至原生方案）：
方案 A（默认推荐：Python 向量化批处理渲染方案）
* 核心语言：Python 3.11+
* GUI 与布局：PySide6 (Qt6)，采用深色极客主题，左侧为带搜索过滤的 160 算法分类树（QTreeWidget），右侧为渲染主画布与顶部 HUD 状态面板，底部为时间轴与参数控制栏。
* 渲染性能优化（关键约束）：严禁使用 Python for 循环逐根调用 drawRect！必须使用 NumPy 批量计算所有柱子/点位的屏幕坐标，并构造 QPolygonF / QLineF 列表或直接操作 NumPy RGB Buffer 生成 QImage 进行单次位图块传输（BitBlt），确保在 N=10,000 数据量下依然稳定保持 60 FPS+。
* 音效合成引擎：NumPy + sounddevice 实时生成正弦波/三角波音效（含 ADSR 包络防爆音）；离线导出时使用 scipy.io.wavfile 生成完整音轨。
* 视频导出与打包：subprocess 调用 FFmpeg 管道推流 + PyInstaller 打包 .exe。
方案 B（备选：Rust 原生单文件 .exe 极速方案）
* 核心语言与框架：Rust (2021 Edition) + eframe / egui（即时模式 GUI）+ cpal（低延迟音频合成）+ rayon（数据生成并行加速），通过 cargo build --release 生成单文件 .exe。
2. 核心架构设计 (Core System Architecture)
2.1 统一数组包装器与原子操作协议 (VisualArray & Trace Protocol)
无论是内置的 160 种算法还是外部多语言脚本，均通过统一的索引操作接口执行，确保状态统计、颜色高亮、音效触发与单步回退 100% 准确：
1. 核心原子操作与指令集：
   * CMP <i> <j>：比较主数组索引 i 和 j（黄色高亮 i, j，触发双音高合成音效，比较次数 +1，数组读取次数 +2）。
   * CMP_VAL <i> <val>：将主数组索引 i 与外部寄存器/临时变量值 val 比较（比较次数 +1，读取次数 +1）。
   * SWAP <i> <j>：交换主数组索引 i 和 j（珊瑚红高亮 i, j，交换次数 +1，主存写入次数 +2，总访问次数 +4）。
   * SET <i> <val>：将主数组索引 i 覆写为 val（珊瑚红高亮 i，主存写入次数 +1，总访问次数 +1）。
   * FLIP <left> <right>：将主数组区间 [left, right] 原地对称翻转（专用于煎饼排序、手摇块旋转归并等，触发区间扫光动画，交换次数 +(right-left+1)//2）。
   * AUX_INIT <size>：初始化长度为 size 的辅助数组（画布自动开启上下分屏模式，上方展示主数组，下方展示辅助数组）。
   * AUX_SET <i> <val>：向辅助数组索引 i 写入 val（青色高亮辅助数组位置 i，辅助数组写入次数 +1）。
   * AUX_SWAP <i> <j>：交换辅助数组索引 i 和 j（辅助数组写入次数 +2）。
   * AUX_CLEAR：销毁并收起辅助数组分屏视图。
   * MARK <i> <role>：标记特定索引状态（PIVOT 霓虹紫基准值、BOUNDARY 电光青区间边界、HEAP_ROOT 橙色堆顶、SORTED 翠绿已就位）。
   * CLEAR_MARKS：清除所有临时状态标记。
   * MSG <text>：更新 HUD 看板上的实时阶段解说文本。
2. 步进生成与倍速控制机制：
   * 内置算法使用生成器（yield）或指令环形缓冲区。
   * 渲染器根据用户设定的速度档位控制 每渲染帧消化的原子操作步数（Steps Per Frame, SPF）：
      * 慢动作教学档：每 K 帧执行 1 步（支持看清每一次指针移动）。
      * 标准观赏档：每帧执行 1 \sim 50 步。
      * 极速/大数据档：每帧批量执行 100 \sim 5,000 步，仅在帧末重绘一次画面。
2.2 插件式算法注册架构 (Plugin Registry Pattern)
由于内置算法数量高达 160 种，严禁使用硬编码的 if-elif 分发。必须实现装饰器注册机制：
@register_algo(
   algo_id="076_dual_pivot_quicksort",
   name_zh="双轴快速排序",
   name_en="Dual-Pivot Quick Sort (Yaroslavskiy)",
   category="05. 快速排序家族 (Quick Sorts)",
   time_best="O(n log n)",
   time_avg="O(n log n)",
   time_worst="O(n^2)",
   space="O(log n)",
   stable=False,
   desc="选取两个基准值将数组切分为三段递归，具备更高的缓存局部性，为 Java Arrays.sort 底层算法。"
)
def dual_pivot_quicksort(arr: VisualArray):
   ...

UI 启动时自动扫描 algorithms/ 目录下的所有模块，生成左侧按类别折叠的算法树形导航栏（带中英文实时搜索过滤框）。
3. 内置 160 种排序算法完整目录 (Comprehensive 160-Algorithm Catalog)
请在 algorithms/ 目录下按以下 11 个分类模块 实现全部 160 种 排序算法（同源参数化变体可通过高阶工厂函数优雅生成，严禁使用 pass 或空函数占位）：
类别 01：cat01_exchange.py — 交换类排序 (18 种)
1. Bubble Sort (Standard) | 标准冒泡排序：基础相邻比较交换。
2. Optimized Bubble Sort | 提前终止冒泡排序：带 swapped 标志与最后交换边界收缩记忆。
3. Cocktail Shaker Sort | 鸡尾酒排序（双向冒泡）：左右交替双向扫描冒泡。
4. Optimized Cocktail Shaker Sort | 自适应边界鸡尾酒排序：记录左右两端最后交换位置，大幅跳过有序区。
5. Odd-Even Sort (Brick Sort) | 奇偶砖块排序：奇数对与偶数对交替并行比较交换。
6. Gnome Sort (Stupid Sort) | 标准地精排序：单个指针向前扫描，遇逆序则一路交换回退。
7. Optimized Gnome Sort | 跳跃记忆地精排序：回退交换前记录原位置，插好后直接跳回原处而非一步步重走。
8. Comb Sort (Shrink 1.3) | 标准梳排序（收缩因子 1.3）：消除冒泡排序尾部“乌龟（小元素在末尾）”问题。
9. Comb Sort (Shrink 1.2473) | 黄金经验因子梳排序：采用 1/(1-e^{-\phi}) \approx 1.24733 收缩因子。
10. Comb Sort 11 | 梳排序 11 变体：强制间距序列包含 9 或 10 时修正为 11，提升收敛效率。
11. Hybrid Comb-Insertion Sort | 梳排序+插入混合排序：当间距缩小至 \le 8 时切换为直接插入排序收尾。
12. Circle Sort (Recursive) | 递归圆圈排序：将区间首尾对称位置配对比较交换，再递归左右两半，直到某轮无交换。
13. Circle Sort (Iterative) | 非递归圆圈排序：使用循环迭代实现的对称同心圆比较排序。
14. Proportion Extend Sort | 比例扩展交换排序：按比例逐步扩大有序前缀并与后缀对称交换。
15. Shove Sort (Chinotto Sort) | 推挤排序：扫描时一旦发现逆序，将较大元素一路相邻交换推到数组最末端。
16. Push Sort | 推入交换排序：渐进累积最大元素群并整体向后推入。
17. Room Sort | 房间局部块交换排序：以移动窗口（Room）为单位做局部冒泡推进。
18. Slope Sort | 斜率下降交换排序：按斜率阶梯式向下逐个交换归位。
类别 02：cat02_selection_cycle.py — 选择、锦标赛与循环置换排序 (12 种)
1. Selection Sort | 标准简单选择排序：每趟寻找未排序区最小值交换至前端。
2. Double Selection Sort (Cocktail Selection) | 双向选择排序：单趟扫描同时找出最小值与最大值，分别交换至首尾两端。
3. Stable Selection Sort | 稳定选择排序：找到最小值后不使用跨位置 SWAP，而是通过区间整体右移插入以保持相等元素稳定性。
4. Bingo Sort | 宾果排序：扫描记住当前最大值 max_val，下一趟将所有等于 max_val 的重复元素一次性移到位（针对大量重复值极快）。
5. Cycle Sort (Standard) | 标准圈排序：计算每个元素前方有多少个比它小的元素以确定目标坐标，沿着置换环写回，实现理论最少主存写入次数。
6. Optimized In-Place Cycle Sort | 优化原地圈排序：快速跳过已处于正确位置的元素与重复值环。
7. Tournament Sort (Winner Tree) | 胜者树锦标赛排序：在辅助空间构建完全二叉树胜者树，每次提取树根最小值并沿路径更新。
8. Loser Tree Sort | 败者树锦标赛排序：父节点记录败者、冠军向上传递，减少重构时的兄弟节点访问。
9. Cartesian Tree Sort | 笛卡尔树排序：线性时间构建满足堆性质的笛卡尔树，再结合优先队列按序提取。
10. Sandpaper Sort | 砂纸选择交换排序：二重循环遍历中只要 arr[i] > arr[j] 就立即交换（形似冒泡但固定左端点 i）。
11. Roll Sort | 滚动选择排序：动态维护最小滚动窗口的选择变体。
12. Min-Max Heap Sort | 双端最小最大堆排序：奇数层为小顶堆、偶数层为大顶堆，同时从两端收缩归位。
类别 03：cat03_heaps_trees.py — 堆与树结构排序全家族 (18 种)
1. Max-Heap Sort (Floyd Sift-Down) | 标准大顶堆排序：使用 O(N) Floyd 自底向上下沉建堆 + 逐个弹出堆顶。
2. Max-Heap Sort (Williams Sift-Up) | 自顶向下建堆排序：使用 Williams 逐个元素上浮插入建堆。
3. Min-Heap Sort | 小顶堆排序：建立小顶堆降序排列后通过 FLIP 翻转为升序。
4. Bottom-Up Heap Sort (Wegener) | 自底向上堆排序：堆顶移走后，先沿较大子节点一路无比较下沉至叶节点，再向上回溯寻找插入位置（逼近 1.5 N \log N 次比较）。
5. Ternary Heap Sort (3-ary Heap) | 三叉堆排序：每个节点拥有 3 个子节点，降低树高。
6. Quaternary Heap Sort (4-ary Heap) | 四叉堆排序：每个节点拥有 4 个子节点，减少下沉层数。
7. Octonary Heap Sort (8-ary Heap) | 八叉堆排序：扇出度为 8 的宽扁堆结构展示。
8. Weak Heap Sort (Dutton) | 弱堆排序：根节点无左子树，使用翻转位（Reverse Bit）数组切换左右孩子角色，比较次数仅约 N \log_2 N + 0.09N。
9. Smoothsort (Dijkstra) | 平滑排序：基于莱昂纳多数（Leonardo Numbers L(k) = L(k-1)+L(k-2)+1）森林构建的自适应堆排序，基本有序时退化为 O(N)。
10. Poplar Sort | 白杨堆排序：维护大小呈二次幂减一的完美二叉堆森林，无需莱昂纳多数表即可原地堆化。
11. Ternary Smoothsort Variant | 三叉平滑堆变体：扩展子树合并规则的平滑堆。
12. Binomial Heap Sort | 二项堆排序：在辅助空间模拟二项树合并与提取最小根过程。
13. Fibonacci Heap Sort | 斐波那契堆排序：展示延迟度数合并（Consolidate）的堆抽取过程。
14. Pairing Heap Sort | 配对堆排序：展示两两配对（Two-Pass Pairing）合并子树的高效自调整堆排序。
15. Skew Heap Sort | 斜堆排序：每次合并无条件交换左右子树的自适应堆排序。
16. Binary Search Tree Sort (Unbalanced) | 朴素二叉搜索树排序：构建 BST 并通过中序遍历写回主数组。
17. AVL Tree Sort | AVL 平衡树排序：带 LL/RR/LR/RL 旋转平衡的二叉搜索树排序。
18. Treap Sort (Randomized BST) | 树堆排序：结合随机优先级旋转维护平衡的笛卡尔树堆排序。
类别 04：cat04_insertion_shell.py — 插入与希尔排序全家族 (20 种)
1. Insertion Sort (Standard) | 标准直接插入排序：从左向右逐个将元素向左平移插入。
2. Binary Insertion Sort | 二分查找插入排序：使用二分搜索定位插入点，减少比较次数至 O(N \log N)。
3. Exponential Binary Insertion Sort | 指数倍增二分插入排序：从已排序区末尾向左按 1, 2, 4, 8\dots 倍增探测边界后再二分，在近乎有序数组上达到 O(N)。
4. Pair Insertion Sort | 成对双元素插入排序：每次同时取出两个元素，先排好大小，再在一次扫描中先后插入两个值（JDK DualPivotQuicksort 底层技术）。
5. Pin Insertion Sort | 针式双端插入排序：以中间值为锚点，小元素向左侧插入，大元素向右侧插入。
6. Unguarded Insertion Sort | 无哨兵边界插入排序：先将全局最小值置于 arr[0] 充当哨兵，内层循环省去 j >= 0 边界判断。
7. Shell Sort (Original Shell 1959) | 原始希尔序列：步长 h_k = \lfloor N / 2^k \rfloor，最坏情况可能退化为 O(N^2)。
8. Shell Sort (Frank & Lazarus 1960) | Frank-Lazarus 奇化序列：h_k = 2\lfloor N / 2^{k+1} \rfloor + 1（强制步长为奇数，打破偶下标隔离）。
9. Shell Sort (Hibbard 1963) | Hibbard 序列：h_k = 2^k - 1 \ (1, 3, 7, 15, 31, 63\dots)，最坏复杂度 O(N^{3/2})。
10. Shell Sort (Papernov & Stasevich 1965) | Papernov-Stasevich 序列：h_k = 2^k + 1（首项补 1：1, 3, 5, 9, 17, 33\dots）。
11. Shell Sort (Pratt 1971 Smooth) | Pratt 3-光滑数序列：h = 2^p 3^q \ (1, 2, 3, 4, 6, 8, 9, 12\dots)，理论最优最坏复杂度 O(N \log^2 N)。
12. Shell Sort (Knuth 1973) | Knuth 序列：h_k = (3^k - 1) / 2 \ (1, 4, 13, 40, 121, 364\dots)。
13. Shell Sort (Sedgewick 1982) | Sedgewick 1982 序列：h_k = 4^k + 3 \cdot 2^{k-1} + 1 \ (1, 8, 23, 77, 281\dots)，最坏 O(N^{4/3})。
14. Shell Sort (Incerpi & Sedgewick 1985) | Incerpi-Sedgewick 互质表序列：基于互质乘积构造的高效步长。
15. Shell Sort (Sedgewick 1986 Interleaved) | Sedgewick 1986 交错序列：奇偶项交替采用 9(2^k - 2^{k/2}) + 1 与 8\cdot 2^k - 6\cdot 2^{(k+1)/2} + 1 \ (1, 5, 19, 41, 109\dots)。
16. Shell Sort (Gonnet & Baeza-Yates 1991) | Gonnet 5/11 序列：h_{k} = \max(\lfloor 5 h_{k-1} / 11 \rfloor, 1)，连续除约 2.2。
17. Shell Sort (Tokuda 1992) | 德田（Tokuda）序列：h_k = \lceil (9 \cdot (9/4)^{k-1} - 4) / 5 \rceil \ (1, 4, 9, 20, 46, 103, 233\dots)。
18. Shell Sort (Ciura 2001 Empirical) | Ciura 最佳经验序列：1, 4, 10, 23, 57, 132, 301, 701, 1750（后续按 \lfloor 2.25 h \rfloor 扩展，实测平均最快）。
19. Library Sort (Gapped Insertion) | 图书馆排序：在辅助数组中预留空白间隙（Gaps）做二分插入，每当插入满 2^k 个元素则重平衡均匀拉开间隙。
20. Patience Sort | 耐心排序：模拟纸牌接龙（Solitaire），利用二分查找将元素分入若干单调递减牌堆，再用最小堆做多路归并写回。
类别 05：cat05_quicksorts.py — 快速排序全家族 (16 种)
1. Quick Sort (Lomuto Partition) | Lomuto 单路快排：单侧同向快慢指针扫描分区。
2. Quick Sort (Hoare Partition) | Hoare 双指针快排：左右两端相向扫描交换的经典快排。
3. Quick Sort (LL Double Left Pointer) | 双左指针快排：两个指针均从左端出发的分区变体。
4. Quick Sort (Random Pivot) | 随机化基准快排：每次随机选取区间内一个位置作为 Pivot，抵御逆序/特定构造数据退化。
5. Quick Sort (Median-of-Three) | 三数取中快排：取左、中、右三点中位数作基准 + 尾递归优先处理短区间优化。
6. Quick Sort (Median-of-Five) | 五数取中快排：采样 5 个位置取中位数作基准。
7. Quick Sort (Tukey's Ninther) | 九数取中快排：将 9 个采样点分为 3 组分别取中位数，再取这 3 个中位数的中位数作为极稳健 Pivot。
8. Dual-Pivot Quick Sort (Yaroslavskiy) | 双轴快速排序：选取 P_1 \le P_2 两个基准，将数组切分为 < P1、P1..P2、> P2 三段递归（更高缓存命中率）。
9. Multi-Pivot Quick Sort (3-Pivot 4-Way) | 三轴四路快速排序：使用 3 个有序基准将数组切分为 4 个子区间同时推进。
10. 3-Way Quick Sort (Dutch National Flag) | 荷兰国旗三路切分快排：Dijkstra 经典算法，分为 < P、== P、> P 三段，遇到大量重复元素时直接 O(N) 结束。
11. Bentley-McIlroy 3-Way Quick Sort | Bentley-McIlroy 快速三路切分：扫描时将等于基准的元素先交换堆积在区间左右最外端，分区结束后再将两端相等元素翻转回中心（减少无重复元素时的额外交换）。
12. Iterative Quick Sort (Explicit Stack) | 显式栈非递归快排：在代码中维护区间栈并高亮待处理栈区间。
13. Stable Quick Sort (Auxiliary Buffer) | 外部辅助空间稳定快排：利用辅助数组按原相对顺序稳定划分左右分区。
14. In-Place Stable Quick Sort | 原地旋转稳定快排：基于分治与手摇块旋转（Block Rotation）实现的 O(1) 空间稳定分区快排。
15. BlockQuicksort (Branchless Buffer) | 块缓冲无分支快排：先在局部小索引缓冲记录两侧待交换偏移量，装满后再批量执行 SWAP，可视化呈规律跳跃脉冲。
16. Proportion Split Quick Sort | 比例分割快排：先对局部样本排序，按固定分位数比例选取基准切分。
类别 06：cat06_mergesorts.py — 归并排序全家族 (14 种)
1. Merge Sort (Top-Down Recursive) | 自顶向下递归二路归并：经典分治并在辅助数组展示归并过程。
2. Merge Sort (Bottom-Up Iterative) | 自底向上迭代二路归并：按步长 1, 2, 4, 8, 16\dots 迭代归并，无递归调用。
3. 3-Way Merge Sort | 三路归并排序：每次将区间平分为 3 段递归并进行三指针归并。
4. 4-Way Merge Sort | 四路归并排序：四分治归并，树高减半。
5. Ping-Pong Merge Sort | 乒乓双向交替归并：奇数趟从主数组归并到辅助数组，偶数趟直接从辅助数组归并回主数组，省去 50% 的纯复制回写开销。
6. Natural Merge Sort | 自然归并排序：先线性扫描识别数据中天然存在的递增段与递减段（递减段原地 FLIP 转递增），再对自然有序段两两归并。
7. In-Place Merge Sort (Insertion Shifting) | 平移插入原地归并：不使用辅助数组，右半区元素较小时将左半区整块右移一格插入。
8. In-Place Merge Sort (Block Rotation) | 手摇块旋转原地归并：利用二分查找定位分割点，通过三次区间翻转（Gries-Mills Rotation）在 O(1) 额外空间内完成归并。
9. SymMerge (Symmetric In-Place Merge) | 对称旋转原地稳定归并：取两段中点做对称二分搜索与块旋转，递归合并左右子问题，仅需 O(N \log^2 N) 移动与严格 O(N \log N) 比较。
10. Weave Merge Sort | 奇偶交织归并排序：递归排好左右两半后，先将左右两半像洗牌一样奇偶交错穿插（Weave）在一起，再对其跑一遍极速插入排序（视觉效果极具韵律感）。
11. Rotate Merge Sort | 纯旋转分治归并排序：全程仅依赖区间翻转与二分查找实现的稳定原地排序。
12. Strand Sort | 抽丝排序：反复从剩余乱序区线性抽取一条单调递增子序列（Strand），并归并进有序结果区。
13. Drop-Merge Sort | 丢弃归并排序：针对接近有序的数据，线性扫描保留递增主干，将破坏单调性的少量乱序元素暂存至辅助区排序后再一把归并回来。
14. TwinSort | 成对迭代块归并排序：先扫描将相邻元素排成有序对（Twins），再通过半空间缓冲区高效迭代归并。
类别 07：cat07_hybrids_blocks.py — 现代工业级混合与 O(1) 块归并排序 (16 种)
1. TimSort | Python/Java 工业级排序：计算最佳 minrun（32~64）+ 自然单调段识别 + 二分插入补齐 + 归并栈不变量维护 + Galloping（倍增指数跳跃）块归并。
2. Powersort | Python 3.11+ 新一代标准排序：Munro & Wild 提出，通过计算相邻有序段分界点的节点幂次（Node Power）构建近乎最优的归并顺序树，取代传统 TimSort 复杂的栈合并启发式规则。
3. Peeksort | 自适应窥探归并排序：自顶向下递归时从中点向左右两端窥探扩展天然单调段，若单调段覆盖全区间则瞬间 O(N) 完成。
4. IntroSort (Musser) | C++ std::sort 内省排序：三数取中快排为主，当递归深度超过 2\lfloor \log_2 N \rfloor 时自动切换为大顶堆排序防退化，小区间（\le 16）统一用插入排序收尾。
5. PDQSort (Pattern-Defeating Quicksort) | Rust 标准库非稳定排序：结合坏分区检测自动洗牌、已排序区间乐观无分支插入探测、三数/九数取中与堆排兜底。
6. Quadsort | 四路对称归并混合排序：结合奇偶四元素交换预处理、乒乓四路同时归并（Quad Merge）与尾部跳跃块归并。
7. Fluxsort | 自适应稳定分区归并排序：结合稳定三路快速分区与 Quadsort 归并引擎的现代极速稳定排序。
8. GrailSort (Simplified Block Merge) | 圣杯原地稳定块归并排序：无需任何外部内存（O(1) Space），先在数组前端收集 2\sqrt{N} 个互不相等的元素充当“内部缓冲区（Internal Buffer）”与块标签，将数组切分为 \sqrt{N} 大小的块进行块选择与块内局部归并。
9. SqrtSort | 平方根缓冲块归并排序：仅分配 \sqrt{N} 长度的极小辅助数组完成块选择与块归并。
10. WikiSort (Block Cache Merge) | 维基块缓存原地归并：基于小定长缓存与内部键块交换的 O(1) 空间稳定归并排序。
11. KotaSort | 科塔原地块交换归并：基于动态标记块与旋转的稳定块归并变体。
12. Vergesort | 宏观趋势侦测混合排序：先以 N / \log N 的大跨步跳跃侦测宏观有序或逆序大区块，将其合并后再对零散区调用快排/归并。
13. Spreadsort (Hybrid Distribution-Comparison) | Boost 混合分布比较排序：当数值跨度较大时先执行最高位分桶切分，当桶内元素小于阈值时切换为比较排序。
14. Ska Sort | 字节前缀原地分桶混合排序：按字节提取前缀统计偏移并做原地循环置换，小桶转 IntroSort。
15. Merge-Insertion Sort (Ford-Johnson) | Ford-Johnson 最少比较排序：先两两配对比较分为主链与副链，对主链递归排序后，严格按照雅各布斯塔尔数（Jacobsthal Numbers: 1, 3, 5, 11, 21\dots）顺序二分插入副链元素，逼近信息论比较下界 \lceil \log_2(N!) \rceil。
16. Quick-Shell Hybrid Sort | 快排+希尔混合排序：快排递归至中等粒度区间后切换为 Ciura 希尔排序收尾。
类别 08：cat08_distribution_radix.py — 非比较、基数与分布类排序 (18 种)
1. Counting Sort | 标准计数排序：在辅助空间展示频次统计、前缀和累加与稳定倒序回写。
2. In-Place Counting Sort | 原地计数排序：利用计数前缀边界在主数组内部直接循环交换归位。
3. Pigeonhole Sort | 鸽巢排序：针对值域紧凑的数据一对一映射分槽并顺序写回。
4. Bucket Sort (Uniform + Insertion) | 标准桶排序：按值域线性均匀分入 K 个桶（辅助数组展示），桶内执行插入排序后拼接。
5. Scatter Sort | 散射桶归并排序：多级均匀散射分桶后合并。
6. Radix Sort LSD (Base 2 / Binary) | 二进制 LSD 基数排序：从最低比特位（Bit 0）到最高比特位逐位执行稳定 0/1 分桶收集，形成极具科技感的二进制分层波浪动画。
7. Radix Sort LSD (Base 4) | 四进制 LSD 基数排序：每次按 2 个比特位（0~3 四个桶）分桶收集。
8. Radix Sort LSD (Base 8) | 八进制 LSD 基数排序：每次按 3 个比特位（0~7 八个桶）分桶收集。
9. Radix Sort LSD (Base 10) | 十进制 LSD 基数排序：按个位、十位、百位依次分入 0~9 十个桶。
10. Radix Sort LSD (Base 16) | 十六进制 LSD 基数排序：按半字节（Nibble，0~15 共 16 个桶）极速分桶收集。
11. In-Place LSD Radix Sort (Base 2) | 原地二进制 LSD 基数排序：不使用辅助数组，每一比特位扫描中遇到 0 则通过向左平移插入到零区末尾，全程原地保持稳定。
12. Radix Sort MSD (Base 2 / Binary Quicksort) | 二进制 MSD 基数交换排序（位级快排）：从最高有效比特位开始，使用左右双指针将最高位为 0 和 1 的元素原地交换切分，再递归下一比特位。
13. Radix Sort MSD (Base 4) | 四进制 MSD 基数排序：自顶向下按四进制高位递归分桶回写。
14. Radix Sort MSD (Base 10) | 十进制 MSD 基数排序：自顶向下按十进制高位递归分桶，小桶自动切换插入排序。
15. American Flag Sort | 美国国旗原地基数排序：McIlroy 经典算法，先统计各桶频次计算出每个桶的起始偏移边界，再通过原地循环置换（Cycle Permutation）把元素直接交换进对应桶槽，实现 O(1) 主存额外空间的 MSD 基数排序。
16. Flash Sort (Neubert) | 闪电排序：通过线性插值公式 L(A[i]) = 1 + \lfloor (m-1)(A[i]-A_{\min})/(A_{\max}-A_{\min}) \rfloor 统计约 0.43N 个分桶边界，通过原地循环置换将元素瞬间送入近似位置，最后用一趟插入排序极速收尾。
17. Postman Sort | 邮差排序：模拟邮政信件按省、市、区多级最高位分拣归并。
18. Gravity Sort (Bead Sort) | 算盘珠子重力下落排序：将每个正整数展开为水平算盘杆上的一排珠子，模拟珠子在重力作用下逐列同时坠落到底部的过程（极具视觉冲击力）。
类别 09：cat09_sorting_networks.py — 排序网络与并行映射排序 (12 种)
(注：所有排序网络算法均需通过越界判断或虚拟无穷大填充，完美适配任意非 2^k 数组长度，绝不在非 2 的幂次长度下崩溃) 133. Bitonic Sort (Recursive) | 递归双调排序网络：先构造先升后降的双调序列（Bitonic Sequence），再递归执行双调合并。 134. Bitonic Sort (Iterative Network) | 迭代位运算双调排序网络：双重位掩码循环直接驱动比较器对 (i, i \oplus j)，呈现极其工整的分形几何美感。 135. Batcher's Odd-Even Merge Sort (Recursive) | Batcher 递归奇偶归并网络：将有序两半拆分为奇数下标子列与偶数下标子列递归合并，再用相邻比较器修正。 136. Batcher's Odd-Even Merge Sort (Iterative) | Batcher 迭代奇偶归并网络：非递归位运算生成的奇偶归并比较器序列。 137. Pairwise Sorting Network (Parberry) | 成对比较排序网络：先按步长对奇偶配对元素排序分离大小，再按层级间距收敛比较。 138. Bose-Nelson Sorting Network | Bose-Nelson 递归排序网络：通过递归分治生成固定比较器对序列 star(i, len, j, len)。 139. Hibbard Sorting Network | Hibbard 位驱动排序网络：利用位运算状态机按字典序枚举比较器对。 140. Periodic Balanced Sorting Network | 周期平衡排序网络：Dowd 等人提出的对称折叠块多趟循环排序网络。 141. Shear Sort (2D Snake Matrix) | 二维蛇形矩阵剪切排序：将一维数组映射为 \sqrt{N} \times \sqrt{N} 矩阵，奇数行升序、偶数行降序（蛇形），再对每一列纵向升序，重复 \lceil \log_2 N \rceil + 1 轮后整体自然有序。 142. Column Sort (Leighton) | 矩阵列排序：8 步法矩阵转置、重塑与列内排序算法。 143. Weave Sorting Network | 交织比较器网络排序：结合完美洗牌置换（Perfect Shuffle）与相邻比较器的网络排序。 144. Diamond / Pratt Network Sort | 菱形网格比较器排序：按对角线波前推进的确定性比较网络。
类别 10：cat10_pancake_rotation.py — 煎饼翻转与受限操作排序 (6 种)
1. Pancake Sort (Classic Max-Flip) | 经典煎饼排序：每次仅允许使用前缀翻转操作 FLIP(0, k)，先将未排序区最大值翻到最顶端 arr[0]，再一铲子翻到当前未排序区最底端。
2. Burnt Pancake Sort | 烧焦煎饼排序：每个元素带有正反面状态（朝向标记），必须通过额外一次顶层单翻转确保排好序时所有煎饼“焦面朝下”。
3. Insertion Pancake Sort (Binary Flip) | 二分翻转煎饼插入排序：利用二分查找在有序前缀中找到插入点，通过三次前缀翻转将新元素精确嵌入，无需寻找最大值。
4. Quasi-Pancake Sort (Subarray Reversal) | 准煎饼区间翻转排序：利用任意子区间对称翻转操作实现的归位排序。
5. Adjacent Block Transpose Sort | 相邻块互换排序：仅通过交换相邻等长或不等长子块完成的排序。
6. Two-Stack Simulation Sort | 双栈倒腾模拟排序：利用辅助数组模拟输入栈与有序栈，像汉诺塔一样来回弹出压入完成排序。
类别 11：cat11_esoteric_educational.py — 教学、幽默与极限慢速排序 (10 种)
1. Slow Sort (Multiply and Surrender) | 慢速排序：Broder & Stolfi 提出的“乘积与投降”幽默分治算法——递归排左半、递归排右半，把两个半区的最大值放到最末尾后，再递归排除了最后一个元素之外的整个数组。
2. Stooge Sort | 臭皮匠排序：若首尾逆序则交换，随后递归排前 2/3、再递归排后 2/3、最后再递归排一遍前 2/3，时间复杂度 O(N^{\log_{1.5} 3}) \approx O(N^{2.7095})。
3. Silly Sort | 傻瓜递归分治冒泡排序：极其低效的多重重叠分治交换教学演示。
4. Spaghetti Sort (Mechanical Scan Simulation) | 意大利面扫描模拟排序：模拟将一把长短不一的意大利面立在桌面上，手掌从最高处水平向下平移，依次触碰并抽走最长的面条写回有序区。
5. Sleep Sort (Discrete Event Simulation) | 睡眠排序（离散事件队列安全模拟版）：无需真实创建系统线程休眠卡死，而是根据每个元素数值大小注册离散时钟滴答（Tick），按时钟推进依次唤醒收集元素。
6. Bogo Sort (Monkey Shuffle) | 猴子随机洗牌排序：每次检查是否有序，若无序则使用 Fisher-Yates 洗牌打乱整个数组（内置安全步数熔断提示，适合 N \le 8 演示）。
7. Bozo Sort (Random Pair Swap) | 蠢蛋随机对换排序：每次随机抽取两个下标交换，直到数组恰好有序。
8. Less Bogo Sort (Progressive Prefix Lock) | 渐进锁定猴子排序：一旦随机洗牌使得前 k 个元素恰好是全局最小的 k 个有序元素，则锁定前 k 个位置，仅对剩余后缀继续随机洗牌。
9. Cocktail Bogo Sort | 双向锁定猴子排序：同时锁定首尾两端碰巧排对的极值，缩小洗牌区间。
10. Stalin Sort + Gulag Re-merge (Humorous Educational) | 斯大林检阅重归并排序：第一遍线性扫描，凡是小于前一个元素的“不合群元素”直接移入辅助区（流放区），保留主数组严格递增；随后对辅助区递归排序并归并回主数组，保证最终数据不丢失且完整有序。
4. 多语言自定义算法扩展系统 (Polyglot Custom Algorithm Engine)
为了支持用户使用任意编程语言（C, C++, Python, Java, Rust, Go, JavaScript (Node.js), C#）添加自己的排序算法并享受同等的可视化与视频导出效果：
4.1 跨语言标准通信协议 (IPC via stdin / stdout)
1. 主程序通过 subprocess.Popen 启动用户配置的可执行程序或脚本解释器。
2. 主程序向子进程 stdin 输入两行数据：
   * 第 1 行：整数 N（当前用户设定的数组长度）
   * 第 2 行：N 个空格分隔的初始数组整数
3. 用户程序执行排序逻辑，并在发生比较、交换、赋值时向 stdout 打印符合 2.1 规范的指令行（如 CMP 0 1、SWAP 0 1、SET 2 45、MSG 正在执行自定义分区）。
4. 主程序实时解析 stdout 指令流，驱动画布高亮、计数器刷新与音效播放。
4.2 内置一键生成 7 种语言 SDK 模板 (sdk_templates/)
界面提供 “新建/导出多语言算法模板” 按钮，自动生成封装好 VisualArray 类的单文件代码模板（含 template.cpp, template.c, template.py, Template.java, template.rs, template.go, template.js）。
例如在 C++ 模板中，已预置好：
struct VisualArray {
   std::vector<int> data;
   int size() const { return data.size(); }
   bool cmp(int i, int j) {
       std::cout << "CMP " << i << " " << j << "\n";
       return data[i] < data[j];
   }
   void swap(int i, int j) {
       std::cout << "SWAP " << i << " " << j << "\n";
       std::swap(data[i], data[j]);
   }
   int get(int i) const { return data[i]; }
   void set(int i, int val) {
       std::cout << "SET " << i << " " << val << "\n";
       data[i] = val;
   }
};
// 用户只需在此函数内像写普通代码一样编写排序算法：
void my_custom_sort(VisualArray& arr, int n) {
   // User code here
}

软件内置自动编译检测器（自动调用系统中的 g++, clang++, rustc, javac, go, node, python），支持用户在软件内一键点击 “编译并运行可视化”。
5. 可视化视觉规范、实时状态看板与用户控制 (Visuals, HUD & Controls)
5.1 视觉色彩编码系统（高对比度极客深色风）
* 背景色：深空黑 #0D0E12（网格辅助线 #1A1D24）。
* 未排序常规元素：支持一键切换 纯白极简 (#ECEFF4)、渐变科技蓝 (#00B4D8 -> #0077B6) 或 HSV 全光谱彩虹色相模式 (0° -> 300°)。
* 正在比较的元素 (CMP)：亮柠檬黄 #FFEA00（并在底部绘制向上指示三角标）。
* 正在交换或覆写的元素 (SWAP / SET)：珊瑚高亮红 #FF2A55。
* 基准值与边界指针 (PIVOT / BOUNDARY)：霓虹紫 #B537F2 / 青色 #00F5D4。
* 辅助数组 (AUX)：当算法启用辅助空间时，画布自动平滑分割为上下双视图（上方 65% 主数组，下方 35% 辅助数组），清晰展示归并、计数、基数分桶的数据流动。
* 排序完成校验扫光 (SORTED)：排序结束后，自动触发从左至右的翠绿色 #00E676 扫光校验动画与和弦爬升音效。
5.2 5 种实时可切换可视化几何样式
1. 经典垂直柱状图 (Vertical Bars)：自适应间隙与宽度。
2. 极坐标彩虹圆环 (Color Wheel / Disparity Circle)：角度对应当前索引，半径或颜色对应数值及与正确位置的距离偏差。
3. 散点星云图 (Scatter Plot)：横坐标为索引，纵坐标为数值（乱序呈星云状，排好序收敛为对角线）。
4. 阿基米德螺旋图 (Archimedean Spiral)：极坐标螺旋线展示元素收敛过程。
5. 二维色块矩阵图 (2D Carpet / Matrix)：专为 Shear Sort、Column Sort 与基数排序设计的矩阵色块视图。
5.3 实时状态数据看板 (Real-time HUD Overlay)
画布左上角采用半透明毛玻璃浮层 + 等宽字体 (Consolas / JetBrains Mono) 实时刷新：
* 算法档案：序号与名称（中英双语）、所属分类、时间复杂度（最好/平均/最坏）、空间复杂度、稳定性（Stable 绿标 / Unstable 橙标）。
* 数据规模：当前数据量 N（支持用户自由拖动或输入 8 ~ 10,000）、初始数据分布形态。
* 核心计数器：
   * Comparisons（比较次数）
   * Swaps（交换次数）
   * Main Writes（主数组写入次数）& Aux Writes（辅助数组写入次数）
   * Total Array Accesses（数组总访问次数）
* 实时状态与进度：当前执行步数 / 总步数进度百分比、模拟耗时、当前阶段动态解说词 (MSG)。
5.4 8 种初始数据分布与同屏赛马模式
1. 8 种初始数据分布：完全随机 (Random)、完全逆序 (Reversed)、近乎有序 (Nearly Sorted)、大量重复值 (Few Unique: 4/8/16 种值)、正弦波 (Sine Wave)、锯齿波 (Sawtooth)、山峰管风琴 (Organ Pipe)、局部乱序块 (Scrambled Segments)。
2. 播放与单步调试：支持播放、暂停、重置、单步前进 (Step +1)、单步后退 (Step -1)、倍速无级调节（0.1x ~ 2000x）及进度条任意拖拽跳转。
3. 同屏赛马对比模式 (2-Grid / 4-Grid Race Mode)：允许用户在界面开启双屏或四宫格模式，从 160 个内置算法或自定义脚本中任选 2~4 个，在同一初始数组和相同时钟频率下同台竞技，直观对比谁先排完、谁的比较和交换次数更少。
6. 离线 1080P@60FPS 视频导出与 .exe 打包方案
6.1 离线高清视频导出器 (exporter/video_exporter.py)
* 用户可设定导出参数：分辨率（1920x1080 或 3840x2160）、帧率（60 FPS）、目标视频总时长（如自动将整个排序过程平滑浓缩为 15秒、30秒 或 60秒，结尾附带 1.5 秒绿色扫光定格）。
* 离屏渲染管道：在后台线程中利用 QImage 逐帧绘制高清画面（包含 HUD 看板、主副数组、底部进度条），同时在内存中精确合成对应帧的立体声 WAV 音频采样，通过管道交给 FFmpeg 合成为 H.264 MP4 视频文件，保证在任何配置的电脑上导出的视频都丝滑无掉帧。
6.2 独立 .exe 一键打包 (build_exe.py)
提供完整的 PyInstaller 自动化打包脚本，将程序代码、160 个算法模块、多语言 SDK 模板目录以及本地 ffmpeg.exe 打包为免安装独立运行的 Windows 可执行程序。
7. 项目目录结构与分批生成指令 (Project Structure & Batch Delivery Plan)
SortingVisualizerUltimate/
├── main.py                           # 程序启动入口
├── core/
│   ├── protocol.py                   # VisualArray 包装器、原子指令流与回溯状态机
│   ├── registry.py                   # @register_algo 装饰器与 160 算法索引中心
│   ├── data_generator.py             # 8 种初始数据分布生成器
│   ├── polyglot_runner.py            # 外部多语言自动编译与子进程通信引擎
│   └── audio_synth.py                # 实时合成器音效与离线 WAV 音轨生成器
├── algorithms/                       # 内置 160 种排序算法库（按 11 个分类模块组织）
│   ├── __init__.py                   # 自动扫描加载全部 11 个分类模块
│   ├── cat01_exchange.py             # #001 - #018 交换类排序 (18种)
│   ├── cat02_selection_cycle.py      # #019 - #030 选择、锦标赛与圈排序 (12种)
│   ├── cat03_heaps_trees.py          # #031 - #048 堆与平衡树排序家族 (18种)
│   ├── cat04_insertion_shell.py      # #049 - #068 插入与希尔全序列家族 (20种)
│   ├── cat05_quicksorts.py           # #069 - #084 快速排序全家族 (16种)
│   ├── cat06_mergesorts.py           # #085 - #098 归并排序全家族 (14种)
│   ├── cat07_hybrids_blocks.py       # #099 - #114 现代工业级与原地块归并 (16种)
│   ├── cat08_distribution_radix.py   # #115 - #132 计数、桶、基数、闪电与重力珠子 (18种)
│   ├── cat09_sorting_networks.py     # #133 - #144 双调、奇偶、成对与矩阵剪切网络 (12种)
│   ├── cat10_pancake_rotation.py     # #145 - #150 煎饼翻转与受限栈排序 (6种)
│   └── cat11_esoteric_educational.py # #151 - #160 慢速、臭皮匠、意大利面、猴子等 (10种)
├── sdk_templates/                    # C, C++, Python, Java, Rust, Go, JS 用户算法模板
├── ui/
│   ├── main_window.py                # 主窗口、160算法搜索树、参数控制栏、四宫格赛马模式
│   ├── canvas_widget.py              # NumPy 向量化加速渲染画布 (支持主/副数组分屏与5种样式)
│   └── custom_algo_dialog.py         # 多语言代码编辑器、SDK 导出与一键编译运行弹窗
├── exporter/
│   └── video_exporter.py             # FFmpeg 1080P@60FPS 音画同步离线视频导出器
├── requirements.txt
└── build_exe.py                      # PyInstaller 一键生成 EXE 脚本

⚠️ 给 AI 的强制分批交付指令（防止输出截断，严禁省略任何算法）：
由于本项目包含实打实的 160 种排序算法 与完整的桌面级渲染/导出引擎，单次对话绝对无法容纳全部源码。请严格按照以下 6 个批次（Batches） 逐步输出完整、无省略、可直接运行的代码（每完成一个 Batch 后停下，等待我发送“继续下一批”）：
* Batch 1（核心底层引擎 + 类别 01 ~ 03 共 48 种算法）：输出 core/protocol.py, core/registry.py, core/data_generator.py，以及 cat01_exchange.py (18种)、cat02_selection_cycle.py (12种)、cat03_heaps_trees.py (18种) 的完整实现。
* Batch 2（类别 04 ~ 06 共 50 种算法）：输出 cat04_insertion_shell.py (20种)、cat05_quicksorts.py (16种)、cat06_mergesorts.py (14种) 的完整实现。
* Batch 3（类别 07 ~ 11 共 62 种算法，凑齐 160 种全集）：输出 cat07_hybrids_blocks.py (16种)、cat08_distribution_radix.py (18种)、cat09_sorting_networks.py (12种)、cat10_pancake_rotation.py (6种)、cat11_esoteric_educational.py (10种) 及 algorithms/__init__.py。
* Batch 4（高性能向量化 GUI、5种视觉画布、四宫格赛马与实时音效）：输出 core/audio_synth.py, ui/canvas_widget.py, ui/main_window.py, main.py。
* Batch 5（多语言自定义算法沙盒与 7 语言 SDK 模板）：输出 core/polyglot_runner.py, ui/custom_algo_dialog.py 以及 C/C++/Python/Java/Rust/Go/JS 模板生成逻辑。
* Batch 6（FFmpeg 离线视频导出器与 EXE 自动化打包）：输出 exporter/video_exporter.py, requirements.txt, build_exe.py。
现在，请确认已读取全部 160 种算法清单，并直接开始输出 Batch 1 的全部完整代码。