# -*- coding: utf-8 -*-
"""插件式算法注册中心。

禁止任何 if-elif 硬编码分发：算法模块只用 ``@register_algo(...)`` 声明元数据，
UI 启动时 :func:`load_builtin` 自动扫描 ``algorithms/`` 目录下全部 ``cat*.py``
模块，构建出左侧按类别折叠、可按中英文实时搜索的算法树。

外部多语言脚本（C/C++/Python/Java/Rust/Go/JS/C#）编译后可调用
:func:`register_external` 注入动态元数据，与内置算法共享同一套索引。
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "AlgoMeta", "REGISTRY", "register_algo", "register_external", "get_algo",
    "all_algos", "category_names", "algos_in_category", "search_algos",
    "load_builtin", "is_loaded", "category_tree", "registry_stats",
]

CATEGORY_ORDER_HINT = (
    "01. ", "02. ", "03. ", "04. ", "05. ", "06. ",
    "07. ", "08. ", "09. ", "10. ", "11. ",
)


@dataclass(frozen=True)
class AlgoMeta:
    """一种排序算法的完整档案。"""

    algo_id: str
    name_zh: str
    name_en: str
    category: str
    time_best: str
    time_avg: str
    time_worst: str
    space: str
    stable: bool
    desc: str
    func: Callable
    external: bool = False          # 是否来自外部多语言脚本
    source_lang: str = "python"     # python / cpp / c / java / rust / go / js / cs
    extra: Dict[str, object] = field(default_factory=dict)

    # ---- 展示辅助 --------------------------------------------------------
    @property
    def index(self) -> int:
        """算法序号（algo_id 形如 ``076_dual_pivot_quicksort``）。"""
        m = re.match(r"(\d+)", self.algo_id)
        return int(m.group(1)) if m else -1

    @property
    def display(self) -> str:
        return f"{self.name_zh} · {self.name_en}"

    @property
    def category_index(self) -> int:
        m = re.match(r"(\d+)", self.category)
        return int(m.group(1)) if m else 99

    @property
    def stable_tag(self) -> str:
        return "Stable" if self.stable else "Unstable"

    def as_dict(self) -> Dict[str, object]:
        return {
            "algo_id": self.algo_id,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "category": self.category,
            "time_best": self.time_best,
            "time_avg": self.time_avg,
            "time_worst": self.time_worst,
            "space": self.space,
            "stable": self.stable,
            "desc": self.desc,
            "external": self.external,
            "source_lang": self.source_lang,
        }


#: 全局算法索引中心：algo_id -> AlgoMeta
REGISTRY: Dict[str, AlgoMeta] = {}

_loaded = False


def register_algo(**meta_kwargs):
    """装饰器：把函数登记为一种内置排序算法。

    用法::

        @register_algo(
            algo_id="001_bubble_sort",
            name_zh="标准冒泡排序",
            name_en="Bubble Sort (Standard)",
            category="01. 交换类排序 (Exchange Sorts)",
            time_best="O(n)", time_avg="O(n^2)", time_worst="O(n^2)",
            space="O(1)", stable=True,
            desc="基础相邻比较交换。")
        def bubble_sort(arr): ...
    """
    required = ("algo_id", "name_zh", "name_en", "category")

    def deco(fn: Callable) -> Callable:
        missing = [k for k in required if not meta_kwargs.get(k)]
        if missing:
            raise ValueError(f"{getattr(fn, '__name__', fn)} 缺少元数据字段: {missing}")
        meta = AlgoMeta(
            algo_id=meta_kwargs["algo_id"],
            name_zh=meta_kwargs["name_zh"],
            name_en=meta_kwargs["name_en"],
            category=meta_kwargs["category"],
            time_best=meta_kwargs.get("time_best", "?"),
            time_avg=meta_kwargs.get("time_avg", "?"),
            time_worst=meta_kwargs.get("time_worst", "?"),
            space=meta_kwargs.get("space", "O(1)"),
            stable=bool(meta_kwargs.get("stable", False)),
            desc=meta_kwargs.get("desc", ""),
            func=fn,
            external=bool(meta_kwargs.get("external", False)),
            source_lang=meta_kwargs.get("source_lang", "python"),
            extra=dict(meta_kwargs.get("extra", {})),
        )
        if meta.algo_id in REGISTRY:
            raise ValueError(f"算法 ID 冲突: {meta.algo_id}")
        REGISTRY[meta.algo_id] = meta
        return fn

    return deco


def register_external(algo_id: str, name_zh: str, name_en: str, runner: Callable,
                      category: str = "99. 外部自定义算法 (Custom)",
                      time_best: str = "外部实现", time_avg: str = "外部实现",
                      time_worst: str = "外部实现", space: str = "外部实现",
                      stable: bool = False, desc: str = "",
                      source_lang: str = "python",
                      extra: Optional[Dict[str, object]] = None) -> AlgoMeta:
    """登记一个外部多语言算法（runner 负责启动子进程并回传指令流）。

    ``extra`` 用来捎带不属于展示字段的信息，例如 ``{"source_path": ...}``
    —— 「查看源码」按钮据此定位外部算法的源文件。
    """
    meta = AlgoMeta(
        algo_id=algo_id, name_zh=name_zh, name_en=name_en, category=category,
        time_best=time_best, time_avg=time_avg, time_worst=time_worst,
        space=space, stable=stable, desc=desc, func=runner,
        external=True, source_lang=source_lang,
        extra=dict(extra or {}),
    )
    REGISTRY[algo_id] = meta
    return meta


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------
def get_algo(algo_id: str) -> Optional[AlgoMeta]:
    return REGISTRY.get(algo_id)


def all_algos() -> List[AlgoMeta]:
    """按算法序号升序返回全部算法。"""
    return sorted(REGISTRY.values(), key=lambda m: (m.index, m.algo_id))


def category_names() -> List[str]:
    """按类别序号升序返回类别名列表。"""
    cats = {m.category for m in REGISTRY.values()}
    return sorted(cats, key=lambda c: (re.match(r"(\d+)", c).group(1) if re.match(r"(\d+)", c) else "99", c))


def algos_in_category(category: str) -> List[AlgoMeta]:
    return sorted((m for m in REGISTRY.values() if m.category == category),
                  key=lambda m: (m.index, m.algo_id))


def category_tree() -> List[Tuple[str, List[AlgoMeta]]]:
    """``[(类别名, [算法...]), ...]``，供 QTreeWidget 直接消费。"""
    return [(c, algos_in_category(c)) for c in category_names()]


def search_algos(keyword: str) -> List[AlgoMeta]:
    """中英文 / ID / 分类模糊搜索（大小写不敏感）。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return all_algos()
    hit: List[AlgoMeta] = []
    for m in all_algos():
        haystack = " ".join((m.algo_id, m.name_zh, m.name_en, m.category, m.desc)).lower()
        if kw in haystack:
            hit.append(m)
    return hit


def registry_stats() -> Dict[str, object]:
    cats = category_names()
    return {
        "total": len(REGISTRY),
        "categories": len(cats),
        "builtin": sum(1 for m in REGISTRY.values() if not m.external),
        "external": sum(1 for m in REGISTRY.values() if m.external),
        "per_category": {c: len(algos_in_category(c)) for c in cats},
    }


# --------------------------------------------------------------------------
# 自动扫描加载
# --------------------------------------------------------------------------
def load_builtin(force: bool = False) -> int:
    """扫描 ``algorithms/`` 包，导入全部 ``cat*.py`` 模块并返回算法总数。"""
    global _loaded
    if _loaded and not force:
        return len(REGISTRY)
    pkg = importlib.import_module("algorithms")
    loader = getattr(pkg, "load_all", None)
    if loader is None:  # pragma: no cover
        raise RuntimeError("algorithms 包缺少 load_all()")
    loader()
    _loaded = True
    return len(REGISTRY)


def is_loaded() -> bool:
    return _loaded
