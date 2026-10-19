# -*- coding: utf-8 -*-
"""Sorting Visualizer Ultimate —— 离线视频导出参数对话框。

对应规范书 6.1：用户可设定分辨率（1080P / 1440P / 4K）、帧率
（30 / 60 / 120 FPS）、目标总时长（自动把整个排序过程平滑浓缩）、
音效与编码器，然后一键导出 H.264 MP4。

界面职责与引擎严格分离：本文件只负责「收集参数 + 展示进度」，
真正干活的是 :class:`exporter.video_exporter.ExportWorker`；因此同一条
导出链路既能被这个对话框调用，也能被 ``main.py --export`` 的命令行
入口直接调用（后者用于无头环境 / 自动化回归）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from core.audio_synth import WAVEFORMS
from core.protocol import Trace
from exporter.video_exporter import (DURATION_PRESETS, EASINGS,
                                     ENCODER_CHOICES, FPS_CHOICES,
                                     RESOLUTIONS, ExportProgress,
                                     ExportResult, ExportSettings,
                                     ExportWorker, default_output_path,
                                     ffmpeg_report)
from ui.canvas_widget import PALETTES, STYLES

__all__ = ["ExportDialog", "mono_ui_font"]

_MONO_STACK = ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono",
               "Courier New")
_CJK_STACK = ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC",
              "SimHei", "sans-serif")


def mono_ui_font(pt: int = 9, bold: bool = False) -> QFont:
    """界面里用的等宽字体（含中文字体回退，与主窗口保持一致的观感）。"""
    f = QFont(_MONO_STACK[2])
    try:
        f.setFamilies([*_MONO_STACK, *_CJK_STACK])
    except Exception:                                          # pragma: no cover
        pass
    f.setPointSize(pt)
    f.setBold(bold)
    f.setStyleHint(QFont.Monospace)
    return f


class ExportDialog(QDialog):
    """导出参数 + 进度面板。"""

    def __init__(self, parent=None, *, meta=None,
                 values: Sequence[int] = (), trace: Optional[Trace] = None,
                 n_value: Optional[int] = None, dist_kind: str = "random",
                 style: str = "bars", palette: str = "rainbow") -> None:
        super().__init__(parent)
        self.setWindowTitle("导出高清视频 · FFmpeg 1080P / 4K @ 60FPS")
        self.setMinimumWidth(700)

        self._meta = meta
        self._values = [int(v) for v in values]
        self._trace = trace
        self._n_value = int(n_value) if n_value else len(self._values)
        self._dist_kind = dist_kind
        self._worker: Optional[ExportWorker] = None
        self._result: Optional[ExportResult] = None
        self._ffmpeg_ready = False

        self._settings = QSettings("SortingVisualizerUltimate", "Export")
        self._build_ui(style, palette)
        self._restore_settings()
        self._refresh_toolchain()
        self._refresh_estimate()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self, style: str, palette: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        self.lbl_tool = QLabel("—")
        self.lbl_tool.setFont(mono_ui_font(9))
        self.lbl_tool.setWordWrap(True)
        root.addWidget(self.lbl_tool)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # ---- 左列：画面 --------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(8)
        body.addLayout(left, 1)

        gfx = QGroupBox("画面")
        gf = QFormLayout(gfx)
        gf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gf.setSpacing(6)

        self.combo_res = QComboBox()
        for key, label, _w, _h in RESOLUTIONS:
            self.combo_res.addItem(label, key)
        self.combo_res.currentIndexChanged.connect(self._refresh_estimate)
        gf.addRow("分辨率", self.combo_res)

        self.combo_fps = QComboBox()
        for f in FPS_CHOICES:
            self.combo_fps.addItem(f"{f} FPS", f)
        self.combo_fps.setCurrentIndex(
            max(0, list(FPS_CHOICES).index(60) if 60 in FPS_CHOICES else 0))
        self.combo_fps.currentIndexChanged.connect(self._refresh_estimate)
        gf.addRow("帧率", self.combo_fps)

        dur_row = QHBoxLayout()
        dur_row.setSpacing(6)
        self.combo_dur = QComboBox()
        self.combo_dur.setEditable(True)
        for d in DURATION_PRESETS:
            self.combo_dur.addItem(f"{d} 秒", d)
        self.combo_dur.setCurrentText("15 秒")
        self.combo_dur.currentTextChanged.connect(self._on_duration_text)
        dur_row.addWidget(self.combo_dur, 1)
        self.combo_ease = QComboBox()
        for key, label in EASINGS:
            self.combo_ease.addItem(label, key)
        dur_row.addWidget(self.combo_ease, 1)
        gf.addRow("总时长 / 缓动", dur_row)

        hold_row = QHBoxLayout()
        hold_row.setSpacing(6)
        self.spin_head = QDoubleSpinBox()
        self.spin_head.setRange(0.0, 5.0)
        self.spin_head.setSingleStep(0.1)
        self.spin_head.setValue(0.6)
        self.spin_head.setSuffix(" s")
        hold_row.addWidget(QLabel("开头定格"))
        hold_row.addWidget(self.spin_head, 1)
        self.spin_tail = QDoubleSpinBox()
        self.spin_tail.setRange(0.0, 8.0)
        self.spin_tail.setSingleStep(0.1)
        self.spin_tail.setValue(1.5)
        self.spin_tail.setSuffix(" s")
        hold_row.addWidget(QLabel("扫光定格"))
        hold_row.addWidget(self.spin_tail, 1)
        gf.addRow("", hold_row)

        style_row = QHBoxLayout()
        style_row.setSpacing(6)
        self.combo_style = QComboBox()
        for key, label in STYLES:
            self.combo_style.addItem(label, key)
        idx = next((i for i, (k, _) in enumerate(STYLES) if k == style), 0)
        self.combo_style.setCurrentIndex(idx)
        style_row.addWidget(self.combo_style, 1)
        self.combo_pal = QComboBox()
        for key, label in PALETTES:
            self.combo_pal.addItem(label, key)
        pidx = next((i for i, (k, _) in enumerate(PALETTES) if k == palette), 2)
        self.combo_pal.setCurrentIndex(pidx)
        style_row.addWidget(self.combo_pal, 1)
        gf.addRow("视图 / 配色", style_row)

        self.chk_hud = QCheckBox("叠加 HUD 状态看板")
        self.chk_hud.setChecked(True)
        self.chk_bar = QCheckBox("叠加底部进度条")
        self.chk_bar.setChecked(True)
        self.spin_hot = QSpinBox()
        self.spin_hot.setRange(1, 128)
        self.spin_hot.setValue(16)
        self.spin_hot.setToolTip(
            "高速档一帧会推进上万条原子操作，只高亮最后一条会疯狂闪烁；\n"
            "聚合最近 K 条指令后画面会呈现连续的活动轨迹（1 = 与界面完全一致）。")
        hot_row = QHBoxLayout()
        hot_row.setSpacing(6)
        hot_row.addWidget(self.chk_hud)
        hot_row.addWidget(self.chk_bar)
        hot_row.addStretch(1)
        hot_row.addWidget(QLabel("高亮聚合"))
        hot_row.addWidget(self.spin_hot)
        gf.addRow("", hot_row)
        left.addWidget(gfx)

        # ---- 左列：音效 --------------------------------------------------
        snd = QGroupBox("音效")
        sf = QFormLayout(snd)
        sf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sf.setSpacing(6)
        self.chk_audio = QCheckBox("导出立体声 AAC 音轨")
        self.chk_audio.setChecked(True)
        sf.addRow("", self.chk_audio)
        self.combo_wave = QComboBox()
        for key, label in WAVEFORMS:
            self.combo_wave.addItem(label, key)
        sf.addRow("波形", self.combo_wave)
        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(20, 100)
        self.slider_vol.setValue(85)
        sf.addRow("音量", self.slider_vol)
        left.addWidget(snd)
        left.addStretch(1)

        # ---- 右列：编码与输出 --------------------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 1)

        enc = QGroupBox("编码")
        ef = QFormLayout(enc)
        ef.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ef.setSpacing(6)
        self.combo_enc = QComboBox()
        for key, label in ENCODER_CHOICES:
            self.combo_enc.addItem(label, key)
        ef.addRow("编码器", self.combo_enc)

        q_row = QHBoxLayout()
        q_row.setSpacing(6)
        self.spin_crf = QSpinBox()
        self.spin_crf.setRange(0, 51)
        self.spin_crf.setValue(18)
        self.spin_crf.setToolTip("数值越小越清晰、文件越大（x264 建议 16~23）")
        q_row.addWidget(QLabel("画质 CRF"))
        q_row.addWidget(self.spin_crf, 1)
        self.combo_preset = QComboBox()
        for p in ("ultrafast", "veryfast", "faster", "fast", "medium", "slow"):
            self.combo_preset.addItem(p, p)
        self.combo_preset.setCurrentText("medium")
        q_row.addWidget(QLabel("预设"))
        q_row.addWidget(self.combo_preset, 1)
        ef.addRow("", q_row)
        right.addWidget(enc)

        outf = QGroupBox("输出")
        ol = QVBoxLayout(outf)
        ol.setSpacing(6)
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.edit_out = QLineEdit()
        self.edit_out.setFont(mono_ui_font(9))
        path_row.addWidget(self.edit_out, 1)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._choose_output)
        path_row.addWidget(self.btn_browse)
        ol.addLayout(path_row)
        self.lbl_est = QLabel("—")
        self.lbl_est.setFont(mono_ui_font(9))
        self.lbl_est.setWordWrap(True)
        ol.addWidget(self.lbl_est)
        right.addWidget(outf)

        # ---- 进度 --------------------------------------------------------
        prog = QGroupBox("进度")
        pl = QVBoxLayout(prog)
        pl.setSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        pl.addWidget(self.bar)
        self.lbl_prog = QLabel("待开始")
        self.lbl_prog.setFont(mono_ui_font(9))
        pl.addWidget(self.lbl_prog)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_ui_font(9))
        self.log.setMaximumBlockCount(400)
        self.log.setPlaceholderText("导出日志…")
        self.log.setFixedHeight(110)
        pl.addWidget(self.log)
        right.addWidget(prog, 1)

        # ---- 底部按钮 ----------------------------------------------------
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_open_dir = QPushButton("打开所在文件夹")
        self.btn_open_dir.setEnabled(False)
        self.btn_open_dir.clicked.connect(self._open_output_dir)
        self.btn_start = QPushButton("🎬 开始导出")
        self.btn_start.setObjectName("Accent")
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel = QPushButton("取消导出")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        btns.addWidget(self.btn_open_dir)
        btns.addStretch(1)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        # 默认输出路径
        self.edit_out.setText(
            default_output_path(self._meta, self._current_settings()))

    # ------------------------------------------------------------------
    # 参数收集
    # ------------------------------------------------------------------
    def _duration(self) -> float:
        text = self.combo_dur.currentText().strip()
        digits = "".join(c for c in text if c.isdigit() or c == ".")
        try:
            return max(1.0, float(digits))
        except ValueError:
            return 15.0

    def _on_duration_text(self, _text: str) -> None:
        self._refresh_estimate()

    def _current_settings(self) -> ExportSettings:
        res = self.combo_res.currentData() or "1080p"
        st = ExportSettings.for_resolution(
            res,
            fps=int(self.combo_fps.currentData() or 60),
            duration=self._duration(),
            hold_head=float(self.spin_head.value()),
            hold_tail=float(self.spin_tail.value()),
            easing=self.combo_ease.currentData() or "ease_in_out",
            style=self.combo_style.currentData() or "bars",
            palette=self.combo_pal.currentData() or "rainbow",
            audio=bool(self.chk_audio.isChecked()),
            waveform=self.combo_wave.currentData() or "sine",
            volume=self.slider_vol.value() / 100.0,
            show_hud=bool(self.chk_hud.isChecked()),
            show_progress=bool(self.chk_bar.isChecked()),
            hot_window=int(self.spin_hot.value()),
            encoder=self.combo_enc.currentData() or "auto",
            crf=int(self.spin_crf.value()),
            preset=self.combo_preset.currentText() or "medium",
        )
        st.output = self.edit_out.text().strip()
        return st

    # ------------------------------------------------------------------
    # 环境探测与预估
    # ------------------------------------------------------------------
    def _refresh_toolchain(self) -> None:
        rep = ffmpeg_report()
        self._ffmpeg_ready = bool(rep["available"]) and bool(rep["encoders"])
        if rep["available"]:
            text = f"FFmpeg：{rep['path']}\n{rep['version']}\n可用编码器：" \
                   f"{'、'.join(rep['encoders']) or '（无 H.264 编码器）'}"
            if not rep["encoders"]:
                text += f"\n⚠ {rep['note']}"
        else:
            text = f"⚠ FFmpeg 不可用：{rep['note']}"
        self.lbl_tool.setText(text)
        color = "#00E676" if self._ffmpeg_ready else "#FF2A55"
        self.lbl_tool.setStyleSheet(f"color: {color};")
        self.btn_start.setEnabled(self._ffmpeg_ready)
        if not self._ffmpeg_ready:
            self.log.appendPlainText("[!] 未检测到可用的 FFmpeg，导出按钮已禁用。")

    def _refresh_estimate(self) -> None:
        try:
            st = self._current_settings()
        except Exception:                                      # pragma: no cover
            return
        total = int(self._trace.n_ops) if self._trace is not None else 0
        anim = max(0.0, st.duration_exact - st.hold_head - st.hold_tail)
        notes: List[str] = []
        if total == 0:
            notes.append("⚠ 当前还没有可回放的指令流（先让算法录制完再导出）")
        if st.hold_head + st.hold_tail >= st.duration:
            notes.append("⚠ 首尾定格已占满全片，请加长总时长或减小定格")
        if st.frames > 24000:
            notes.append("提示：帧数超过 2.4 万，导出会比较久")
        self.lbl_est.setText(
            f"{st.width}×{st.height} @ {st.fps}FPS · 共 {st.frames} 帧 · "
            f"精确时长 {st.duration_exact:.3f}s\n"
            f"排序动画 {anim:.2f}s  |  开头定格 {st.hold_head:.2f}s  "
            f"|  扫光定格 {st.hold_tail:.2f}s\n"
            f"指令流 {total:,} 步 · 平均每帧推进 {total / max(1, st.frames):,.0f} 步"
            f" · {st.easing}"
            + ("\n" + "；".join(notes) if notes else ""))

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _choose_output(self) -> None:
        st = self._current_settings()
        start = st.output or default_output_path(self._meta, st)
        path, _flt = QFileDialog.getSaveFileName(
            self, "选择输出视频文件", start, "MP4 视频 (*.mp4);;所有文件 (*)")
        if path:
            if not path.lower().endswith((".mp4", ".mkv", ".mov")):
                path += ".mp4"
            self.edit_out.setText(path)
            self._refresh_estimate()

    def _open_output_dir(self) -> None:
        target = self._result.output if self._result else self.edit_out.text()
        if not target:
            return
        folder = Path(target).expanduser().resolve().parent
        try:
            if os.name == "nt":
                os.startfile(str(folder))                      # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:                               # pragma: no cover
            QMessageBox.warning(self, "打开失败", str(exc))

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if self._trace is None or self._trace.n_ops == 0:
            QMessageBox.warning(self, "无法导出",
                                "当前没有可回放的指令流。\n"
                                "请先在主窗口选择算法并等待录制完成。")
            return
        st = self._current_settings()
        if not st.output:
            st.output = default_output_path(self._meta, st)
            self.edit_out.setText(st.output)
        problems = st.validate()
        if problems:
            QMessageBox.warning(self, "参数不合法", "\n".join("• " + p for p in problems))
            return
        out = Path(st.output).expanduser()
        if out.exists() and QMessageBox.question(
                self, "文件已存在", f"{out.name} 已存在，要覆盖吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return

        self._save_settings(st)
        self._result = None
        self.log.clear()
        self.bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.btn_open_dir.setEnabled(False)
        self.lbl_prog.setText("正在启动…")
        self._log(f"→ {st.label()}")
        self._log(f"→ 视图 {st.style} / 配色 {st.palette} / 编码器 {st.encoder}")
        self._log(f"→ 输出 {st.output}")

        self._worker = ExportWorker(
            self._meta, self._values, self._trace, st,
            n_value=self._n_value, dist_kind=self._dist_kind, parent=self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_thread_done)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._log("… 正在取消（等待 FFmpeg 退出）")
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _on_progress(self, prog: ExportProgress) -> None:
        self.bar.setValue(int(min(1000, max(0, prog.percent * 10))))
        parts: List[str] = []
        if prog.stage == "render" and prog.frames:
            parts.append(f"{prog.frame}/{prog.frames} 帧")
            parts.append(f"{prog.fps:5.1f} 帧/秒")
            if prog.eta > 0:
                parts.append(f"剩余约 {prog.eta:5.1f}s")
        self.lbl_prog.setText((prog.message or " ".join(parts)) or "…")
        if prog.stage == "audio" and prog.frame % 128 == 0:
            self._log(f"  音轨 {prog.percent:5.1f}%")

    def _on_finished(self, result: ExportResult) -> None:
        self._result = result
        self.bar.setValue(1000)
        self.lbl_prog.setText("完成" if not result.cancelled else "已取消")
        self._log("")
        for line in result.summary().splitlines():
            self._log(line)
        if result.log:
            tail = [ln for ln in result.log.splitlines() if ln.strip()][-6:]
            for ln in tail:
                self._log("  ffmpeg | " + ln)
        self.btn_open_dir.setEnabled(not result.cancelled
                                     and Path(result.output).is_file())
        if not result.cancelled:
            self._log("提示：视频可直接拖进剪映 / PR，或上传到 B 站、YouTube。")

    def _on_failed(self, message: str) -> None:
        self.bar.setValue(0)
        self.lbl_prog.setText("失败")
        self._log("")
        for line in message.splitlines():
            self._log("✗ " + line)
        QMessageBox.critical(self, "导出失败", message[:1200])

    def _on_thread_done(self) -> None:
        self.btn_start.setEnabled(self._ffmpeg_ready)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self._worker = None

    # ------------------------------------------------------------------
    # 参数持久化
    # ------------------------------------------------------------------
    def _save_settings(self, st: ExportSettings) -> None:
        s = self._settings
        s.setValue("res", st.resolution_key)
        s.setValue("fps", st.fps)
        s.setValue("duration", st.duration)
        s.setValue("easing", st.easing)
        s.setValue("hold_head", st.hold_head)
        s.setValue("hold_tail", st.hold_tail)
        s.setValue("style", st.style)
        s.setValue("palette", st.palette)
        s.setValue("audio", st.audio)
        s.setValue("waveform", st.waveform)
        s.setValue("volume", int(round(st.volume * 100)))
        s.setValue("hud", st.show_hud)
        s.setValue("bar", st.show_progress)
        s.setValue("hot_window", st.hot_window)
        s.setValue("encoder", st.encoder)
        s.setValue("crf", st.crf)
        s.setValue("preset", st.preset)
        s.setValue("out_dir", str(Path(st.output).parent))
        s.sync()

    def _restore_settings(self) -> None:
        s = self._settings
        if not s.contains("fps"):
            return
        res = str(s.value("res", "1080p"))
        idx = next((i for i, (k, _l, _w, _h) in enumerate(RESOLUTIONS)
                    if k == res), 0)
        self.combo_res.setCurrentIndex(idx)
        fps = int(s.value("fps", 60))
        self.combo_fps.setCurrentIndex(
            max(0, list(FPS_CHOICES).index(fps) if fps in FPS_CHOICES else 1))
        self.combo_dur.setCurrentText(f"{float(s.value('duration', 15)):g} 秒")
        ease = str(s.value("easing", "ease_in_out"))
        eidx = next((i for i, (k, _l) in enumerate(EASINGS) if k == ease), 1)
        self.combo_ease.setCurrentIndex(eidx)
        self.spin_head.setValue(float(s.value("hold_head", 0.6)))
        self.spin_tail.setValue(float(s.value("hold_tail", 1.5)))
        st_key = str(s.value("style", "bars"))
        self.combo_style.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(STYLES) if k == st_key), 0))
        pal = str(s.value("palette", "rainbow"))
        self.combo_pal.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(PALETTES) if k == pal), 2))
        self.chk_audio.setChecked(bool(s.value("audio", True, type=bool)))
        wf = str(s.value("waveform", "sine"))
        self.combo_wave.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(WAVEFORMS) if k == wf), 0))
        self.slider_vol.setValue(int(s.value("volume", 85)))
        self.chk_hud.setChecked(bool(s.value("hud", True, type=bool)))
        self.chk_bar.setChecked(bool(s.value("bar", True, type=bool)))
        self.spin_hot.setValue(int(s.value("hot_window", 16)))
        enc = str(s.value("encoder", "auto"))
        self.combo_enc.setCurrentIndex(
            next((i for i, (k, _l) in enumerate(ENCODER_CHOICES) if k == enc), 0))
        self.spin_crf.setValue(int(s.value("crf", 18)))
        preset = str(s.value("preset", "medium"))
        if self.combo_preset.findText(preset) >= 0:
            self.combo_preset.setCurrentText(preset)
        out_dir = str(s.value("out_dir", "") or "")
        if out_dir:
            self.edit_out.setText(default_output_path(
                self._meta, self._current_settings()).replace(
                    str(Path(default_output_path(self._meta,
                                                 self._current_settings())).parent),
                    out_dir))

    def shutdown(self) -> None:
        """静默中止导出并等待线程退出（供主窗口退出时调用，不弹确认框）。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(8000)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:                       # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            if QMessageBox.question(
                    self, "正在导出", "导出尚未完成，确定要中止并关闭吗？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                event.ignore()
                return
            self.shutdown()
        event.accept()

    def refresh_source(self, *, meta, values: Sequence[int], trace: Trace,
                       n_value: Optional[int], dist_kind: str) -> None:
        """主窗口换了算法 / 数据量后同步刷新（不重置用户已调好的参数）。"""
        self._meta = meta
        self._values = [int(v) for v in values]
        self._trace = trace
        self._n_value = int(n_value) if n_value else len(self._values)
        self._dist_kind = dist_kind
        cur = Path(self.edit_out.text() or ".")
        new_default = Path(default_output_path(meta, self._current_settings()))
        if not self.edit_out.text() or cur.parent.name == "exports":
            self.edit_out.setText(str(new_default))
        self._refresh_estimate()
        QTimer.singleShot(0, self._refresh_estimate)
