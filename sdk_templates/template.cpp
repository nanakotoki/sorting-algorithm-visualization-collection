// Sorting Visualizer Ultimate —— C++ 自定义算法模板（单文件）
//
// 手工编译验证：
//     g++ -O2 -std=c++17 -o my_algo template.cpp
//     echo "8
//     5 3 9 1 7 2 8 4" | ./my_algo
//
// 协议（每行一条指令写入 stdout）：
//     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
//     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
//     MARK i ROLE | CLEAR_MARKS | MSG text...
//
// 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。

#include <algorithm>
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

// =========================================================================
// 1. 统一数组包装器（无需修改）
// =========================================================================
struct VisualArray {
    std::vector<int> data;
    std::vector<int> aux;
    bool aux_ready = false;

    int size() const { return static_cast<int>(data.size()); }

    // ---- 内部 ----------------------------------------------------------
    void check(int i) const {
        if (i < 0 || i >= size())
            throw std::out_of_range("索引越界: " + std::to_string(i) +
                                    "（数组长度 " + std::to_string(size()) + "）");
    }

    // ---- 读取 ----------------------------------------------------------
    int peek(int i) const { check(i); return data[i]; }

    int get(int i) {                                  // READ：计 1 次访问
        check(i);
        std::cout << "READ " << i << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return data[i];
    }

    // ---- 比较 ----------------------------------------------------------
    bool cmp(int i, int j) {                          // arr[i] < arr[j]
        check(i); check(j);
        std::cout << "CMP " << i << " " << j << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return data[i] < data[j];
    }

    bool gt(int i, int j) {                           // arr[i] > arr[j]（严格）
        check(i); check(j);
        std::cout << "CMP " << j << " " << i << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return data[i] > data[j];
    }

    bool cmp_val(int i, int val) {                    // arr[i] < val
        check(i);
        std::cout << "CMP_VAL " << i << " " << val << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return data[i] < val;
    }

    bool gt_val(int i, int val) {                     // arr[i] > val
        check(i);
        std::cout << "CMP_VAL " << i << " " << val << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return data[i] > val;
    }

    // ---- 写入 ----------------------------------------------------------
    void swap(int i, int j) {
        check(i); check(j);
        if (i == j) return;
        std::cout << "SWAP " << i << " " << j << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        std::swap(data[i], data[j]);
    }

    void set(int i, int val) {
        check(i);
        std::cout << "SET " << i << " " << val << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        data[i] = val;
    }

    void flip(int left, int right) {                  // 原地翻转 [left, right]
        check(left); check(right);
        if (left >= right) return;
        std::cout << "FLIP " << left << " " << right << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        std::reverse(data.begin() + left, data.begin() + right + 1);
    }

    // ---- 辅助数组 ------------------------------------------------------
    void aux_init(int n) {
        std::cout << "AUX_INIT " << n << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        aux.assign(n < 0 ? 0 : n, 0);
        aux_ready = true;
    }
    void aux_set(int i, int val) {
        std::cout << "AUX_SET " << i << " " << val << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        aux[i] = val;
    }
    int aux_get(int i) {
        std::cout << "AUX_GET " << i << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return aux[i];
    }
    void aux_swap(int i, int j) {
        if (i == j) return;
        std::cout << "AUX_SWAP " << i << " " << j << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        std::swap(aux[i], aux[j]);
    }
    bool aux_cmp(int i, int j) {
        std::cout << "AUX_CMP " << i << " " << j << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return aux[i] < aux[j];
    }
    void aux_clear() {
        std::cout << "AUX_CLEAR\n";
        aux.clear();
        aux_ready = false;
    }

    // ---- 标记与解说 ----------------------------------------------------
    void mark(int i, const std::string &role) {
        check(i);
        std::cout << "MARK " << i << " " << role << std::endl;   // endl 逐行刷新，主程序才能实时渲染
    }
    void clear_marks() { std::cout << "CLEAR_MARKS\n"; }
    void msg(const std::string &text) { std::cout << "MSG " << text << std::endl;   // endl 逐行刷新，主程序才能实时渲染 }

    bool is_sorted() const {
        for (int i = 1; i < size(); ++i)
            if (data[i - 1] > data[i]) return false;
        return true;
    }
};

// =========================================================================
// 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
// =========================================================================
void my_custom_sort(VisualArray &arr, int n) {
    for (int i = 1; i < n; ++i) {
        int j = i;
        arr.mark(j, "CURSOR");
        while (j > 0 && arr.gt(j - 1, j)) {           // arr[j-1] > arr[j] 才交换
            arr.swap(j - 1, j);
            --j;
        }
        arr.mark(j, "SORTED");
    }
    arr.clear_marks();
}

// =========================================================================
// 3. 输入输出（无需修改）
// =========================================================================
static bool read_input(int &n, std::vector<int> &values) {
    if (!(std::cin >> n)) return false;
    if (n < 0) n = 0;
    values.resize(n);
    for (int i = 0; i < n; ++i)
        if (!(std::cin >> values[i])) return false;
    return true;
}

int main() {
    // 关掉 iostream 与 C stdio 的同步以提速，同时保留 std::endl 的逐行刷新；
    // 若你的算法规模极大（百万步以上），可把 endl 换成 '\n' 并在最后手动
    // std::cout.flush()——代价是画面会攒够一整块缓冲才刷新一次。
    std::ios::sync_with_stdio(false);

    int n = 0;
    std::vector<int> values;
    if (!read_input(n, values)) {
        std::cerr << "输入解析失败\n";
        return 2;
    }

    VisualArray arr;
    arr.data = values;
    try {
        my_custom_sort(arr, n);
    } catch (const std::exception &e) {
        arr.msg(std::string("自定义算法异常：") + e.what());
        std::cerr << e.what() << std::endl;   // endl 逐行刷新，主程序才能实时渲染
        return 1;
    }

    if (arr.is_sorted())
        arr.msg("自定义算法完成：数组已有序 ✓");
    else {
        arr.msg("自定义算法结束：数组尚未有序 ✗");
        std::cerr << "警告：算法返回时数组并未有序\n";
    }
    std::cout.flush();
    return 0;
}
