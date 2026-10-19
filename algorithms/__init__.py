# -*- coding: utf-8 -*-
"""内置算法库自动扫描加载器。

``load_all()`` 会扫描本目录下所有 ``cat*.py`` 分类模块并逐一导入，
导入过程中 ``@register_algo`` 装饰器会把算法登记到 ``core.registry.REGISTRY``。
因此后续新增类别模块无需修改任何代码即可自动纳入算法树。
"""

from __future__ import annotations

import importlib
import os
from typing import List

__all__ = ["CATEGORY_MODULES", "discover_modules", "load_all", "expected_count"]

#: 规范书中约定的 11 个分类模块（按批次逐步补齐）
CATEGORY_MODULES = (
    "cat01_exchange",              # 001 - 018  交换类排序         18 种
    "cat02_selection_cycle",       # 019 - 030  选择/锦标赛/圈排序  12 种
    "cat03_heaps_trees",           # 031 - 048  堆与树结构排序      18 种
    "cat04_insertion_shell",       # 049 - 068  插入与希尔全序列    20 种
    "cat05_quicksorts",            # 069 - 084  快速排序全家族      16 种
    "cat06_mergesorts",            # 085 - 098  归并排序全家族      14 种
    "cat07_hybrids_blocks",        # 099 - 114  工业级混合与块归并  16 种
    "cat08_distribution_radix",    # 115 - 132  基数与分布类排序    18 种
    "cat09_sorting_networks",      # 133 - 144  排序网络与并行映射  12 种
    "cat10_pancake_rotation",      # 145 - 150  煎饼翻转与受限操作   6 种
    "cat11_esoteric_educational",  # 151 - 160  教学与幽默极限排序  10 种
)

_loaded = False


def discover_modules() -> List[str]:
    """扫描目录下真实存在的 ``cat*.py`` 模块（按文件名升序）。

    **打包后的关键分支**：PyInstaller 会把 ``algorithms`` 整个包收进 PYZ
    归档，磁盘上根本没有 ``cat*.py`` 文件，``os.listdir`` 会直接抛
    ``FileNotFoundError``。一旦这里炸掉，冻结版的算法库就是 0 种 ——
    所以取不到目录时**退回清单里的 11 个模块名**，由 :func:`load_all`
    逐个尝试导入。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        names = [
            f[:-3] for f in os.listdir(here)
            if f.startswith("cat") and f.endswith(".py")
            and not f.startswith("cat_")
        ]
    except OSError:                       # 冻结环境：源码不在磁盘上
        names = []
    return sorted(names) or list(CATEGORY_MODULES)


def load_all(force: bool = False) -> int:
    """导入全部分类模块，返回本次**成功导入**的模块数。"""
    global _loaded
    if _loaded and not force:
        return 0
    loaded = 0
    for name in discover_modules():
        try:
            importlib.import_module(f"{__name__}.{name}")
            loaded += 1
        except ModuleNotFoundError as exc:
            # 只放过「这个分类模块本身不存在」（分批交付期间清单会更早补全），
            # 模块内部缺第三方库（exc.name == 'numpy' 等）必须继续向上抛。
            if exc.name != f"{__name__}.{name}":
                raise
    _loaded = True
    return loaded


def expected_count() -> int:
    return 160
