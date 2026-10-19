/* Sorting Visualizer Ultimate —— Java 自定义算法模板（单文件）
 *
 * 注意：Java 要求 public 类名与文件名一致，因此本文件请保持名为 Template.java；
 *       若你改了类名，主程序会自动识别并把源码复制成「类名.java」再编译。
 *
 * 手工编译验证：
 *     javac -d out Template.java
 *     printf '8\n5 3 9 1 7 2 8 4\n' | java -cp out Template
 *
 * 协议（每行一条指令写入 stdout）：
 *     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
 *     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
 *     MARK i ROLE | CLEAR_MARKS | MSG text...
 *
 * 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。
 */

import java.io.PrintStream;
import java.util.Scanner;

public class Template {

    /* =====================================================================
     * 1. 统一数组包装器（无需修改）
     * ===================================================================== */
    static final class VisualArray {
        final int[] data;
        final int n;
        int[] aux;
        boolean auxReady = false;

        VisualArray(int[] values) {
            this.data = values.clone();
            this.n = this.data.length;
            this.aux = new int[0];
        }

        // ---- 内部 --------------------------------------------------------
        private int check(int i) {
            if (i < 0 || i >= n) {
                throw new IndexOutOfBoundsException(
                        "索引越界: " + i + "（数组长度 " + n + "）");
            }
            return i;
        }

        private static void emit(String s) {
            System.out.println(s);
            System.out.flush();          // 逐行刷新：主程序才能实时渲染
        }

        int size() { return n; }

        // ---- 读取 --------------------------------------------------------
        int peek(int i) { return data[check(i)]; }

        int get(int i) {                 // READ：计 1 次访问
            check(i);
            emit("READ " + i);
            return data[i];
        }

        // ---- 比较 --------------------------------------------------------
        boolean cmp(int i, int j) {       // arr[i] < arr[j]
            check(i); check(j);
            emit("CMP " + i + " " + j);
            return data[i] < data[j];
        }

        boolean gt(int i, int j) {        // arr[i] > arr[j]（严格）
            check(i); check(j);
            emit("CMP " + j + " " + i);
            return data[i] > data[j];
        }

        boolean cmpVal(int i, int val) {  // arr[i] < val
            check(i);
            emit("CMP_VAL " + i + " " + val);
            return data[i] < val;
        }

        boolean gtVal(int i, int val) {   // arr[i] > val
            check(i);
            emit("CMP_VAL " + i + " " + val);
            return data[i] > val;
        }

        // ---- 写入 --------------------------------------------------------
        void swap(int i, int j) {
            check(i); check(j);
            if (i == j) return;
            emit("SWAP " + i + " " + j);
            int t = data[i]; data[i] = data[j]; data[j] = t;
        }

        void set(int i, int val) {
            check(i);
            emit("SET " + i + " " + val);
            data[i] = val;
        }

        void flip(int left, int right) {  // 原地翻转 [left, right]
            check(left); check(right);
            if (left >= right) return;
            emit("FLIP " + left + " " + right);
            while (left < right) {
                int t = data[left]; data[left] = data[right]; data[right] = t;
                left++; right--;
            }
        }

        // ---- 辅助数组 ----------------------------------------------------
        void auxInit(int size) {
            int m = Math.max(0, size);
            emit("AUX_INIT " + m);
            aux = new int[m];
            auxReady = true;
        }

        void auxSet(int i, int val) {
            emit("AUX_SET " + i + " " + val);
            aux[i] = val;
        }

        int auxGet(int i) {
            emit("AUX_GET " + i);
            return aux[i];
        }

        void auxSwap(int i, int j) {
            if (i == j) return;
            emit("AUX_SWAP " + i + " " + j);
            int t = aux[i]; aux[i] = aux[j]; aux[j] = t;
        }

        boolean auxCmp(int i, int j) {
            emit("AUX_CMP " + i + " " + j);
            return aux[i] < aux[j];
        }

        void auxClear() {
            emit("AUX_CLEAR");
            aux = new int[0];
            auxReady = false;
        }

        // ---- 标记与解说 --------------------------------------------------
        void mark(int i, String role) {
            check(i);
            emit("MARK " + i + " " + role);
        }

        void clearMarks() { emit("CLEAR_MARKS"); }

        void msg(String text) { emit("MSG " + text); }

        boolean isSorted() {
            for (int i = 1; i < n; i++) {
                if (data[i - 1] > data[i]) return false;
            }
            return true;
        }
    }

    /* =====================================================================
     * 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
     * ===================================================================== */
    static void myCustomSort(VisualArray arr, int n) {
        for (int i = 1; i < n; i++) {
            int j = i;
            arr.mark(j, "CURSOR");
            while (j > 0 && arr.gt(j - 1, j)) {   // arr[j-1] > arr[j] 才交换
                arr.swap(j - 1, j);
                j--;
            }
            arr.mark(j, "SORTED");
        }
        arr.clearMarks();
    }

    /* =====================================================================
     * 3. 输入输出（无需修改）
     * ===================================================================== */
    public static void main(String[] args) {
        // Windows 上 JVM 默认按控制台代码页（GBK）编码 System.out，中文 MSG 会变成
        // 乱码、且「✓」这类字符直接输出成 '?'。这里强制把标准流换成 UTF-8。
        try {
            PrintStream utf8 = new PrintStream(
                    new java.io.FileOutputStream(java.io.FileDescriptor.out),
                    true, "UTF-8");
            System.setOut(utf8);
            System.setErr(new PrintStream(
                    new java.io.FileOutputStream(java.io.FileDescriptor.err),
                    true, "UTF-8"));
        } catch (Exception ignore) {
            // 换不了就退回默认流，不影响功能
        }

        PrintStream err = System.err;
        Scanner sc = new Scanner(System.in);
        if (!sc.hasNextInt()) {
            err.println("输入解析失败：缺少 N");
            System.exit(2);
            return;
        }
        int n = sc.nextInt();
        if (n < 0) n = 0;
        int[] values = new int[n];
        for (int i = 0; i < n; i++) {
            if (!sc.hasNextInt()) {
                err.println("输入解析失败：数组元素不足 " + n + " 个");
                System.exit(2);
                return;
            }
            values[i] = sc.nextInt();
        }

        VisualArray arr = new VisualArray(values);
        try {
            myCustomSort(arr, n);
        } catch (RuntimeException e) {
            arr.msg("自定义算法异常：" + e.getClass().getSimpleName() + ": " + e.getMessage());
            err.println(e);
            System.exit(1);
            return;
        }

        if (arr.isSorted()) {
            arr.msg("自定义算法完成：数组已有序 ✓");
        } else {
            arr.msg("自定义算法结束：数组尚未有序 ✗");
            err.println("警告：算法返回时数组并未有序");
        }
        System.out.flush();
    }
}
