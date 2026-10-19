#!/usr/bin/env node
/* Sorting Visualizer Ultimate —— JavaScript (Node.js) 自定义算法模板（单文件）
 *
 * 手工验证：
 *     echo -e "8\n5 3 9 1 7 2 8 4" | node template.js
 *
 * 协议（每行一条指令写入 stdout）：
 *     CMP i j | CMP_VAL i val | READ i | SWAP i j | SET i val | FLIP l r
 *     AUX_INIT size | AUX_SET i val | AUX_GET i | AUX_SWAP i j | AUX_CMP i j | AUX_CLEAR
 *     MARK i ROLE | CLEAR_MARKS | MSG text...
 *
 * 只写你自己的排序逻辑即可，可视化 / 计数器 / 音效全部由指令流自动驱动。
 */

"use strict";

const fs = require("fs");

/* =========================================================================
 * 1. 统一数组包装器（无需修改）
 * ========================================================================= */
class VisualArray {
    constructor(values) {
        this.data = Array.from(values, (v) => Number(v) | 0);
        this.n = this.data.length;
        this.aux = [];
        this.auxReady = false;
    }

    // ---- 内部 ------------------------------------------------------------
    static emit(line) {
        // process.stdout.write 直接落管道，逐行即时送达主程序
        process.stdout.write(line + "\n");
    }

    /**
     * 用 Proxy 包一层，把 ``arr[i]`` 这种写法从「静默失败」变成「立刻报错」。
     *
     * JS 的类实例没有数字索引属性，``arr[3]`` 只会安静地返回 ``undefined``，
     * 于是 ``undefined < undefined === false``，整个排序没有任何交换 ——
     * 用户的代码语法全对、进程正常退出、实时预览却一步都没有。这比 Python
     * 那边的 TypeError 更难查，所以这里直接拦下来抛错。
     */
    static guarded(values) {
        const inner = new VisualArray(values);
        return new Proxy(inner, {
            get(target, key, receiver) {
                if (typeof key === "string" && /^\d+$/.test(key)) {
                    throw new TypeError(
                        `arr[${key}] 不可用：它会返回 undefined，导致比较永远为假、`
                        + `画面空白。请改用 arr.cmp(i, j) / arr.gt(i, j) / arr.get(i)。`);
                }
                return Reflect.get(target, key, receiver);
            },
            set(target, key, value, receiver) {
                if (typeof key === "string" && /^\d+$/.test(key)) {
                    throw new TypeError(
                        `arr[${key}] = v 不可用，请改用 arr.set(${key}, v)。`);
                }
                return Reflect.set(target, key, value, receiver);
            },
        });
    }

    check(i) {
        i = Number(i) | 0;
        if (i < 0 || i >= this.n) {
            throw new RangeError(`索引越界: ${i}（数组长度 ${this.n}）`);
        }
        return i;
    }

    checkAux(i) {
        i = Number(i) | 0;
        if (!this.auxReady || i < 0 || i >= this.aux.length) {
            throw new RangeError(`辅助数组索引越界: ${i}（长度 ${this.aux.length}）`);
        }
        return i;
    }

    size() { return this.n; }

    // ---- 读取 ------------------------------------------------------------
    peek(i) { return this.data[this.check(i)]; }

    get(i) {                                  // READ：计 1 次访问
        const k = this.check(i);
        VisualArray.emit(`READ ${k}`);
        return this.data[k];
    }

    // ---- 比较 ------------------------------------------------------------
    cmp(i, j) {                               // arr[i] < arr[j]
        const a = this.check(i), b = this.check(j);
        VisualArray.emit(`CMP ${a} ${b}`);
        return this.data[a] < this.data[b];
    }

    gt(i, j) {                                // arr[i] > arr[j]（严格）
        const a = this.check(i), b = this.check(j);
        VisualArray.emit(`CMP ${b} ${a}`);
        return this.data[a] > this.data[b];
    }

    cmpVal(i, val) {                          // arr[i] < val
        const a = this.check(i);
        val = Number(val) | 0;
        VisualArray.emit(`CMP_VAL ${a} ${val}`);
        return this.data[a] < val;
    }

    gtVal(i, val) {                           // arr[i] > val
        const a = this.check(i);
        val = Number(val) | 0;
        VisualArray.emit(`CMP_VAL ${a} ${val}`);
        return this.data[a] > val;
    }

    // ---- 写入 ------------------------------------------------------------
    swap(i, j) {
        const a = this.check(i), b = this.check(j);
        if (a === b) return;
        VisualArray.emit(`SWAP ${a} ${b}`);
        const t = this.data[a];
        this.data[a] = this.data[b];
        this.data[b] = t;
    }

    set(i, val) {
        const a = this.check(i);
        val = Number(val) | 0;
        VisualArray.emit(`SET ${a} ${val}`);
        this.data[a] = val;
    }

    flip(left, right) {                       // 原地翻转 [left, right]
        let l = this.check(left), r = this.check(right);
        if (l >= r) return;
        VisualArray.emit(`FLIP ${l} ${r}`);
        while (l < r) {
            const t = this.data[l];
            this.data[l] = this.data[r];
            this.data[r] = t;
            l++; r--;
        }
    }

    // ---- 辅助数组 --------------------------------------------------------
    auxInit(size) {
        const m = Math.max(0, Number(size) | 0);
        VisualArray.emit(`AUX_INIT ${m}`);
        this.aux = new Array(m).fill(0);
        this.auxReady = true;
    }

    auxSet(i, val) {
        const k = this.checkAux(i);
        val = Number(val) | 0;
        VisualArray.emit(`AUX_SET ${k} ${val}`);
        this.aux[k] = val;
    }

    auxGet(i) {
        const k = this.checkAux(i);
        VisualArray.emit(`AUX_GET ${k}`);
        return this.aux[k];
    }

    auxSwap(i, j) {
        const a = this.checkAux(i), b = this.checkAux(j);
        if (a === b) return;
        VisualArray.emit(`AUX_SWAP ${a} ${b}`);
        const t = this.aux[a];
        this.aux[a] = this.aux[b];
        this.aux[b] = t;
    }

    auxCmp(i, j) {
        const a = this.checkAux(i), b = this.checkAux(j);
        VisualArray.emit(`AUX_CMP ${a} ${b}`);
        return this.aux[a] < this.aux[b];
    }

    auxClear() {
        VisualArray.emit("AUX_CLEAR");
        this.aux = [];
        this.auxReady = false;
    }

    // ---- 标记与解说 ------------------------------------------------------
    mark(i, role) {
        const k = this.check(i);
        VisualArray.emit(`MARK ${k} ${String(role).toUpperCase()}`);
    }

    clearMarks() { VisualArray.emit("CLEAR_MARKS"); }

    msg(text) { VisualArray.emit(`MSG ${text}`); }

    isSorted() {
        for (let i = 1; i < this.n; i++) {
            if (this.data[i - 1] > this.data[i]) return false;
        }
        return true;
    }
}

/* =========================================================================
 * 2. ★ 在这里编写你的排序算法 ★（下面是一个可跑通的示例：插入排序）
 * ========================================================================= */
function myCustomSort(arr, n) {
    for (let i = 1; i < n; i++) {
        let j = i;
        arr.mark(j, "CURSOR");
        while (j > 0 && arr.gt(j - 1, j)) {   // arr[j-1] > arr[j] 才交换
            arr.swap(j - 1, j);
            j--;
        }
        arr.mark(j, "SORTED");
    }
    arr.clearMarks();
}

/* =========================================================================
 * 3. 输入输出（无需修改）
 * ========================================================================= */
function readInput() {
    let raw = "";
    try {
        raw = fs.readFileSync(0, "utf8");     // 0 = stdin，同步读取
    } catch (e) {
        throw new Error("读取 stdin 失败: " + e.message);
    }
    const tokens = raw.split(/\s+/).filter((t) => t.length > 0);
    if (tokens.length === 0) return [0, []];
    const n = parseInt(tokens[0], 10);
    if (!Number.isFinite(n) || n < 0) {
        throw new Error("N 不是合法整数: " + tokens[0]);
    }
    const values = tokens.slice(1, 1 + n).map((t) => {
        const v = parseInt(t, 10);
        if (!Number.isFinite(v)) throw new Error("元素不是整数: " + t);
        return v;
    });
    if (values.length !== n) {
        throw new Error(`数组元素不足 ${n} 个（实际 ${values.length} 个）`);
    }
    return [n, values];
}

function main() {
    let n, values;
    try {
        [n, values] = readInput();
    } catch (e) {
        process.stderr.write("输入解析失败: " + e.message + "\n");
        return 2;
    }

    const arr = VisualArray.guarded(values);
    try {
        myCustomSort(arr, n);
    } catch (e) {
        arr.msg(`自定义算法异常：${e.name}: ${e.message}`);
        process.stderr.write(`${e.stack || e.message}\n`);
        return 1;
    }

    if (arr.isSorted()) {
        arr.msg("自定义算法完成：数组已有序 ✓");
    } else {
        arr.msg("自定义算法结束：数组尚未有序 ✗");
        process.stderr.write("警告：算法返回时数组并未有序\n");
    }
    return 0;
}

if (require.main === module) {
    process.exitCode = main();
}
