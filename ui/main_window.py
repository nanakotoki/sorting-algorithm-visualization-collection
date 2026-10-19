# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— 主窗口、算法导航树、HUD 看板与同屏赛马。

布局（规范书 2.1 / 5.3 / 5.4）
-----------------------------
::

    ┌──────────────┬────────────────────────────────────────────┐
    │  搜索过滤框   │            渲染画布（1 / 2 / 4 宫格）         │
    │              │  ┌──────────────────────────┐              │
    │  160 算法     │  │ 半透明 HUD 状态看板（毛玻璃浮层）│          │
    │  分类折叠树   │  └──────────────────────────┘              │
    │              ├────────────────────────────────────────────┤
    │              │  时间轴 QSlider + 播放控制 + 0.1x~2000x 倍速 │
    │              ├────────────────────────────────────────────┤
    │              │  N / 分布 / 视图样式 / 配色 / 音效 / 赛马    │
    └──────────────┴────────────────────────────────────────────┘

播放引擎
--------
一个 16 ms 的 ``QTimer``（≈60 FPS）驱动全部窗格。每帧按当前倍速换算出
**Steps Per Frame (SPF)**：

* ``speed < 1``（慢动作教学档）用小数累加器实现「每 K 帧走 1 步」；
* ``speed ≥ 1`` 时每帧批量推进 ``speed`` 步，仅在帧末重绘一次画面。

录制与回放分离：算法运行被录制成 :class:`~core.protocol.Trace` 后再交给
:class:`~core.protocol.TracePlayer` 回放，因此单步前进 / 后退 / 任意拖拽跳转
都是纯状态机操作，与算法本身完全解耦。
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox,
                               QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QSizePolicy,
                               QSlider, QSpinBox, QSplitter, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from core import data_generator as dg
from core.algo_source import SourceUnavailable, resolve_source, source_ready
from core.audio_synth import WAVEFORMS, AudioSynth, audio_backend_status
from core.protocol import (DEFAULT_MAX_OPS, Trace, TracePlayer,
                           collect_notes_between, ensure_deep_recursion,
                           extract_hot_events, is_sorted_values, record)
from core.polyglot_runner import autoload_custom
from core.registry import AlgoMeta, all_algos, load_builtin, registry_stats
from ui.canvas_widget import (PALETTES, STYLES, CanvasWidget, VizFrame,
                              set_slice_source, slice_source_name)
from ui.custom_algo_dialog import CustomAlgoDialog, warm_toolchains
from ui.export_dialog import ExportDialog
from ui.source_viewer import SourceViewerDialog

__all__ = ["MainWindow", "AlgoSession", "extract_hot", "collect_notes",
           "apply_theme"]

#: 数据量范围（规范书 5.4：8 ~ 10,000）
N_MIN = 8
N_MAX = 10_000

#: 倍速范围（规范书 5.4：0.1x ~ 2000x），滑块按对数刻度映射
SPEED_MIN = 0.1
SPEED_MAX = 2000.0

#: 单帧最多推进的原子操作数，防止极端倍速下界面卡死
SPF_HARD_CAP = 20_000

#: 每帧最多触发的音符数
NOTES_PER_FRAME = 6

#: 排序完成后翠绿扫光校验动画的时长（秒）
SWEEP_SECONDS = 0.9


# ==========================================================================
# 1. 深色极客主题
# ==========================================================================
_THEME_QSS = """
* { outline: none; }
QWidget { background: #0D0E12; color: #D8DEE9; font-size: 12px; }
QMainWindow, QDialog { background: #0D0E12; }

QFrame#Panel, QWidget#Panel {
    background: #12141A; border: 1px solid #1E222B; border-radius: 8px;
}
QLabel#Section {
    color: #6E7A8C; font-size: 11px; font-weight: 600;
    letter-spacing: 1px; padding: 2px 0;
}
QLabel#AlgoTitle { color: #ECEFF4; font-size: 14px; font-weight: 700; }
QLabel#AlgoSub   { color: #7C8AA0; font-size: 11px; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #171A21; border: 1px solid #252A34; border-radius: 6px;
    padding: 5px 8px; selection-background-color: #00B4D8; color: #E5E9F0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #00B4D8;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #171A21; border: 1px solid #252A34;
    selection-background-color: #0077B6; color: #E5E9F0;
}

QTreeWidget {
    background: #101219; border: 1px solid #1E222B; border-radius: 8px;
    show-decoration-selected: 1; padding: 4px;
}
QTreeWidget::item { padding: 4px 2px; border-radius: 4px; }
QTreeWidget::item:hover { background: #1A1F29; }
QTreeWidget::item:selected { background: #0B4F6C; color: #FFFFFF; }
QTreeWidget::branch { background: transparent; }

QPushButton, QToolButton {
    background: #1A1F29; border: 1px solid #252A34; border-radius: 6px;
    padding: 5px 10px; color: #D8DEE9;
}
QPushButton:hover, QToolButton:hover { background: #232A36; border-color: #00B4D8; }
QPushButton:pressed, QToolButton:pressed { background: #0B4F6C; }
QPushButton:disabled, QToolButton:disabled { color: #4A5262; border-color: #1E222B; }
QToolButton#Play { font-size: 15px; padding: 4px 14px; }
QPushButton#Accent {
    background: #0077B6; border-color: #00B4D8; color: #FFFFFF; font-weight: 600;
}
QPushButton#Accent:hover { background: #0090D6; }

QSlider::groove:horizontal {
    height: 4px; background: #1E222B; border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #00B4D8; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #ECEFF4; width: 12px; margin: -5px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #00B4D8; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid #2C333F; background: #171A21;
}
QCheckBox::indicator:checked { background: #00B4D8; border-color: #00B4D8; }

QScrollBar:vertical { background: #101219; width: 10px; margin: 0; }
QScrollBar::handle:vertical {
    background: #252A34; border-radius: 5px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #00B4D8; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { background: #101219; height: 10px; }
QScrollBar::handle:horizontal {
    background: #252A34; border-radius: 5px; min-width: 24px;
}

QSplitter::handle { background: #15181F; width: 6px; }
QStatusBar { background: #101219; color: #6E7A8C; border-top: 1px solid #1E222B; }
QListWidget {
    background: #101219; border: 1px solid #1E222B; border-radius: 6px;
}
QListWidget::item { padding: 3px 6px; }
QListWidget::item:selected { background: #0B4F6C; }
"""


def apply_theme(app: QApplication) -> None:
    """应用深色极客主题，并挑选一款等宽字体。"""
    app.setStyleSheet(_THEME_QSS)
    for name in ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                 "Menlo", "Monaco", "Courier New"):
        if name in QFontDatabase.families():
            app.setProperty("monoFamily", name)
            break


def mono_font(size: int = 10, bold: bool = False) -> QFont:
    """取一款等宽字体（HUD 看板与计数器专用）。"""
    family = "Consolas"
    app = QApplication.instance()
    if app is not None:
        family = app.property("monoFamily") or family
    f = QFont(family, size)
    f.setStyleHint(QFont.Monospace)
    f.setBold(bold)
    return f


# ==========================================================================
# 2. 指令流 → 视觉/听觉事件
# ==========================================================================
#: 这两个纯函数已下沉到 :mod:`core.protocol`（视频导出器也要用，而
#: ``exporter`` 不能反向 import ``ui``，否则和导出对话框形成循环导入），
#: 这里保留同名薄封装以免破坏既有调用点与外部脚本。
extract_hot = extract_hot_events
collect_notes = collect_notes_between


# ==========================================================================
# 3. 会话（一次算法运行的完整状态）
# ==========================================================================
class AlgoSession:
    """一种算法在**一份固定的初始数组**上的一次录制 + 回放会话。"""

    __slots__ = ("meta", "values", "trace", "player", "error")

    def __init__(self, meta: AlgoMeta, values: Sequence[int],
                 max_ops: int = DEFAULT_MAX_OPS) -> None:
        self.meta = meta
        self.values = [int(v) for v in values]
        self.error = ""
        try:
            self.trace: Trace = record(meta.func, self.values, max_ops=max_ops)
        except Exception as exc:                       # 算法自身抛错
            self.trace = Trace()
            self.error = f"{type(exc).__name__}: {exc}"
        self.player = TracePlayer(self.trace, self.values)

    @property
    def total(self) -> int:
        return self.trace.n_ops

    @property
    def finished(self) -> bool:
        return self.player.at_end()

    @property
    def sorted_ok(self) -> bool:
        return is_sorted_values(self.player.data)


class RecordWorker(QThread):
    """后台录制线程：避免大规模 N 下阻塞 UI 事件循环。"""

    finished_ok = Signal(object)     # AlgoSession
    failed = Signal(str)

    def __init__(self, meta: AlgoMeta, values: Sequence[int],
                 max_ops: int, parent=None) -> None:
        super().__init__(parent)
        self._meta = meta
        self._values = list(values)
        self._max_ops = max_ops

    def run(self) -> None:                             # pragma: no cover
        ensure_deep_recursion()
        try:
            sess = AlgoSession(self._meta, self._values, self._max_ops)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit(sess)


# ==========================================================================
# 4. HUD 状态看板（毛玻璃浮层）
# ==========================================================================
class HudOverlay(QWidget):
    """画布左上角的半透明毛玻璃浮层，用等宽字体实时刷新全部关键指标。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedWidth(392)
        self._lines: List[Tuple[str, str, str]] = []
        self._title = ("", "")
        self.setMinimumHeight(240)

    def set_content(self, title_zh: str, title_en: str,
                    rows: Sequence[Tuple[str, str, str]]) -> None:
        self._title = (title_zh, title_en)
        self._lines = list(rows)
        self.setFixedHeight(58 + 17 * max(1, len(self._lines)) + 10)
        self.update()

    def paintEvent(self, event) -> None:              # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect().adjusted(0, 0, -1, -1)
        # 半透明深色底 + 细描边，模拟毛玻璃浮层
        painter.setPen(QPen(QColor(0x2A, 0x31, 0x3D, 200), 1))
        painter.setBrush(QColor(0x0B, 0x0D, 0x12, 205))
        painter.drawRoundedRect(r, 10, 10)

        x = 14
        y = 24
        # 面板是固定宽度的，而「分类」「MSG」这类字段长度完全不可控（分类名
        # 最长一条有 40 多个字符）。早期版本只用 ``[:34]`` 硬切，字符数够但
        # 像素宽度照样溢出，字被面板右边框直接裁掉半截 —— 必须交给
        # ``QFontMetrics.elidedText`` 按**真实像素宽度**做省略。
        avail_w = max(60, r.width() - 2 * x)
        painter.setFont(mono_font(11, bold=True))
        painter.setPen(QColor(0xEC, 0xEF, 0xF4))
        painter.drawText(x, y,
                         painter.fontMetrics().elidedText(self._title[0],
                                                          Qt.ElideRight, avail_w))
        y += 16
        painter.setFont(mono_font(9))
        painter.setPen(QColor(0x7C, 0x8A, 0xA0))
        painter.drawText(x, y,
                         painter.fontMetrics().elidedText(self._title[1],
                                                          Qt.ElideRight, avail_w))
        y += 6
        painter.setPen(QPen(QColor(0x25, 0x2A, 0x34), 1))
        painter.drawLine(x, y, r.width() - 8, y)
        y += 14

        val_x = x + 132
        for label, value, color in self._lines:
            painter.setFont(mono_font(9))
            painter.setPen(QColor(0x6E, 0x7A, 0x8C))
            painter.drawText(x, y, label)
            painter.setFont(mono_font(9, bold=True))
            painter.setPen(QColor(color) if color else QColor(0xD8, 0xDE, 0xE9))
            room = max(40, r.width() - val_x - 10)
            painter.drawText(val_x, y,
                             painter.fontMetrics().elidedText(str(value),
                                                              Qt.ElideRight, room))
            y += 17
        painter.end()


# ==========================================================================
# 5. 单个渲染窗格
# ==========================================================================
class RacePane(QWidget):
    """一个「画布 + 标题条」单元；四宫格赛马时最多同时存在 4 个。"""

    clicked = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.header = QLabel("—")
        self.header.setObjectName("AlgoSub")
        self.header.setFont(mono_font(9, bold=True))
        self.header.setFixedHeight(16)
        self.canvas = CanvasWidget(self)
        layout.addWidget(self.header)
        layout.addWidget(self.canvas, 1)
        self.session: Optional[AlgoSession] = None
        self.sweep_t0 = 0.0
        self.chord_played = False
        #: 是否处于「启用」状态。不能依赖 ``isVisible()``——窗口尚未 show()
        #: 时所有子控件的 isVisible() 都是 False，会误判成没有活动窗格。
        self.active = True

    def attach(self, session: Optional[AlgoSession], style: str = "bars") -> None:
        self.session = session
        self.sweep_t0 = 0.0
        self.chord_played = False
        self.canvas.set_style(style)
        if session is None:
            self.header.setText("空槽位 · 从左侧算法树选一个加入赛马")
            self.canvas.set_placeholder("空槽位")
            self.canvas.set_frame(VizFrame(values=(1,)))
        else:
            self.header.setText(f"#{session.meta.index:03d}  {session.meta.name_zh}")

    def build_frame(self, n_max: int, palette: str) -> VizFrame:
        sess = self.session
        if sess is None:
            return VizFrame(values=(1,), n_max=1)
        p = sess.player
        hot, hot_aux = extract_hot(sess.trace, p.step)
        # 「已播到末尾」是扫光定格与「全绿」两个效果共同的前提
        finished = p.at_end() and not sess.trace.truncated and p.total > 0
        sweep = 0.0
        if finished:
            if self.sweep_t0 <= 0.0:
                self.sweep_t0 = time.perf_counter()
            sweep = min(1.0, (time.perf_counter() - self.sweep_t0) / 0.8)
        else:
            self.sweep_t0 = 0.0
        return VizFrame(values=p.data, aux=p.aux, aux_active=p.aux_active,
                        marks=p.marks, hot=hot, hot_aux=hot_aux,
                        n_max=n_max, palette=palette, sweep=sweep,
                        # 录制定型时校验过的有序标志，交给渲染层统一铺绿
                        done=finished and bool(sess.sorted_ok),
                        # 时空瀑布流需要步号来识别「往回拖 / 回到 0」，
                        # 其余样式完全忽略该字段
                        step=p.step)

    def refresh_header(self) -> None:
        sess = self.session
        if sess is None:
            return
        p = sess.player
        tag = ""
        if sess.trace.truncated:
            tag = " · ⚠已截断"
        elif p.at_end():
            tag = " · ✓完成" if sess.sorted_ok else " · ✗未排好"
        self.header.setText(
            f"#{sess.meta.index:03d}  {sess.meta.name_zh}"
            f"   CMP {p.cmp}   SWP {p.swaps}   步 {p.step}/{p.total}{tag}")


# ==========================================================================
# 6. 主窗口
# ==========================================================================
class MainWindow(QMainWindow):
    """Sorting Visualizer Ultimate 主窗口。"""

    def __init__(self, start_algo: Optional[str] = None,
                 start_n: int = 128) -> None:
        super().__init__()
        ensure_deep_recursion()

        load_builtin()

        # 启动时按清单把上次导入的外部多语言算法重新挂上（源码还在才注册）
        self._custom_notes: List[str] = []
        self._custom_dialog: Optional[CustomAlgoDialog] = None
        self._export_dialog: Optional[ExportDialog] = None
        try:
            self._custom_loaded = autoload_custom(report=self._custom_notes)
        except Exception as exc:                      # 清单坏了也不能拖垮启动
            self._custom_loaded = 0
            self._custom_notes.append(f"自定义算法清单读取失败：{exc}")
        self._sync_library_title()
        self._fit_to_screen()

        # ---- 运行参数 ----------------------------------------------------
        self.n_value = int(start_n)
        self.dist_kind = "random"
        self.style_key = "bars"
        self.palette_key = "white"
        self.seed = random.randrange(1 << 30)
        self.speed = 8.0
        self._acc = 0.0
        self._base_values: List[int] = []

        self.synth = AudioSynth(enabled=False, waveform="sine", volume=0.30)

        self._panes: List[RacePane] = []
        self._grid_count = 1
        self._slots: List[AlgoMeta] = []
        self._primary: Optional[AlgoMeta] = None
        self._worker: Optional[RecordWorker] = None
        self._pending: List[Tuple[int, AlgoMeta]] = []
        self._current_recording = 0
        self._resume_after_drag = False
        self.playing = False               # 用户是否「意图播放」
        self._finish_t0 = 0.0              # 全部排完的时刻（用于跑完扫光动画）
        self._fps_t0 = time.perf_counter()
        self._fps_frames = 0
        self._fps = 0.0

        self._regen_timer = QTimer(self)   # 拖动 N 滑块时防抖，避免疯狂重录
        self._regen_timer.setSingleShot(True)
        self._regen_timer.setInterval(220)
        self._regen_timer.timeout.connect(lambda: self.regenerate())

        # 播放引擎计时器必须先于 regenerate() 建好——后者会 stop() 它
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)                     # ≈60 FPS
        self.timer.timeout.connect(self._tick)

        self._build_ui()
        self._build_shortcuts()
        self._populate_tree()
        self._apply_layout()

        # 启动一秒钟后在后台预热工具链缓存（检测 python/javac/node/dotnet…）。
        # 这样第一次打开「自定义算法工作室」时已经能直接从缓存读，秒开。
        # 探测本身在子线程里，加上 CREATE_NO_WINDOW，用户既看不到黑窗也不会卡。
        QTimer.singleShot(1000, warm_toolchains)

        # 默认选中第一号算法
        metas = all_algos()
        target = None
        if start_algo:
            target = next((m for m in metas if m.algo_id == start_algo), None)
        self._primary = target or (metas[0] if metas else None)
        if self._primary is not None:
            self._select_in_tree(self._primary.algo_id)
        self.regenerate(keep_algo=True)

        info = audio_backend_status()
        self._set_status_ready(info)

    # ------------------------------------------------------------------
    # 6.1 界面搭建
    # ------------------------------------------------------------------
    #: 设计基准尺寸（1920×1080 屏上最舒展）
    DESIGN_SIZE = (1560, 940)
    #: 可压缩下限：再小画布就没有意义了
    MIN_SIZE = (900, 600)

    def _fit_to_screen(self) -> None:
        """按**屏幕可用区域**决定窗口尺寸，而不是写死一个数。

        早期版本直接 ``resize(1560, 940)``，在三种很常见的机器上都会出问题：

        * 1366×768 笔记本 —— 高度直接超出屏幕；
        * 1080P 但系统缩放 125% / 150% —— Qt 拿到的是**逻辑像素**，
          可用区域只剩 1536×864 / 1280×720；
        * 接了投影仪或多屏、可用区域更小的情况。

        表现就是「最大化之后底部参数栏还是被挤在屏幕外，怎么拖都看不全」。
        这里取「不超可用区域的 94%」，同时把最小尺寸也按屏幕收缩（否则最小
        尺寸一旦大于屏幕，Qt 会把窗口撑出边界，最大化也救不回来），最后居中。
        """
        dw, dh = self.DESIGN_SIZE
        mw, mh = self.MIN_SIZE
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            # 最小尺寸不得超过屏幕，否则窗口必然溢出
            mw = min(mw, max(640, avail.width()))
            mh = min(mh, max(480, avail.height()))
            w = min(dw, int(avail.width() * 0.94))
            h = min(dh, int(avail.height() * 0.94))
            w = max(mw, w)
            h = max(mh, h)
        else:                                              # pragma: no cover
            w, h = dw, dh
        self.setMinimumSize(mw, mh)
        self.resize(w, h)
        if screen is not None:
            avail = screen.availableGeometry()
            self.move(avail.x() + max(0, (avail.width() - w) // 2),
                      avail.y() + max(0, (avail.height() - h) // 2))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 1200])
        root.addWidget(splitter, 1)

        self.status = self.statusBar()
        self.lbl_fps = QLabel("—")
        self.lbl_fps.setFont(mono_font(9))
        self.status.addPermanentWidget(self.lbl_fps)

    # ---- 左侧：算法导航树 --------------------------------------------
    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(400)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        head = QLabel("ALGORITHM LIBRARY")
        head.setObjectName("Section")
        head_row.addWidget(head)
        head_row.addStretch(1)
        self.btn_custom = QToolButton()
        self.btn_custom.setText("⌨ 自定义算法")
        self.btn_custom.setToolTip(
            "打开多语言算法工作室：用 C / C++ / Python / Java / Rust / Go / JS / C# "
            "写自己的排序算法，一键编译运行并加入左侧算法树")
        self.btn_custom.setCursor(Qt.PointingHandCursor)
        self.btn_custom.clicked.connect(self.open_custom_studio)
        head_row.addWidget(self.btn_custom)
        lay.addLayout(head_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索算法：中英文 / 编号 / 分类…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_tree_click)
        self.tree.itemActivated.connect(self._on_tree_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        lay.addWidget(self.tree, 1)

        # 算法档案卡
        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(3)
        self.lbl_card_title = QLabel("—")
        self.lbl_card_title.setObjectName("AlgoTitle")
        self.lbl_card_title.setWordWrap(True)
        self.lbl_card_sub = QLabel("—")
        self.lbl_card_sub.setObjectName("AlgoSub")
        self.lbl_card_sub.setWordWrap(True)
        self.lbl_card_meta = QLabel("—")
        self.lbl_card_meta.setFont(mono_font(9))
        self.lbl_card_meta.setWordWrap(True)
        self.lbl_card_desc = QLabel("—")
        self.lbl_card_desc.setObjectName("AlgoSub")
        self.lbl_card_desc.setWordWrap(True)
        for w in (self.lbl_card_title, self.lbl_card_sub, self.lbl_card_meta,
                  self.lbl_card_desc):
            cl.addWidget(w)

        # 「查看源码」：源码默认不铺在界面上，点这里才按需读取（Ctrl+U 同效）。
        # 放在档案卡内部，跟「这个算法是什么」的信息挨在一起，位置最直觉。
        self.btn_source = QToolButton()
        self.btn_source.setText("📄 查看源码")
        self.btn_source.setCursor(Qt.PointingHandCursor)
        self.btn_source.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_source.setToolTip(
            "查看当前算法的完整实现（只读，快捷键 Ctrl+U）\n"
            "内置算法读取磁盘上的 .py；外部算法读取你导入时的那份源码\n"
            "在算法树上右键也能打开")
        self.btn_source.clicked.connect(lambda: self.open_source_viewer())
        cl.addWidget(self.btn_source)

        lay.addWidget(card)
        return panel

    # ---- 右侧：画布 + HUD + 控制栏 -----------------------------------
    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        # 画布容器 + HUD 浮层
        holder = QFrame()
        holder.setObjectName("Panel")
        self.canvas_holder = holder
        grid = QGridLayout(holder)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(8)
        self.pane_grid = grid
        for i in range(4):
            pane = RacePane(holder)
            self._panes.append(pane)
            grid.addWidget(pane, i // 2, i % 2)
        holder.setMinimumHeight(240)

        self.hud = HudOverlay(holder)
        self.hud.move(22, 22)
        self.hud.raise_()

        rl.addWidget(holder, 1)
        rl.addWidget(self._build_transport())
        rl.addWidget(self._build_params())
        return right

    # ---- 时间轴与播放控制 --------------------------------------------
    def _build_transport(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_reset = QToolButton(); self.btn_reset.setText("⏮ 重置")
        self.btn_back1 = QToolButton(); self.btn_back1.setText("◀ 步退")
        self.btn_play = QToolButton(); self.btn_play.setText("▶ 播放")
        self.btn_play.setObjectName("Play")
        self.btn_fwd1 = QToolButton(); self.btn_fwd1.setText("步进 ▶")
        self.btn_end = QToolButton(); self.btn_end.setText("⏭ 末尾")
        self.btn_rerecord = QToolButton(); self.btn_rerecord.setText("↻ 重新录制")
        self.btn_export = QToolButton(); self.btn_export.setText("🎬 导出视频")
        self.btn_export.setObjectName("Accent")
        self.btn_export.setToolTip(
            "把当前算法的整段排序过程浓缩成 1080P / 4K @ 60FPS 的 H.264 MP4\n"
            "（FFmpeg 管道离屏逐帧渲染 + 立体声 AAC 音轨，音画完全同步，不丢帧）\n"
            "快捷键 Ctrl+E")
        for b in (self.btn_reset, self.btn_back1, self.btn_play, self.btn_fwd1,
                  self.btn_end, self.btn_rerecord, self.btn_export):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        row.addSpacing(10)
        self.btn_export.clicked.connect(self.open_export_dialog)

        row.addWidget(QLabel("倍速"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(0, 1000)
        self.speed_slider.setValue(self._speed_to_slider(self.speed))
        self.speed_slider.setMinimumWidth(120)
        self.speed_slider.setMaximumWidth(300)
        self.speed_slider.valueChanged.connect(self._on_speed_slider)
        row.addWidget(self.speed_slider, 1)
        self.lbl_speed = QLabel(f"{self.speed:g}x")
        self.lbl_speed.setFont(mono_font(9, bold=True))
        self.lbl_speed.setFixedWidth(58)
        row.addWidget(self.lbl_speed)

        self.lbl_step = QLabel("步 0 / 0")
        self.lbl_step.setFont(mono_font(9))
        row.addWidget(self.lbl_step)
        lay.addLayout(row)

        # 第二行：进度条 + 倍速预设按钮。
        # 6 个预设按钮原先和上面那排控制按钮挤在同一行，两者宽度相加把播放栏的
        # 最小宽度顶到 1350+；挪到进度条右侧后，第一行只剩「7 个按钮 + 倍速
        # 滑块 + 步数」，窄屏下也不会把整个窗口撑开。
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.setCursor(Qt.PointingHandCursor)
        self.progress.sliderMoved.connect(self._on_progress_drag)
        self.progress.sliderPressed.connect(self._on_progress_press)
        self.progress.sliderReleased.connect(self._on_progress_release)
        bottom.addWidget(self.progress, 1)

        for preset in (0.25, 1, 8, 64, 512, 2000):
            b = QToolButton()
            b.setText(f"{preset:g}x")
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(mono_font(8))
            b.setToolTip(f"把倍速设为 {preset:g}x")
            b.clicked.connect(lambda _=False, v=preset: self.set_speed(v))
            bottom.addWidget(b)
        lay.addLayout(bottom)

        self.btn_reset.clicked.connect(self.reset_playback)
        self.btn_back1.clicked.connect(lambda: self.nudge(-1))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_fwd1.clicked.connect(lambda: self.nudge(1))
        self.btn_end.clicked.connect(self.jump_end)
        self.btn_rerecord.clicked.connect(lambda: self.regenerate(keep_algo=True))
        return bar

    # ---- 参数控制栏 ---------------------------------------------------
    def _build_params(self) -> QWidget:
        """参数栏：**分两行**排布。

        早期版本把 N / 分布 / 视图 / 配色 / 音效 / 宫格 / 赛马全挤在一行，
        各控件的固定宽度累加约 1600 px，直接把主窗口的最小宽度顶到 1600 以上
        —— 在 1366×768、或 1080P 开 125% 缩放（逻辑宽度只剩 1536）的机器上，
        窗口最大化之后右侧和底部就被挤出屏幕，怎么拖都看不全。
        拆成「数据与画面」「音效与赛马」两行后，单行最宽约 810 px，安全。
        """
        bar = QFrame()
        bar.setObjectName("Panel")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(10, 7, 10, 7)
        outer.setSpacing(6)

        # ---- 第一行：数据与画面 ------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(8)

        # 数据量
        row.addWidget(QLabel("数据量 N"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(N_MIN, N_MAX)
        self.spin_n.setValue(self.n_value)
        self.spin_n.setFixedWidth(70)
        self.spin_n.valueChanged.connect(self._on_n_spin)
        row.addWidget(self.spin_n)
        self.slider_n = QSlider(Qt.Horizontal)
        self.slider_n.setRange(0, 1000)
        self.slider_n.setValue(self._n_to_slider(self.n_value))
        self.slider_n.setFixedWidth(108)
        self.slider_n.valueChanged.connect(self._on_n_slider)
        row.addWidget(self.slider_n)
        row.addSpacing(8)

        # 分布
        row.addWidget(QLabel("分布"))
        self.combo_dist = QComboBox()
        for key, label in dg.DISTRIBUTIONS:
            self.combo_dist.addItem(label, key)
        self.combo_dist.setCurrentIndex(
            max(0, [k for k, _ in dg.DISTRIBUTIONS].index(self.dist_kind)))
        self.combo_dist.setFixedWidth(150)
        self.combo_dist.currentIndexChanged.connect(self._on_dist_changed)
        row.addWidget(self.combo_dist)
        row.addSpacing(8)

        # 视图样式
        row.addWidget(QLabel("视图"))
        self.combo_style = QComboBox()
        for key, label in STYLES:
            self.combo_style.addItem(label, key)
        self.combo_style.setFixedWidth(196)
        # 说明：label 形如「对称声波图 · Mirror」。加宽到 196 px 是为了让 18 个
        # 视图名都不被省略成「对称声波图 · Mir…」—— 一旦省略，几个长名字看起来
        # 就完全一样了。
        self.combo_style.currentIndexChanged.connect(self._on_style_changed)
        row.addWidget(self.combo_style)

        # 「高清切片还原」模式的图源导入。放在视图旁边而不是设置对话框里：
        # 这个按钮只在 slice 视图下有意义，摆得远就没人找得到。
        self.btn_slice = QPushButton("🖼 导入图片")
        self.btn_slice.setToolTip(
            "为「高清切片还原 · Slices」模式导入一张本地图片（JPG / PNG / BMP / WebP）。\n"
            "不导入时使用内置的「赛博朋克落日星云」合成画卷。")
        self.btn_slice.clicked.connect(self._on_import_slice_image)
        row.addWidget(self.btn_slice)
        row.addSpacing(8)

        # 配色
        row.addWidget(QLabel("配色"))
        self.combo_palette = QComboBox()
        for key, label in PALETTES:
            self.combo_palette.addItem(label, key)
        self.combo_palette.setFixedWidth(124)
        self.combo_palette.currentIndexChanged.connect(self._on_palette_changed)
        row.addWidget(self.combo_palette)
        row.addStretch(1)
        outer.addLayout(row)

        # ---- 第二行：音效与赛马 ------------------------------------------
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        # 音效
        self.chk_audio = QCheckBox("音效")
        self.chk_audio.toggled.connect(self._on_audio_toggled)
        row2.addWidget(self.chk_audio)
        self.combo_wave = QComboBox()
        for key, label in WAVEFORMS:
            self.combo_wave.addItem(label, key)
        self.combo_wave.setFixedWidth(108)
        self.combo_wave.currentIndexChanged.connect(
            lambda i: self.synth.set_waveform(self.combo_wave.itemData(i)))
        row2.addWidget(self.combo_wave)
        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(30)
        self.slider_vol.setFixedWidth(64)
        self.slider_vol.setToolTip("音量")
        self.slider_vol.valueChanged.connect(
            lambda v: setattr(self.synth, "volume", v / 100.0))
        row2.addWidget(self.slider_vol)

        row2.addStretch(1)

        # 赛马
        row2.addWidget(QLabel("宫格"))
        self.combo_grid = QComboBox()
        self.combo_grid.addItem("单视图", 1)
        self.combo_grid.addItem("双宫格", 2)
        self.combo_grid.addItem("四宫格", 4)
        self.combo_grid.setFixedWidth(76)
        self.combo_grid.currentIndexChanged.connect(self._on_grid_changed)
        row2.addWidget(self.combo_grid)

        self.btn_add_race = QPushButton("＋ 加入赛马")
        self.btn_add_race.setObjectName("Accent")
        self.btn_add_race.clicked.connect(self._on_add_race)
        row2.addWidget(self.btn_add_race)

        self.btn_clear_race = QPushButton("清空赛马")
        self.btn_clear_race.clicked.connect(self._on_clear_race)
        row2.addWidget(self.btn_clear_race)

        outer.addLayout(row2)
        return bar

    def _build_shortcuts(self) -> None:
        """键盘快捷键走 ``keyPressEvent``（见下），这里只做提示性占位。"""
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event) -> None:           # noqa: N802
        """全局快捷键：空格播放/暂停、←→ 单步、R/Home 重置、End 末尾、
        Ctrl+F 搜索、Ctrl+E 导出、Ctrl+U 查看源码。

        当焦点落在输入框里（搜索框 / 数值微调框 / 下拉框）时**完全放行**，
        否则在搜索框里敲一个 ``r`` 就会把播放重置掉。
        """
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QAbstractSpinBox, QComboBox)):
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play()
        elif key == Qt.Key_Right:
            self.nudge(1)
        elif key == Qt.Key_Left:
            self.nudge(-1)
        elif key in (Qt.Key_R, Qt.Key_Home):
            self.reset_playback()
        elif key == Qt.Key_End:
            self.jump_end()
        elif key == Qt.Key_F and event.modifiers() & Qt.ControlModifier:
            self.search.setFocus()
            self.search.selectAll()
        elif key == Qt.Key_E and event.modifiers() & Qt.ControlModifier:
            self.open_export_dialog()
        elif key == Qt.Key_U and event.modifiers() & Qt.ControlModifier:
            self.open_source_viewer()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # ------------------------------------------------------------------
    # 6.2 算法树
    # ------------------------------------------------------------------
    def _populate_tree(self, keyword: str = "") -> None:
        self.tree.clear()
        metas = all_algos()
        if keyword.strip():
            from core.registry import search_algos
            hit = set(m.algo_id for m in search_algos(keyword))
            metas = [m for m in metas if m.algo_id in hit]

        root: Dict[str, QTreeWidgetItem] = {}
        for m in metas:
            parent = root.get(m.category)
            if parent is None:
                parent = QTreeWidgetItem(self.tree)
                parent.setText(0, m.category)
                parent.setFlags(Qt.ItemIsEnabled)
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
                parent.setForeground(0, QColor(0xFF, 0x9E, 0x2C) if m.external
                                     else QColor(0x00, 0xB4, 0xD8))
                root[m.category] = parent
            item = QTreeWidgetItem(parent)
            item.setText(0, ("⚙ " if m.external else "") + f"#{m.index:03d}  {m.name_zh}")
            item.setData(0, Qt.UserRole, m.algo_id)
            tip = f"{m.name_en}\n{m.desc}"
            if m.external:
                tip += f"\n[外部 {m.source_lang} 实现]"
                item.setForeground(0, QColor(0xFF, 0x9E, 0x2C))
            tip += "\n\n右键 → 查看源码 / 加入赛马"
            item.setToolTip(0, tip)
        self.tree.expandAll()

    def _select_in_tree(self, algo_id: str) -> None:
        it = self._find_item(algo_id)
        if it is not None:
            self.tree.setCurrentItem(it)
            self.tree.scrollToItem(it)

    def _find_item(self, algo_id: str) -> Optional[QTreeWidgetItem]:
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it is None:
                continue
            if it.data(0, Qt.UserRole) == algo_id:
                return it
            for i in range(it.childCount()):
                stack.append(it.child(i))
        return None

    def _on_search(self, text: str) -> None:
        self._populate_tree(text)
        if self._primary is not None:
            self._select_in_tree(self._primary.algo_id)

    def _on_tree_menu(self, pos) -> None:             # noqa: N802
        """算法树右键菜单：查看源码 / 加入赛马 / 复制名称。

        只在菜单里给入口，不往树节点上挂按钮 —— 160 个节点的行内控件会明显拖慢
        滚动，也会把「浏览算法」这件事弄得很吵。
        """
        item = self.tree.itemAt(pos)
        algo_id = item.data(0, Qt.UserRole) if item is not None else None
        if not algo_id:
            return
        from core.registry import get_algo
        meta = get_algo(algo_id)
        if meta is None:
            return

        menu = QMenu(self)
        act_src = menu.addAction("📄 查看源码")
        act_src.setShortcut("Ctrl+U")
        act_race = menu.addAction("➕ 加入赛马对比")
        act_copy = menu.addAction("⧉ 复制算法名称")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_src:
            self.open_source_viewer(meta)
        elif chosen is act_race:
            self._primary = meta
            self._on_add_race()
        elif chosen is act_copy:
            QApplication.clipboard().setText(f"{meta.name_zh} · {meta.name_en}")

    def _on_tree_click(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        algo_id = item.data(0, Qt.UserRole)
        if not algo_id:
            return
        from core.registry import get_algo
        meta = get_algo(algo_id)
        if meta is None:
            return
        self._primary = meta
        self._slots = []
        self._grid_count = 1
        self.combo_grid.setCurrentIndex(0)
        self._apply_layout()
        self.regenerate(keep_algo=True)

    def _update_card(self, meta: AlgoMeta) -> None:
        self.lbl_card_title.setText(f"#{meta.index:03d}  {meta.name_zh}")
        self.lbl_card_sub.setText(meta.name_en)
        self.lbl_card_meta.setText(
            f"{meta.category}\n"
            f"time  best {meta.time_best} | avg {meta.time_avg} | worst {meta.time_worst}\n"
            f"space {meta.space}   "
            f"{'✓ Stable' if meta.stable else '✗ Unstable'}"
            + (f"   [{meta.source_lang}]" if meta.external else ""))
        self.lbl_card_desc.setText(meta.desc)
        self._sync_source_button(meta)

    def _sync_source_button(self, meta: Optional[AlgoMeta]) -> None:
        """按「这份源码现在取不取得到」决定按钮是否可点。"""
        btn = getattr(self, "btn_source", None)
        if btn is None:
            return
        ready = source_ready(meta)
        btn.setEnabled(ready)
        if ready:
            btn.setToolTip(
                f"查看「{meta.name_zh}」的源码（只读，Ctrl+U）\n"
                "内置算法读取磁盘上的 .py；外部算法读取你导入时的那份源码\n"
                "在算法树上右键也能打开")
        else:
            btn.setToolTip(
                "这个算法的源码取不到：\n"
                "· 外部算法的源码文件被移动或删除了 → 重新导入一次即可\n"
                "· 打包版缺少 algorithms_src 数据目录 → 重新运行 build_exe.py")

    # ------------------------------------------------------------------
    # 6.2.1 查看源码
    # ------------------------------------------------------------------
    def open_source_viewer(self, meta: Optional[AlgoMeta] = None) -> None:
        """打开「查看源码」弹窗。

        源码**不在界面上常驻**：这里才真正去磁盘读文件、用 AST 切出算法本体。
        ``meta`` 为空时看当前主算法；从算法树右键进来时可以指定任意一条。
        """
        target = meta or self._primary
        if target is None:
            return
        try:
            bundle = resolve_source(target)
        except SourceUnavailable as exc:
            QMessageBox.information(self, "源码不可用", str(exc))
            return
        SourceViewerDialog(bundle, self).exec()

    # ------------------------------------------------------------------
    # 6.3 参数联动
    # ------------------------------------------------------------------
    @staticmethod
    def _n_to_slider(n: int) -> int:
        lo, hi = math.log(N_MIN), math.log(N_MAX)
        return int(round((math.log(max(N_MIN, n)) - lo) / (hi - lo) * 1000))

    @staticmethod
    def _slider_to_n(v: int) -> int:
        lo, hi = math.log(N_MIN), math.log(N_MAX)
        n = int(round(math.exp(lo + (hi - lo) * v / 1000.0)))
        return max(N_MIN, min(N_MAX, n))

    @staticmethod
    def _speed_to_slider(s: float) -> int:
        lo, hi = math.log(SPEED_MIN), math.log(SPEED_MAX)
        return int(round((math.log(max(SPEED_MIN, s)) - lo) / (hi - lo) * 1000))

    @staticmethod
    def _slider_to_speed(v: int) -> float:
        lo, hi = math.log(SPEED_MIN), math.log(SPEED_MAX)
        s = math.exp(lo + (hi - lo) * v / 1000.0)
        return round(s, 3) if s < 10 else round(s)

    def _on_n_spin(self, value: int) -> None:
        if value == self.n_value:
            return
        self.n_value = int(value)
        self.slider_n.blockSignals(True)
        self.slider_n.setValue(self._n_to_slider(self.n_value))
        self.slider_n.blockSignals(False)
        self._schedule_regenerate()

    def _on_n_slider(self, value: int) -> None:
        n = self._slider_to_n(value)
        if n == self.n_value:
            return
        self.n_value = n
        self.spin_n.blockSignals(True)
        self.spin_n.setValue(n)
        self.spin_n.blockSignals(False)
        self._schedule_regenerate()

    def _on_dist_changed(self, idx: int) -> None:
        self.dist_kind = self.combo_dist.itemData(idx) or "random"
        self._schedule_regenerate()

    def _on_style_changed(self, idx: int) -> None:
        self.style_key = self.combo_style.itemData(idx) or "bars"
        for pane in self._panes:
            pane.canvas.set_style(self.style_key)
            # 换视图即重置动画相位与视角：否则从全息双螺旋切过去时，
            # 新视图会继承上一次拖拽留下的 Yaw 角，画面是歪的。
            pane.canvas.reset_view()
        self._render_all()
        self._ensure_timer()

    # ---- 切片还原模式的图源导入 --------------------------------------
    def _on_import_slice_image(self) -> None:
        """为「高清切片还原」模式选一张本地图片（规范书第二节特殊模式 1）。"""
        path, _sel = QFileDialog.getOpenFileName(
            self, "选择用于「高清切片还原」的图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;所有文件 (*.*)")
        if not path:
            return
        err = set_slice_source(path)
        if err:
            QMessageBox.warning(self, "导入失败",
                                f"无法使用这张图片：\n{err}")
            return
        if self.style_key != "slice":
            i = next((k for k, (key, _l) in enumerate(STYLES)
                      if key == "slice"), None)
            if i is not None:
                self.combo_style.setCurrentIndex(i)
        self._render_all()
        self.status.showMessage(f"切片图源已切换：{slice_source_name()}", 6000)

    def _on_palette_changed(self, idx: int) -> None:
        self.palette_key = self.combo_palette.itemData(idx) or "white"
        self._render_all()

    def _on_speed_slider(self, value: int) -> None:
        self.speed = self._slider_to_speed(value)
        self.lbl_speed.setText(f"{self.speed:g}x")

    def set_speed(self, value: float) -> None:
        self.speed = float(value)
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(self._speed_to_slider(self.speed))
        self.speed_slider.blockSignals(False)
        self.lbl_speed.setText(f"{self.speed:g}x")

    def _on_audio_toggled(self, on: bool) -> None:
        ok = self.synth.set_enabled(on)
        if on and not ok:
            self.chk_audio.blockSignals(True)
            self.chk_audio.setChecked(False)
            self.chk_audio.blockSignals(False)
            self.status.showMessage(
                f"音效不可用：{self.synth.error or '未检测到输出设备'}", 6000)

    # ---- 赛马 --------------------------------------------------------
    def _on_grid_changed(self, idx: int) -> None:
        count = int(self.combo_grid.itemData(idx) or 1)
        self._grid_count = count
        if count > 1 and len(self._slots) < count:
            metas = all_algos()
            pool = [m for m in metas if m.algo_id != getattr(self._primary, "algo_id", "")]
            start = 0
            for i, m in enumerate(pool):
                if self._primary is not None and m.index > self._primary.index:
                    start = i
                    break
            pick = pool[start:start + max(0, count - 1)]
            self._slots = ([self._primary] if self._primary else []) + pick
            self._slots = self._slots[:count]
        self._apply_layout()
        self.regenerate(keep_algo=True)

    def _on_add_race(self) -> None:
        meta = self._primary
        if meta is None:
            return
        if any(m.algo_id == meta.algo_id for m in self._slots):
            return
        if len(self._slots) >= 4:
            self.status.showMessage("赛马最多同时容纳 4 种算法", 4000)
            return
        self._slots.append(meta)
        self._grid_count = max(1, len(self._slots))
        idx = {1: 0, 2: 1, 4: 2}.get(self._grid_count, 0)
        self.combo_grid.blockSignals(True)
        self.combo_grid.setCurrentIndex(idx)
        self.combo_grid.blockSignals(False)
        self._apply_layout()
        self.regenerate(keep_algo=True)

    def _on_clear_race(self) -> None:
        self._slots = []
        self._grid_count = 1
        self.combo_grid.blockSignals(True)
        self.combo_grid.setCurrentIndex(0)
        self.combo_grid.blockSignals(False)
        self._apply_layout()
        self.regenerate(keep_algo=True)

    def _active_slots(self) -> List[Optional[AlgoMeta]]:
        if self._grid_count <= 1 or not self._slots:
            return [self._primary]
        return list(self._slots[:self._grid_count])

    def _apply_layout(self) -> None:
        """按宫格数重新排布窗格：单视图占满整块区域。"""
        for i, pane in enumerate(self._panes):
            self.pane_grid.removeWidget(pane)
        slots = self._active_slots()
        count = max(1, len(slots))
        if count == 1:
            self.pane_grid.addWidget(self._panes[0], 0, 0, 1, 2)
            for pane in self._panes[1:]:
                pane.hide()
        elif count == 2:
            self.pane_grid.addWidget(self._panes[0], 0, 0, 1, 1)
            self.pane_grid.addWidget(self._panes[1], 0, 1, 1, 1)
            for pane in self._panes[2:]:
                pane.hide()
        else:
            for i in range(4):
                self.pane_grid.addWidget(self._panes[i], i // 2, i % 2)
        for i, pane in enumerate(self._panes):
            pane.active = i < count
            pane.setVisible(pane.active)
            pane.canvas.set_show_labels(count == 1)
        self.hud.setVisible(count == 1)

    # ------------------------------------------------------------------
    # 6.4 数据生成与录制
    # ------------------------------------------------------------------
    def _schedule_regenerate(self) -> None:
        """拖动 N 滑块时防抖：停顿 220 ms 才真正重新生成数据并重录。"""
        self._regen_timer.start()

    def regenerate(self, keep_algo: bool = False) -> None:
        """按当前参数重新生成数据、重新录制全部窗格的指令流。"""
        self._regen_timer.stop()
        self.timer.stop()
        self._finish_t0 = 0.0
        self.seed = random.randrange(1 << 30)
        self._base_values = dg.generate(self.dist_kind, self.n_value, seed=self.seed)
        slots = self._active_slots()
        count = max(1, len(slots))

        # 立即可见的初始画面（不必等录制完成）
        for i, pane in enumerate(self._panes[:count]):
            meta = slots[i] if i < len(slots) else None
            pane.attach(None, self.style_key)
            if meta is not None:
                pane.header.setText(f"#{meta.index:03d}  {meta.name_zh}   （录制中…）")
                pane.canvas.set_placeholder("正在录制指令流…")
                pane.canvas.set_frame(VizFrame(values=self._base_values,
                                               n_max=max(1, self.n_value),
                                               palette=self.palette_key))
        self.progress.setRange(0, 0)
        self.lbl_step.setText("步 0 / 0")
        if self._primary is not None:
            self._update_card(self._primary)

        self._pending = [(i, m) for i, m in enumerate(slots[:count]) if m is not None]
        self._start_next_record()

    def _start_next_record(self) -> None:
        # 上一个录制线程必须彻底结束并释放，否则 Qt 会警告
        # 「QThread: Destroyed while thread is still running」
        old = self._worker
        if old is not None:
            if old.isRunning():
                old.wait(5000)
            old.deleteLater()
            self._worker = None

        if not self._pending:
            self._on_record_done()
            return
        i, meta = self._pending.pop(0)
        self._current_recording = i
        self._worker = RecordWorker(meta, self._base_values, DEFAULT_MAX_OPS, self)
        self._worker.finished_ok.connect(self._on_worker_ok)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_ok(self, session: AlgoSession) -> None:
        i = getattr(self, "_current_recording", 0)
        pane = self._panes[i]
        pane.attach(session, self.style_key)
        if session.error:
            pane.header.setText(f"#{session.meta.index:03d}  录制失败：{session.error}")
            self.status.showMessage(f"算法执行出错：{session.error}", 8000)
        self._start_next_record()

    def _on_worker_failed(self, msg: str) -> None:
        self.status.showMessage(f"录制失败：{msg}", 8000)
        self._start_next_record()

    def _on_record_done(self) -> None:
        primary = self._panes[0].session
        total = primary.total if primary else 0
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self._render_all()
        self._update_hud()
        self._ensure_timer()

    # ------------------------------------------------------------------
    # 6.5 播放引擎
    # ------------------------------------------------------------------
    def _active_panes(self) -> List[RacePane]:
        return [p for p in self._panes if p.active and p.session is not None]

    def _max_total(self) -> int:
        return max([p.session.total for p in self._active_panes()] or [0])

    def _steps_for_frame(self) -> int:
        if self.speed < 1.0:
            self._acc += self.speed
            if self._acc >= 1.0:
                n = int(self._acc)
                self._acc -= n
                return min(n, SPF_HARD_CAP)
            return 0
        return min(int(self.speed), SPF_HARD_CAP)

    def _tick(self) -> None:
        panes = self._active_panes()
        if not panes:
            self.timer.stop()
            return

        steps = self._steps_for_frame()
        if steps > 0:
            notes: List[int] = []
            for pane in panes:
                sess = pane.session
                p = sess.player
                before = p.step
                if p.at_end():
                    continue
                p.seek(min(p.step + steps, p.total))
                if self.synth.enabled and pane is panes[0]:
                    notes = collect_notes(sess.trace, before, p.step, p.data)
                if pane is panes[0] and p.at_end() and not sess.trace.truncated:
                    if not pane.chord_played:
                        pane.chord_played = True
                        self.synth.finish_chord(10)
            if notes:
                self.synth.play_many(notes, max(1, self.n_value))

        self._render_all()
        self._update_progress()
        self._update_hud()

        if all(p.session.player.at_end() for p in panes):
            now = time.perf_counter()
            if self._finish_t0 <= 0.0:
                self._finish_t0 = now
                self.playing = False
                self.btn_play.setText("▶ 播放")
            elif now - self._finish_t0 > SWEEP_SECONDS:
                # 让扫光动画完整播完再停表，而不是到终点就僵住
                self.timer.stop()
                self._finish_t0 = 0.0
        else:
            self._finish_t0 = 0.0

    def _render_all(self) -> None:
        n_max = max(1, self.n_value)
        for pane in self._panes:
            if pane.active:
                pane.canvas.set_frame(pane.build_frame(n_max, self.palette_key))
                pane.refresh_header()
        self._count_fps()

    def _count_fps(self) -> None:
        self._fps_frames += 1
        now = time.perf_counter()
        dt = now - self._fps_t0
        if dt >= 0.5:
            self._fps = self._fps_frames / dt
            self._fps_frames = 0
            self._fps_t0 = now
            ms = self._panes[0].canvas.last_render_ms
            self.lbl_fps.setText(
                f"{self._fps:5.1f} FPS   渲染 {ms:5.1f} ms   音效 "
                f"{'ON' if self.synth.enabled else 'OFF'}")

    def _update_progress(self) -> None:
        p = self._panes[0].session.player if self._panes[0].session else None
        if p is None:
            return
        if not self.progress.isSliderDown():
            self.progress.blockSignals(True)
            self.progress.setRange(0, p.total)
            self.progress.setValue(p.step)
            self.progress.blockSignals(False)
        self.lbl_step.setText(f"步 {p.step} / {p.total}")

    def _ensure_timer(self) -> None:
        """若用户处于「意图播放」状态且本轮已有可回放的指令流，则恢复计时器。

        更换数据量 / 视图样式会触发重新录制，这个钩子保证录制完成后能自动
        接着播，而不是悄悄停住。
        """
        if self.playing and self._max_total() > 0 and not self.timer.isActive():
            self.timer.start()
            self.btn_play.setText("⏸ 暂停")

    def toggle_play(self) -> None:
        if self.playing:
            self._stop_playback()
            return
        self.playing = True
        self.btn_play.setText("⏸ 暂停")
        if self._max_total() > 0:
            self.timer.start()

    def _stop_playback(self) -> None:
        self.playing = False
        self.timer.stop()
        self.btn_play.setText("▶ 播放")

    def reset_playback(self) -> None:
        self._stop_playback()
        self._finish_t0 = 0.0
        for pane in self._panes:
            if pane.session is not None:
                pane.session.player.seek(0)
                pane.sweep_t0 = 0.0
                pane.chord_played = False
        self._render_all()
        self._update_progress()
        self._update_hud()

    def nudge(self, delta: int) -> None:
        """单步前进 / 后退（慢动作教学档）。"""
        was = self.timer.isActive()
        self.timer.stop()
        self._finish_t0 = 0.0
        for pane in self._active_panes():
            p = pane.session.player
            if delta > 0:
                p.advance(delta)
            else:
                p.step_back(-delta)
            pane.sweep_t0 = 0.0
            pane.chord_played = False
        self._render_all()
        self._update_progress()
        self._update_hud()
        if was:
            self.timer.start()

    def jump_end(self) -> None:
        self._stop_playback()
        for pane in self._active_panes():
            pane.session.player.seek(pane.session.total)
            pane.chord_played = False
        self._render_all()
        self._update_progress()
        self._update_hud()
        self._start_sweep_if_done()

    def _start_sweep_if_done(self) -> None:
        """已全部排完时，让计时器多跑 SWEEP_SECONDS 把翠绿扫光校验动画播完。"""
        panes = self._active_panes()
        if not panes or self._max_total() <= 0:
            return
        if not all(p.session.player.at_end() for p in panes):
            return
        for pane in panes:
            pane.sweep_t0 = 0.0
        self._finish_t0 = time.perf_counter()
        if not self.timer.isActive():
            self.timer.start()

    def _on_progress_press(self) -> None:
        self._resume_after_drag = self.timer.isActive()
        self.timer.stop()

    def _on_progress_drag(self, value: int) -> None:
        self.lbl_step.setText(f"步 {value} / {self._max_total()}")

    def _on_progress_release(self) -> None:
        value = self.progress.value()
        self._finish_t0 = 0.0
        for pane in self._active_panes():
            tot = pane.session.total
            pane.session.player.seek(min(value, tot))
            pane.sweep_t0 = 0.0
            pane.chord_played = False
        self._render_all()
        self._update_progress()
        self._update_hud()
        if self._resume_after_drag:
            self.timer.start()
        self._start_sweep_if_done()

    # ------------------------------------------------------------------
    # 6.6 HUD
    # ------------------------------------------------------------------
    def _update_hud(self) -> None:
        pane = self._panes[0]
        sess = pane.session
        if sess is None:
            return
        p = sess.player
        meta = sess.meta
        pct = 100.0 * p.progress
        state = "已完成 ✓" if p.at_end() else ("播放中 ▶" if self.timer.isActive()
                                            else "已暂停 ⏸")
        if sess.trace.truncated:
            state += f"   ⚠已截断({sess.trace.n_ops} 步)"
        stable = "Stable ✓" if meta.stable else "Unstable ✗"
        rows = [
            ("分类", meta.category, "#00B4D8"),
            ("时间复杂度", f"best {meta.time_best} / avg {meta.time_avg}", ""),
            ("", f"worst {meta.time_worst}", ""),
            ("空间复杂度", meta.space, ""),
            ("稳定性", stable, "#00E676" if meta.stable else "#FF9E2C"),
            ("数据规模 N", f"{self.n_value}   {dg.describe(self.dist_kind)}", ""),
            ("Comparisons", f"{p.cmp:,}", "#FFEA00"),
            ("Swaps", f"{p.swaps:,}", "#FF2A55"),
            ("Main Writes", f"{p.main_writes:,}", ""),
            ("Aux  Writes", f"{p.aux_writes:,}", "#4DD0E1"),
            ("Total Accesses", f"{p.accesses:,}", ""),
            ("进度", f"{p.step:,} / {p.total:,}   {pct:5.1f}%", ""),
            ("算法耗时", f"{sess.trace.elapsed * 1000:.2f} ms", ""),
            ("状态", state, "#00E676" if p.at_end() else "#ECEFF4"),
            ("MSG", p.msg or "—", "#00F5D4"),
        ]
        self.hud.set_content(f"#{meta.index:03d}  {meta.name_zh}",
                             meta.name_en, rows)

    # ------------------------------------------------------------------
    # 6.7 外部多语言自定义算法（Batch 5）
    # ------------------------------------------------------------------
    def _sync_library_title(self) -> None:
        """标题栏实时反映算法库规模（含外部自定义算法）。"""
        stats = registry_stats()
        extra = f"（含 {stats['external']} 种外部自定义）" if stats['external'] else ""
        self.setWindowTitle(
            f"Sorting Visualizer Ultimate — {stats['total']} 种排序算法{extra} / "
            f"{stats['categories']} 大分类")

    def open_custom_studio(self) -> None:
        """打开多语言自定义算法工作室（非模态，可边看主窗口边调）。"""
        if self._custom_dialog is None:
            self._custom_dialog = CustomAlgoDialog(self)
            self._custom_dialog.algo_registered.connect(self._on_custom_registered)
        self._custom_dialog.show()
        self._custom_dialog.raise_()
        self._custom_dialog.activateWindow()

    def _on_custom_registered(self, algo_id: str) -> None:
        """外部算法注册 / 注销后刷新算法树、标题与状态栏。"""
        self._sync_library_title()
        self._populate_tree(self.search.text())
        stats = registry_stats()
        if algo_id:
            meta = next((m for m in all_algos() if m.algo_id == algo_id), None)
            if meta is not None:
                self._select_in_tree(algo_id)
                self.status.showMessage(
                    f"已加入算法库：#{meta.index:03d} {meta.name_zh}"
                    f"（{meta.source_lang}）— 可直接播放 / 赛马 / 导出视频", 9000)
        else:
            self.status.showMessage(
                f"自定义算法已变更，当前算法库共 {stats['total']} 种"
                f"（外部 {stats['external']} 种）", 6000)
        self._set_status_ready(audio_backend_status())

    # ------------------------------------------------------------------
    # 6.8 离线高清视频导出（Batch 6）
    # ------------------------------------------------------------------
    def open_export_dialog(self) -> None:
        """打开视频导出对话框，并把当前主窗格的算法与指令流交给它。

        对话框非模态：导出跑在后台线程里，用户仍可继续看别的算法。
        每次打开都重新 ``refresh_source``，因此「换了算法 / 改了 N 之后再导出」
        拿到的永远是最新那一份指令流。
        """
        sess = self._panes[0].session
        if sess is None or sess.trace.n_ops == 0:
            QMessageBox.information(
                self, "暂时无法导出",
                "当前还没有可回放的指令流。\n"
                "请先在左侧选一个算法（或调大一点数据量），等录制完成后重试。")
            return

        if self._export_dialog is None:
            self._export_dialog = ExportDialog(
                self, meta=sess.meta, values=sess.values, trace=sess.trace,
                n_value=self.n_value, dist_kind=self.dist_kind,
                style=self.style_key, palette=self.palette_key)
        else:
            self._export_dialog.refresh_source(
                meta=sess.meta, values=sess.values, trace=sess.trace,
                n_value=self.n_value, dist_kind=self.dist_kind)
        self._export_dialog.show()
        self._export_dialog.raise_()
        self._export_dialog.activateWindow()
        self.status.showMessage(
            f"视频导出：#{sess.meta.index:03d} {sess.meta.name_zh} · "
            f"{sess.trace.n_ops:,} 步指令流已就绪（1080P / 4K @ 30~120FPS）", 8000)

    # ------------------------------------------------------------------
    def _set_status_ready(self, info: Dict[str, object]) -> None:
        stats = registry_stats()
        msg = (f"算法库 {stats['total']} 种 / {stats['categories']} 类  🔍 搜索  "
               f"空格 播放/暂停  ←→ 单步  R 重置  End 末尾  Ctrl+E 导出视频")
        if stats["external"]:
            msg += f"  |  ⚙ 外部自定义 {stats['external']} 种"
        if not info.get("sounddevice"):
            msg += f"  |  音效不可用：{info.get('note') or '未安装 sounddevice'}"
        self.status.showMessage(msg)
        if self._custom_notes:
            self.status.showMessage("外部算法清单：" + "；".join(self._custom_notes), 12000)
            self._custom_notes = []

    def closeEvent(self, event) -> None:              # noqa: N802
        try:
            self.timer.stop()
            self.synth.close()
            if self._worker is not None and self._worker.isRunning():
                self._worker.wait(1500)
            # 正在导出的后台线程必须收干净，否则退出时会留下孤立的 ffmpeg 进程。
            # 这里不走 dialog.close()，避免弹「确定要中止吗」打断退出流程。
            dlg = self._export_dialog
            if dlg is not None:
                worker = getattr(dlg, "_worker", None)
                if worker is not None and worker.isRunning():
                    dlg.shutdown()
        finally:
            event.accept()
