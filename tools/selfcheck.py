# -*- coding: utf-8 -*-
"""算法库自检脚本（开发期质量闸门）。

对每一种已注册算法：

1. 在 9 种规模 × 多种数据分布上录制指令流；
2. 用 :class:`TracePlayer` 从头回放到尾，确认**回放结果严格有序**
   （同时验证"指令流可重放"这一核心不变量）；
3. 做一次"后退 10 步再前进 10 步"的回溯一致性校验；
4. 报告失败用例、耗时与指令规模。

用法::

    python tools/selfcheck.py            # 默认全量
    python tools/selfcheck.py --big      # 追加 n=384 / 512 大数据集
    python tools/selfcheck.py --filter heap
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import registry                                   # noqa: E402
from core.data_generator import generate                    # noqa: E402
from core.protocol import (DEFAULT_MAX_OPS, TracePlayer,    # noqa: E402
                           ensure_deep_recursion, is_sorted_values, record)

SMALL_SIZES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17, 31, 33, 64, 100)
BIG_SIZES = (257, 384)
DIST_FOR_SMALL = ("random", "reversed", "nearly_sorted", "few_unique_4",
                  "few_unique_8", "sine_wave", "sawtooth", "organ_pipe",
                  "scrambled_segments")
DIST_FOR_BIG = ("random", "reversed", "few_unique_4", "scrambled_segments")


def check_one(meta, kind: str, n: int, max_ops: int):
    """返回 None 表示通过，否则返回错误描述字符串。"""
    values = generate(kind, n, seed=20240921)
    # 小数据集不应出现任何截断，用较小的预算即可快速暴露死循环 / 超量操作
    budget = max_ops if n > 100 else min(max_ops, 600_000)
    tr = record(meta.func, values, max_ops=budget)
    if tr.truncated:
        return f"指令流被截断（{n} 个元素产生了 ≥{budget} 步操作）"

    player = TracePlayer(tr, values)
    player.run_to_end()
    if not is_sorted_values(player.data):
        return f"结果未排序: {player.data[:16]}..."

    # 回溯一致性：后退 10 步再前进 10 步必须回到同一状态
    end_state = list(player.data)
    end_step = player.step
    player.step_back(10)
    mid_state = list(player.data)
    player.advance(10)
    if player.step != end_step or player.data != end_state:
        return "回溯（step back / advance）状态不一致"
    if player.step == end_step and len(end_state) > 1 and mid_state == end_state:
        # 极小规模下可能不足 10 步，属正常
        pass

    # 回到 0 步必须还原初始数组
    player.seek(0)
    if player.data != list(values):
        return "seek(0) 未还原初始数组"
    return None


def run_worker(args) -> int:
    ensure_deep_recursion()
    registry.load_builtin()
    stats = registry.registry_stats()
    print(f"已注册算法 {stats['total']} 种，分属 {stats['categories']} 个类别")
    print("-" * 78)

    algos = registry.all_algos()
    if args.filter:
        kw = args.filter.lower()
        algos = [m for m in algos if kw in m.algo_id.lower() or kw in m.name_en.lower()
                 or kw in m.name_zh or kw in m.category.lower()]
        print(f"过滤后剩余 {len(algos)} 种算法")

    sizes = list(SMALL_SIZES) + (list(BIG_SIZES) if args.big else [])
    dists_small = list(DIST_FOR_SMALL)
    dists_big = list(DIST_FOR_BIG)
    max_ops = args.max_ops

    failures = []
    slowest = []
    t_all = time.perf_counter()
    for meta in algos:
        t0 = time.perf_counter()
        cases = 0
        first_err = None
        for kind in dists_small:
            for n in SMALL_SIZES:
                cases += 1
                try:
                    err = check_one(meta, kind, n, max_ops)
                except Exception:
                    err = "异常: " + traceback.format_exc(limit=3).strip().split("\n")[-1]
                if err and first_err is None:
                    first_err = (kind, n, err)
        if args.big:
            for kind in dists_big:
                for n in BIG_SIZES:
                    cases += 1
                    try:
                        err = check_one(meta, kind, n, max_ops)
                    except Exception:
                        err = "异常: " + traceback.format_exc(limit=3).strip().split("\n")[-1]
                    if err and first_err is None:
                        first_err = (kind, n, err)
        dt = time.perf_counter() - t0
        slowest.append((dt, meta))
        if first_err is None:
            print(f"  PASS  #{meta.index:03d} {meta.name_zh:<18} {meta.time_avg:>12} "
                  f"{cases} 例 {dt:6.2f}s")
        else:
            kind, n, err = first_err
            print(f"  FAIL  #{meta.index:03d} {meta.name_zh:<18} {cases} 例 {dt:6.2f}s")
            print(f"        首例失败: 分布={kind} n={n} → {err}")
            failures.append((meta, kind, n, err))

    print("-" * 78)
    print(f"总计 {len(algos)} 种算法，{time.perf_counter() - t_all:.1f}s")
    slowest.sort(reverse=True, key=lambda x: x[0])
    print("最慢 5 种：" + "，".join(
        f"#{m.index:03d} {m.name_zh} {d:.2f}s" for d, m in slowest[:5]))
    if failures:
        print(f"\n失败 {len(failures)} 种：")
        for meta, kind, n, err in failures:
            print(f"  - #{meta.index:03d} {meta.name_zh}: [{kind} n={n}] {err}")
        return 1
    print("\n全部通过 ✅")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="排序可视化算法库自检")
    ap.add_argument("--big", action="store_true", help="追加 n=257/384 大数据集")
    ap.add_argument("--filter", default="", help="按 ID / 中英文名 / 类别过滤")
    ap.add_argument("--max-ops", type=int, default=DEFAULT_MAX_OPS)
    ap.add_argument("--stack-mb", type=int, default=64, help="工作线程栈大小")
    args = ap.parse_args()

    result = {"code": 1}

    def job():
        result["code"] = run_worker(args)

    # 递归型算法需要大栈线程
    threading.stack_size(args.stack_mb * 1024 * 1024)
    th = threading.Thread(target=job)
    th.start()
    th.join()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
