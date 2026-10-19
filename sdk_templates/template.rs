// Sorting Visualizer Ultimate —— Rust 自定义算法模板（单文件，2021 Edition）
//
// 手工编译验证：
//     rustc -O -o my_algo template.rs
//     printf '8\n5 3 9 1 7 2 8 4\n' | ./my_algo
//
// 协议（每行一条指令写入 stdout）：
//     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
//     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
//     MARK i ROLE | CLEAR_MARKS | MSG text...
//
// 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。
// （Rust 侧方法一律 snake_case，Rust 的 stdout 在每个换行处自动刷新。）

use std::io::{self, Read, Write};

/* =========================================================================
 * 1. 统一数组包装器（无需修改）
 * ========================================================================= */
pub struct VisualArray {
    pub data: Vec<i64>,
    pub aux: Vec<i64>,
    pub aux_ready: bool,
}

impl VisualArray {
    pub fn new(values: Vec<i64>) -> Self {
        VisualArray { data: values, aux: Vec::new(), aux_ready: false }
    }

    pub fn len(&self) -> usize { self.data.len() }
    pub fn is_empty(&self) -> bool { self.data.is_empty() }

    // ---- 内部 ----------------------------------------------------------
    fn check(&self, i: i64) -> usize {
        if i < 0 || i as usize >= self.data.len() {
            panic!("索引越界: {}（数组长度 {}）", i, self.data.len());
        }
        i as usize
    }

    fn emit(line: &str) {
        // println! 内部是 LineWriter：遇到 '\n' 立即 flush，
        // 因此主程序可以逐条实时收到指令。
        println!("{}", line);
    }

    // ---- 读取 ----------------------------------------------------------
    pub fn peek(&self, i: i64) -> i64 { self.data[self.check(i)] }

    pub fn get(&mut self, i: i64) -> i64 {          // READ：计 1 次访问
        let k = self.check(i);
        Self::emit(&format!("READ {}", k));
        self.data[k]
    }

    // ---- 比较 ----------------------------------------------------------
    pub fn cmp(&mut self, i: i64, j: i64) -> bool { // arr[i] < arr[j]
        let a = self.check(i);
        let b = self.check(j);
        Self::emit(&format!("CMP {} {}", a, b));
        self.data[a] < self.data[b]
    }

    pub fn gt(&mut self, i: i64, j: i64) -> bool {  // arr[i] > arr[j]（严格）
        let a = self.check(i);
        let b = self.check(j);
        Self::emit(&format!("CMP {} {}", b, a));
        self.data[a] > self.data[b]
    }

    pub fn cmp_val(&mut self, i: i64, val: i64) -> bool {   // arr[i] < val
        let a = self.check(i);
        Self::emit(&format!("CMP_VAL {} {}", a, val));
        self.data[a] < val
    }

    pub fn gt_val(&mut self, i: i64, val: i64) -> bool {    // arr[i] > val
        let a = self.check(i);
        Self::emit(&format!("CMP_VAL {} {}", a, val));
        self.data[a] > val
    }

    // ---- 写入 ----------------------------------------------------------
    pub fn swap(&mut self, i: i64, j: i64) {
        let a = self.check(i);
        let b = self.check(j);
        if a == b { return; }
        Self::emit(&format!("SWAP {} {}", a, b));
        self.data.swap(a, b);
    }

    pub fn set(&mut self, i: i64, val: i64) {
        let a = self.check(i);
        Self::emit(&format!("SET {} {}", a, val));
        self.data[a] = val;
    }

    pub fn flip(&mut self, left: i64, right: i64) {  // 原地翻转 [left, right]
        let mut l = self.check(left);
        let mut r = self.check(right);
        if l >= r { return; }
        Self::emit(&format!("FLIP {} {}", l, r));
        while l < r {
            self.data.swap(l, r);
            l += 1;
            r -= 1;
        }
    }

    // ---- 辅助数组 ------------------------------------------------------
    pub fn aux_init(&mut self, size: i64) {
        let m = if size < 0 { 0 } else { size as usize };
        Self::emit(&format!("AUX_INIT {}", m));
        self.aux = vec![0; m];
        self.aux_ready = true;
    }

    pub fn aux_set(&mut self, i: i64, val: i64) {
        let k = self.check_aux(i);
        Self::emit(&format!("AUX_SET {} {}", k, val));
        self.aux[k] = val;
    }

    pub fn aux_get(&mut self, i: i64) -> i64 {
        let k = self.check_aux(i);
        Self::emit(&format!("AUX_GET {}", k));
        self.aux[k]
    }

    pub fn aux_swap(&mut self, i: i64, j: i64) {
        let a = self.check_aux(i);
        let b = self.check_aux(j);
        if a == b { return; }
        Self::emit(&format!("AUX_SWAP {} {}", a, b));
        self.aux.swap(a, b);
    }

    pub fn aux_cmp(&mut self, i: i64, j: i64) -> bool {
        let a = self.check_aux(i);
        let b = self.check_aux(j);
        Self::emit(&format!("AUX_CMP {} {}", a, b));
        self.aux[a] < self.aux[b]
    }

    pub fn aux_clear(&mut self) {
        Self::emit("AUX_CLEAR");
        self.aux.clear();
        self.aux_ready = false;
    }

    fn check_aux(&self, i: i64) -> usize {
        if !self.aux_ready || i < 0 || i as usize >= self.aux.len() {
            panic!("辅助数组索引越界: {}（长度 {}）", i, self.aux.len());
        }
        i as usize
    }

    // ---- 标记与解说 ----------------------------------------------------
    pub fn mark(&mut self, i: i64, role: &str) {
        let k = self.check(i);
        Self::emit(&format!("MARK {} {}", k, role));
    }

    pub fn clear_marks(&mut self) { Self::emit("CLEAR_MARKS"); }

    pub fn msg(&mut self, text: &str) { Self::emit(&format!("MSG {}", text)); }

    pub fn is_sorted(&self) -> bool {
        self.data.windows(2).all(|w| w[0] <= w[1])
    }
}

/* =========================================================================
 * 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
 * ========================================================================= */
pub fn my_custom_sort(arr: &mut VisualArray, n: usize) {
    for i in 1..n {
        let mut j = i as i64;
        arr.mark(j, "CURSOR");
        while j > 0 && arr.gt(j - 1, j) {       // arr[j-1] > arr[j] 才交换
            arr.swap(j - 1, j);
            j -= 1;
        }
        arr.mark(j, "SORTED");
    }
    arr.clear_marks();
}

/* =========================================================================
 * 3. 输入输出（无需修改）
 * ========================================================================= */
fn read_input() -> Result<(usize, Vec<i64>), String> {
    let mut buf = String::new();
    io::stdin().read_to_string(&mut buf).map_err(|e| e.to_string())?;
    let mut it = buf.split_whitespace();
    let n: usize = match it.next() {
        Some(t) => t.parse().map_err(|_| format!("N 不是整数: {}", t))?,
        None => return Ok((0, Vec::new())),
    };
    let mut values = Vec::with_capacity(n);
    for k in 0..n {
        match it.next() {
            Some(t) => values.push(t.parse().map_err(|_| format!("第 {} 个元素不是整数", k))?),
            None => return Err(format!("数组元素不足 {} 个", n)),
        }
    }
    Ok((n, values))
}

fn main() {
    let (n, values) = match read_input() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("输入解析失败: {}", e);
            std::process::exit(2);
        }
    };

    let mut arr = VisualArray::new(values);
    my_custom_sort(&mut arr, n);

    if arr.is_sorted() {
        arr.msg("自定义算法完成：数组已有序 ✓");
    } else {
        arr.msg("自定义算法结束：数组尚未有序 ✗");
        eprintln!("警告：算法返回时数组并未有序");
    }
    let _ = io::stdout().flush();
}
