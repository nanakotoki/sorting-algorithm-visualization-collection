/* Sorting Visualizer Ultimate —— C 自定义算法模板（单文件，C11）
 *
 * 手工编译验证：
 *     gcc -O2 -std=c11 -o my_algo template.c
 *     printf '8\n5 3 9 1 7 2 8 4\n' | ./my_algo
 *
 * 协议（每行一条指令写入 stdout）：
 *     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
 *     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
 *     MARK i ROLE | CLEAR_MARKS | MSG text...
 *
 * 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* =========================================================================
 * 1. 统一数组包装器（无需修改）
 * ========================================================================= */
typedef struct {
    int *data;
    int  n;

    int *aux;
    int  aux_n;
    int  aux_ready;
} VisualArray;

/* ---- 内部工具 ---------------------------------------------------------- */
static void va_fail(const char *what, int i, int n) {
    fprintf(stderr, "索引越界: %s=%d（数组长度 %d）\n", what, i, n);
    exit(1);
}

static int va_check(const VisualArray *a, int i) {
    if (i < 0 || i >= a->n) va_fail("i", i, a->n);
    return i;
}

/* ---- 初始化 ------------------------------------------------------------ */
static void va_init(VisualArray *a, int *values, int n) {
    a->data = values;
    a->n = n;
    a->aux = NULL;
    a->aux_n = 0;
    a->aux_ready = 0;
}

/* ---- 读取 -------------------------------------------------------------- */
static int va_peek(const VisualArray *a, int i) { return a->data[va_check(a, i)]; }

static int va_get(VisualArray *a, int i) {          /* READ：计 1 次访问 */
    va_check(a, i);
    printf("READ %d\n", i);
    return a->data[i];
}

/* ---- 比较 -------------------------------------------------------------- */
static int va_cmp(VisualArray *a, int i, int j) {   /* arr[i] < arr[j] */
    va_check(a, i); va_check(a, j);
    printf("CMP %d %d\n", i, j);
    return a->data[i] < a->data[j];
}

static int va_gt(VisualArray *a, int i, int j) {    /* arr[i] > arr[j]（严格） */
    va_check(a, i); va_check(a, j);
    printf("CMP %d %d\n", j, i);
    return a->data[i] > a->data[j];
}

static int va_cmp_val(VisualArray *a, int i, int val) {   /* arr[i] < val */
    va_check(a, i);
    printf("CMP_VAL %d %d\n", i, val);
    return a->data[i] < val;
}

static int va_gt_val(VisualArray *a, int i, int val) {    /* arr[i] > val */
    va_check(a, i);
    printf("CMP_VAL %d %d\n", i, val);
    return a->data[i] > val;
}

/* ---- 写入 -------------------------------------------------------------- */
static void va_swap(VisualArray *a, int i, int j) {
    int t;
    va_check(a, i); va_check(a, j);
    if (i == j) return;
    printf("SWAP %d %d\n", i, j);
    t = a->data[i]; a->data[i] = a->data[j]; a->data[j] = t;
}

static void va_set(VisualArray *a, int i, int val) {
    va_check(a, i);
    printf("SET %d %d\n", i, val);
    a->data[i] = val;
}

static void va_flip(VisualArray *a, int left, int right) {   /* 原地翻转 [left, right] */
    va_check(a, left); va_check(a, right);
    if (left >= right) return;
    printf("FLIP %d %d\n", left, right);
    while (left < right) {
        int t = a->data[left];
        a->data[left] = a->data[right];
        a->data[right] = t;
        ++left; --right;
    }
}

/* ---- 辅助数组 ---------------------------------------------------------- */
static void va_aux_init(VisualArray *a, int size) {
    if (size < 0) size = 0;
    printf("AUX_INIT %d\n", size);
    free(a->aux);
    a->aux = (int *)calloc((size_t)size, sizeof(int));
    a->aux_n = size;
    a->aux_ready = 1;
}

static void va_aux_set(VisualArray *a, int i, int val) {
    if (!a->aux_ready || i < 0 || i >= a->aux_n) va_fail("aux i", i, a->aux_n);
    printf("AUX_SET %d %d\n", i, val);
    a->aux[i] = val;
}

static int va_aux_get(VisualArray *a, int i) {
    if (!a->aux_ready || i < 0 || i >= a->aux_n) va_fail("aux i", i, a->aux_n);
    printf("AUX_GET %d\n", i);
    return a->aux[i];
}

static void va_aux_swap(VisualArray *a, int i, int j) {
    int t;
    if (!a->aux_ready) return;
    if (i == j) return;
    printf("AUX_SWAP %d %d\n", i, j);
    t = a->aux[i]; a->aux[i] = a->aux[j]; a->aux[j] = t;
}

static int va_aux_cmp(VisualArray *a, int i, int j) {
    if (!a->aux_ready) return 0;
    printf("AUX_CMP %d %d\n", i, j);
    return a->aux[i] < a->aux[j];
}

static void va_aux_clear(VisualArray *a) {
    printf("AUX_CLEAR\n");
    free(a->aux);
    a->aux = NULL;
    a->aux_n = 0;
    a->aux_ready = 0;
}

/* ---- 标记与解说 -------------------------------------------------------- */
static void va_mark(VisualArray *a, int i, const char *role) {
    va_check(a, i);
    printf("MARK %d %s\n", i, role);
}

static void va_clear_marks(VisualArray *a) { (void)a; printf("CLEAR_MARKS\n"); }

static void va_msg(VisualArray *a, const char *text) { (void)a; printf("MSG %s\n", text); }

static int va_is_sorted(const VisualArray *a) {
    int i;
    for (i = 1; i < a->n; ++i)
        if (a->data[i - 1] > a->data[i]) return 0;
    return 1;
}

/* =========================================================================
 * 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
 * ========================================================================= */
static void my_custom_sort(VisualArray *arr, int n) {
    int i, j;
    for (i = 1; i < n; ++i) {
        j = i;
        va_mark(arr, j, "CURSOR");
        while (j > 0 && va_gt(arr, j - 1, j)) {      /* arr[j-1] > arr[j] 才交换 */
            va_swap(arr, j - 1, j);
            --j;
        }
        va_mark(arr, j, "SORTED");
    }
    va_clear_marks(arr);
}

/* =========================================================================
 * 3. 输入输出（无需修改）
 * ========================================================================= */
static int read_input(int *n_out, int **values_out) {
    int n = 0, i;
    int *values;
    if (scanf("%d", &n) != 1) return 0;
    if (n < 0) n = 0;
    values = (int *)malloc(sizeof(int) * (size_t)(n > 0 ? n : 1));
    if (!values) return 0;
    for (i = 0; i < n; ++i) {
        if (scanf("%d", &values[i]) != 1) { free(values); return 0; }
    }
    *n_out = n;
    *values_out = values;
    return 1;
}

int main(void) {
    int n = 0, *values = NULL, ok;
    VisualArray arr;

    /* 关闭 stdout 缓冲：保证主程序能逐条实时收到指令 */
    setvbuf(stdout, NULL, _IONBF, 0);

    if (!read_input(&n, &values)) {
        fprintf(stderr, "输入解析失败\n");
        return 2;
    }

    va_init(&arr, values, n);
    my_custom_sort(&arr, n);

    if (va_is_sorted(&arr)) {
        va_msg(&arr, "自定义算法完成：数组已有序 ✓");
        ok = 0;
    } else {
        va_msg(&arr, "自定义算法结束：数组尚未有序 ✗");
        fprintf(stderr, "警告：算法返回时数组并未有序\n");
        ok = 0;
    }

    fflush(stdout);
    free(values);
    if (arr.aux) free(arr.aux);
    return ok;
}
