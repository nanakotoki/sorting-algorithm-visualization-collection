// Sorting Visualizer Ultimate —— Go 自定义算法模板（单文件）
//
// 手工编译验证：
//     go build -o my_algo.exe template.go
//     printf '8\n5 3 9 1 7 2 8 4\n' | ./my_algo.exe
//
// 协议（每行一条指令写入 stdout）：
//     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
//     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
//     MARK i ROLE | CLEAR_MARKS | MSG text...
//
// 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。

package main

import (
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
)

/* =========================================================================
 * 1. 统一数组包装器（无需修改）
 * ========================================================================= */
type VisualArray struct {
	data     []int
	aux      []int
	auxReady bool
}

func NewVisualArray(values []int) *VisualArray {
	return &VisualArray{data: values, aux: []int{}}
}

func (a *VisualArray) Size() int { return len(a.data) }

// ---- 内部 ----------------------------------------------------------------
func (a *VisualArray) check(i int) int {
	if i < 0 || i >= len(a.data) {
		panic(fmt.Sprintf("索引越界: %d（数组长度 %d）", i, len(a.data)))
	}
	return i
}

func (a *VisualArray) checkAux(i int) int {
	if !a.auxReady || i < 0 || i >= len(a.aux) {
		panic(fmt.Sprintf("辅助数组索引越界: %d（长度 %d）", i, len(a.aux)))
	}
	return i
}

// emit 写出一行指令。fmt 直接写 os.Stdout，无缓冲，天然逐行实时。
func emit(line string) { fmt.Println(line) }

// ---- 读取 ----------------------------------------------------------------
func (a *VisualArray) Peek(i int) int { return a.data[a.check(i)] }

func (a *VisualArray) Get(i int) int { // READ：计 1 次访问
	k := a.check(i)
	emit("READ " + strconv.Itoa(k))
	return a.data[k]
}

// ---- 比较 ----------------------------------------------------------------
func (a *VisualArray) Cmp(i, j int) bool { // arr[i] < arr[j]
	x, y := a.check(i), a.check(j)
	emit("CMP " + strconv.Itoa(x) + " " + strconv.Itoa(y))
	return a.data[x] < a.data[y]
}

func (a *VisualArray) Gt(i, j int) bool { // arr[i] > arr[j]（严格）
	x, y := a.check(i), a.check(j)
	emit("CMP " + strconv.Itoa(y) + " " + strconv.Itoa(x))
	return a.data[x] > a.data[y]
}

func (a *VisualArray) CmpVal(i, val int) bool { // arr[i] < val
	x := a.check(i)
	emit("CMP_VAL " + strconv.Itoa(x) + " " + strconv.Itoa(val))
	return a.data[x] < val
}

func (a *VisualArray) GtVal(i, val int) bool { // arr[i] > val
	x := a.check(i)
	emit("CMP_VAL " + strconv.Itoa(x) + " " + strconv.Itoa(val))
	return a.data[x] > val
}

// ---- 写入 ----------------------------------------------------------------
func (a *VisualArray) Swap(i, j int) {
	x, y := a.check(i), a.check(j)
	if x == y {
		return
	}
	emit("SWAP " + strconv.Itoa(x) + " " + strconv.Itoa(y))
	a.data[x], a.data[y] = a.data[y], a.data[x]
}

func (a *VisualArray) Set(i, val int) {
	x := a.check(i)
	emit("SET " + strconv.Itoa(x) + " " + strconv.Itoa(val))
	a.data[x] = val
}

func (a *VisualArray) Flip(left, right int) { // 原地翻转 [left, right]
	l, r := a.check(left), a.check(right)
	if l >= r {
		return
	}
	emit("FLIP " + strconv.Itoa(l) + " " + strconv.Itoa(r))
	for l < r {
		a.data[l], a.data[r] = a.data[r], a.data[l]
		l++
		r--
	}
}

// ---- 辅助数组 ------------------------------------------------------------
func (a *VisualArray) AuxInit(size int) {
	if size < 0 {
		size = 0
	}
	emit("AUX_INIT " + strconv.Itoa(size))
	a.aux = make([]int, size)
	a.auxReady = true
}

func (a *VisualArray) AuxSet(i, val int) {
	k := a.checkAux(i)
	emit("AUX_SET " + strconv.Itoa(k) + " " + strconv.Itoa(val))
	a.aux[k] = val
}

func (a *VisualArray) AuxGet(i int) int {
	k := a.checkAux(i)
	emit("AUX_GET " + strconv.Itoa(k))
	return a.aux[k]
}

func (a *VisualArray) AuxSwap(i, j int) {
	x, y := a.checkAux(i), a.checkAux(j)
	if x == y {
		return
	}
	emit("AUX_SWAP " + strconv.Itoa(x) + " " + strconv.Itoa(y))
	a.aux[x], a.aux[y] = a.aux[y], a.aux[x]
}

func (a *VisualArray) AuxCmp(i, j int) bool {
	x, y := a.checkAux(i), a.checkAux(j)
	emit("AUX_CMP " + strconv.Itoa(x) + " " + strconv.Itoa(y))
	return a.aux[x] < a.aux[y]
}

func (a *VisualArray) AuxClear() {
	emit("AUX_CLEAR")
	a.aux = []int{}
	a.auxReady = false
}

// ---- 标记与解说 ----------------------------------------------------------
func (a *VisualArray) Mark(i int, role string) {
	k := a.check(i)
	emit("MARK " + strconv.Itoa(k) + " " + role)
}

func (a *VisualArray) ClearMarks() { emit("CLEAR_MARKS") }

func (a *VisualArray) Msg(text string) { emit("MSG " + text) }

func (a *VisualArray) IsSorted() bool {
	for i := 1; i < len(a.data); i++ {
		if a.data[i-1] > a.data[i] {
			return false
		}
	}
	return true
}

/* =========================================================================
 * 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
 * ========================================================================= */
func myCustomSort(arr *VisualArray, n int) {
	for i := 1; i < n; i++ {
		j := i
		arr.Mark(j, "CURSOR")
		for j > 0 && arr.Gt(j-1, j) { // arr[j-1] > arr[j] 才交换
			arr.Swap(j-1, j)
			j--
		}
		arr.Mark(j, "SORTED")
	}
	arr.ClearMarks()
}

/* =========================================================================
 * 3. 输入输出（无需修改）
 * ========================================================================= */
func readInput() (int, []int, error) {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		return 0, nil, err
	}
	fields := strings.Fields(string(raw))
	if len(fields) == 0 {
		return 0, []int{}, nil
	}
	n, err := strconv.Atoi(fields[0])
	if err != nil {
		return 0, nil, fmt.Errorf("N 不是整数: %s", fields[0])
	}
	if n < 0 {
		n = 0
	}
	values := make([]int, 0, n)
	for k := 1; k <= n; k++ {
		if k >= len(fields) {
			return 0, nil, fmt.Errorf("数组元素不足 %d 个", n)
		}
		v, err := strconv.Atoi(fields[k])
		if err != nil {
			return 0, nil, fmt.Errorf("第 %d 个元素不是整数: %s", k, fields[k])
		}
		values = append(values, v)
	}
	return n, values, nil
}

func main() {
	n, values, err := readInput()
	if err != nil {
		fmt.Fprintln(os.Stderr, "输入解析失败:", err)
		os.Exit(2)
	}

	arr := NewVisualArray(values)
	myCustomSort(arr, n)

	if arr.IsSorted() {
		arr.Msg("自定义算法完成：数组已有序 ✓")
	} else {
		arr.Msg("自定义算法结束：数组尚未有序 ✗")
		fmt.Fprintln(os.Stderr, "警告：算法返回时数组并未有序")
	}
}
