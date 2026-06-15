"""自定义调音台控件"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QDial, QGroupBox, QCheckBox, QFrame,
    QSizePolicy, QGridLayout, QComboBox, QSpinBox,
    QScrollArea, QDoubleSpinBox, QRadioButton, QButtonGroup,
    QLineEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRectF
from PyQt5.QtGui import QFont, QColor, QPalette, QPainter, QPen, QBrush, QPainterPath

import pyqtgraph as pg


# ============================================================
# 混音器控件
# ============================================================

class Fader(QWidget):
    """垂直推子控件"""
    valueChanged = pyqtSignal(int)

    def __init__(self, label: str = "", min_val: int = 0, max_val: int = 100,
                 default: int = 75, parent=None):
        super().__init__(parent)
        self._label = label
        self._min = min_val
        self._max = max_val
        self._value = default
        self._muted = False
        self.setFixedWidth(64)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)

        self.name_label = QLabel(self._label)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #E0E0E0;")
        layout.addWidget(self.name_label)

        self.value_label = QLabel(str(self._value))
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedHeight(20)
        self.value_label.setStyleSheet(
            "background-color: #1a1a2e; color: #00ff88; "
            "border: 1px solid #333; border-radius: 3px; font-size: 12px;"
        )
        layout.addWidget(self.value_label)

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(self._min, self._max)
        self.slider.setValue(self._value)
        self.slider.setTickPosition(QSlider.TicksBothSides)
        self.slider.setTickInterval(10)
        self.slider.setMinimumHeight(140)
        self.slider.setStyleSheet(self._slider_style())
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider, 1)

        self.mute_btn = QPushButton("M")
        self.mute_btn.setFixedSize(28, 22)
        self.mute_btn.setCheckable(True)
        self.mute_btn.setStyleSheet(
            "QPushButton { background-color: #2d2d44; color: #aaa; border: 1px solid #444; border-radius: 3px; font-size: 10px; }"
            "QPushButton:checked { background-color: #e74c3c; color: white; }"
            "QPushButton:hover { border-color: #666; }"
        )
        self.mute_btn.clicked.connect(self._on_mute)
        layout.addWidget(self.mute_btn, 0, Qt.AlignCenter)

    def _slider_style(self):
        return """
            QSlider::groove:vertical {
                background: #1a1a2e; width: 8px; border-radius: 4px;
            }
            QSlider::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a90d9, stop:1 #357abd);
                width: 24px; height: 14px; margin: -8px -8px;
                border-radius: 3px; border: 1px solid #2c5f9e;
            }
            QSlider::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5aa0e9, stop:1 #458acd);
            }
            QSlider::add-page:vertical {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2e86c1, stop:1 #1a5276);
                border-radius: 4px;
            }
        """

    def _on_slider_changed(self, val):
        self._value = val
        self.value_label.setText(str(val))
        self.valueChanged.emit(val)

    def _on_mute(self, checked):
        self._muted = checked
        if checked:
            self.slider.setEnabled(False)
            self.value_label.setStyleSheet(
                "background-color: #1a1a2e; color: #e74c3c; "
                "border: 1px solid #e74c3c; border-radius: 3px; font-size: 12px;"
            )
        else:
            self.slider.setEnabled(True)
            self.value_label.setStyleSheet(
                "background-color: #1a1a2e; color: #00ff88; "
                "border: 1px solid #333; border-radius: 3px; font-size: 12px;"
            )
            # 解除静音时重新发送当前音量
            self.valueChanged.emit(self._value)

    def value(self):
        return self._value

    def setValue(self, val):
        self._value = val
        self.slider.setValue(val)

    def is_muted(self):
        return self._muted


class ChannelStrip(QGroupBox):
    """通道条"""
    volumeChanged = pyqtSignal(str, int)
    muteChanged = pyqtSignal(str, bool)

    def __init__(self, channel: str, label: str, color: str = "#4a90d9", parent=None):
        super().__init__(parent)
        self.channel = channel
        self._color = color
        self.setTitle("")
        self.setFixedWidth(76)
        self.setStyleSheet(f"""
            QGroupBox {{
                background-color: #16213e; border: 1px solid {color};
                border-radius: 6px; margin-top: 2px; padding-top: 8px;
            }}
        """)
        self._setup_ui(label, color)

    def _setup_ui(self, label, color):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(3)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {color};")
        layout.addWidget(lbl)

        self.fader = Fader(label, 0, 100, 75)
        self.fader.valueChanged.connect(lambda v: self.volumeChanged.emit(self.channel, v))
        self.fader.mute_btn.clicked.connect(
            lambda c: self.muteChanged.emit(self.channel, self.fader.is_muted())
        )
        layout.addWidget(self.fader)

    def set_volume(self, val):
        self.fader.setValue(val)

    def set_mute(self, muted):
        self.fader.mute_btn.setChecked(muted)
        self.fader._on_mute(muted)


class VUMeter(QWidget):
    """VU 表控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level_l = 0.0
        self._level_r = 0.0
        self._peak_l = 0.0
        self._peak_r = 0.0
        self.setFixedSize(30, 160)

    def set_levels(self, left: float, right: float):
        self._level_l = max(0.0, min(1.0, left))
        self._level_r = max(0.0, min(1.0, right))
        self._peak_l = max(self._peak_l, self._level_l)
        self._peak_r = max(self._peak_r, self._level_r)
        self.update()

    def decay_peak(self):
        self._peak_l *= 0.95
        self._peak_r *= 0.95
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        bar_w = 10
        margin = 3
        bar_h = h - 10
        painter.fillRect(self.rect(), QColor("#0d1117"))
        x_l = margin
        self._draw_bar(painter, x_l, bar_w, bar_h, self._level_l, self._peak_l)
        x_r = w - margin - bar_w
        self._draw_bar(painter, x_r, bar_w, bar_h, self._level_r, self._peak_r)
        painter.end()

    def _draw_bar(self, painter, x, bar_w, bar_h, level, peak):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1a1a2e"))
        painter.drawRoundedRect(x, 5, bar_w, bar_h, 2, 2)
        fill_h = int(bar_h * level)
        if fill_h > 0:
            if level < 0.6:
                color = QColor("#27ae60")
            elif level < 0.85:
                color = QColor("#f39c12")
            else:
                color = QColor("#e74c3c")
            painter.setBrush(color)
            painter.drawRoundedRect(x, 5 + bar_h - fill_h, bar_w, fill_h, 2, 2)
        peak_y = 5 + bar_h - int(bar_h * peak)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(x, peak_y, x + bar_w, peak_y)


# ============================================================
# 音效面板控件 (DRC + Reverb，参考 APP FxControlActivity)
# ============================================================

class VerticalSlider(QWidget):
    """竖向滑块控件，模拟 APP 的 VerticalSeekBar"""
    valueChanged = pyqtSignal(int)

    def __init__(self, label: str, min_val: int, max_val: int, default: int,
                 unit: str = "", color: str = "#4a90d9", parent=None):
        super().__init__(parent)
        self._label = label
        self._unit = unit
        self._color = color
        self.setFixedWidth(72)
        self._setup_ui(min_val, max_val, default)

    def _setup_ui(self, min_val, max_val, default):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)

        # 标签
        lbl = QLabel(self._label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"font-size: 10px; color: {self._color}; font-weight: bold;")
        layout.addWidget(lbl)

        # 数值
        self.val_label = QLabel(str(default))
        self.val_label.setAlignment(Qt.AlignCenter)
        self.val_label.setFixedHeight(18)
        self.val_label.setStyleSheet(
            "background-color: #1a1a2e; color: #00ff88; "
            "border: 1px solid #333; border-radius: 2px; font-size: 10px;"
        )
        layout.addWidget(self.val_label)

        # 滑块
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(min_val, max_val)
        self.slider.setValue(default)
        self.slider.setMinimumHeight(120)
        self.slider.setStyleSheet(f"""
            QSlider::groove:vertical {{
                background: #1a1a2e; width: 6px; border-radius: 3px;
            }}
            QSlider::handle:vertical {{
                background: {self._color}; width: 20px; height: 12px;
                margin: -7px -7px; border-radius: 3px;
            }}
            QSlider::add-page:vertical {{
                background: {self._color}; border-radius: 3px; opacity: 0.5;
            }}
        """)
        self.slider.valueChanged.connect(self._on_changed)
        layout.addWidget(self.slider, 1)

        # 单位
        if self._unit:
            unit_lbl = QLabel(self._unit)
            unit_lbl.setAlignment(Qt.AlignCenter)
            unit_lbl.setStyleSheet("font-size: 9px; color: #666;")
            layout.addWidget(unit_lbl)

    def _on_changed(self, val):
        self.val_label.setText(str(val))
        self.valueChanged.emit(val)

    def value(self):
        return self.slider.value()

    def setValue(self, val):
        self.slider.setValue(val)


class FxPanel(QWidget):
    """音效面板：DRC + Reverb（参考 APP FxControlActivity）"""

    # DRC 参数
    drcThresholdChanged = pyqtSignal(int)     # -60 ~ 0 dB
    drcRatioChanged = pyqtSignal(int)         # 1 ~ 20 (x10)
    drcAttackChanged = pyqtSignal(int)        # 1 ~ 500 ms
    drcReleaseChanged = pyqtSignal(int)       # 10 ~ 2000 ms

    # Reverb 参数
    reverbRoomSizeChanged = pyqtSignal(int)   # 0 ~ 100
    reverbDampingChanged = pyqtSignal(int)    # 0 ~ 100
    reverbWetChanged = pyqtSignal(int)        # 0 ~ 100

    saveClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 保存按钮
        save_btn = QPushButton("保存音效设置")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #2e86c1; color: white; border-radius: 4px; padding: 8px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        save_btn.clicked.connect(self.saveClicked.emit)
        layout.addWidget(save_btn)

        # DRC 区域
        drc_group = QGroupBox("DRC 压缩器")
        drc_group.setStyleSheet(self._group_style("#e74c3c"))
        drc_layout = QHBoxLayout(drc_group)
        drc_layout.setSpacing(8)

        self.drc_threshold = VerticalSlider("阈值", -60, 0, -30, "dB", "#e74c3c")
        self.drc_threshold.valueChanged.connect(self.drcThresholdChanged.emit)
        drc_layout.addWidget(self.drc_threshold)

        self.drc_ratio = VerticalSlider("比率", 10, 200, 100, "x0.1", "#e67e22")
        self.drc_ratio.valueChanged.connect(self.drcRatioChanged.emit)
        drc_layout.addWidget(self.drc_ratio)

        self.drc_attack = VerticalSlider("启动", 1, 500, 100, "ms", "#f39c12")
        self.drc_attack.valueChanged.connect(self.drcAttackChanged.emit)
        drc_layout.addWidget(self.drc_attack)

        self.drc_release = VerticalSlider("释放", 10, 2000, 200, "ms", "#f1c40f")
        self.drc_release.valueChanged.connect(self.drcReleaseChanged.emit)
        drc_layout.addWidget(self.drc_release)

        layout.addWidget(drc_group)

        # Reverb 区域
        reverb_group = QGroupBox("混响")
        reverb_group.setStyleSheet(self._group_style("#3498db"))
        reverb_layout = QHBoxLayout(reverb_group)
        reverb_layout.setSpacing(8)

        self.reverb_room = VerticalSlider("房间", 0, 100, 50, "%", "#3498db")
        self.reverb_room.valueChanged.connect(self.reverbRoomSizeChanged.emit)
        reverb_layout.addWidget(self.reverb_room)

        self.reverb_damp = VerticalSlider("阻尼", 0, 100, 50, "%", "#2ecc71")
        self.reverb_damp.valueChanged.connect(self.reverbDampingChanged.emit)
        reverb_layout.addWidget(self.reverb_damp)

        self.reverb_wet = VerticalSlider("湿声", 0, 100, 30, "%", "#9b59b6")
        self.reverb_wet.valueChanged.connect(self.reverbWetChanged.emit)
        reverb_layout.addWidget(self.reverb_wet)

        reverb_layout.addStretch()
        layout.addWidget(reverb_group)

        layout.addStretch()

    def _group_style(self, color):
        return f"""
            QGroupBox {{
                background-color: #16213e; border: 1px solid {color};
                border-radius: 6px; margin-top: 12px; padding-top: 18px;
                font-weight: bold; color: {color}; font-size: 13px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }}
        """


# ============================================================
# 梅尔刻度工具函数
# ============================================================

def hz_to_mel(hz):
    """Hz 转梅尔刻度"""
    return 2595.0 * np.log10(1.0 + hz / 700.0)

def mel_to_hz(mel):
    """梅尔刻度转 Hz"""
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

def mel_space_freqs(f_min=20, f_max=20000, n=512):
    """生成梅尔刻度均匀分布的频率数组"""
    mel_min = hz_to_mel(f_min)
    mel_max = hz_to_mel(f_max)
    mels = np.linspace(mel_min, mel_max, n)
    return mel_to_hz(mels)


# ============================================================
# 均衡器面板 (参考 APP EqControlActivity)
# ============================================================

class MelAxisItem(pg.AxisItem):
    """梅尔刻度轴 - 内部用梅尔值，显示 Hz 标签"""

    def tickStrings(self, values, scale, spacing):
        return [f"{mel_to_hz(v):.0f}" for v in values]


class EqCurveView(pg.PlotWidget):
    """EQ 曲线绘制控件（梅尔刻度 X 轴，与 APP 算法一致）"""

    MIN_GAIN = -18.0
    MAX_GAIN = 18.0

    BAND_COLORS = [
        "#E91E63", "#F44336", "#FF9800", "#FFEB3B",
        "#4CAF50", "#00BCD4", "#2196F3", "#9C27B0",
        "#795548", "#607D8B"
    ]

    def __init__(self, parent=None):
        self._mel_axis = MelAxisItem(orientation='bottom')
        super().__init__(parent, axisItems={'bottom': self._mel_axis})
        self._bands = []
        self._curve = None
        self._band_curves = []
        self._band_points = []
        self._setup()

    def _setup(self):
        self.setBackground(QColor("#0d1117"))
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("left", "增益 (dB)")
        self.setLabel("bottom", "频率 (Hz)")
        self.setYRange(self.MIN_GAIN, self.MAX_GAIN)
        # 使用梅尔刻度作为 X 轴
        mel_min = hz_to_mel(20)
        mel_max = hz_to_mel(20000)
        self.setXRange(mel_min, mel_max)

        # 零线
        zero_line = pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen(color="#444", width=1, style=Qt.DashLine)
        )
        self.addItem(zero_line)

        self.getAxis("left").setPen(pg.mkPen("#555"))
        self.getAxis("bottom").setPen(pg.mkPen("#555"))
        self.getAxis("left").setTextPen(pg.mkPen("#888"))
        self.getAxis("bottom").setTextPen(pg.mkPen("#888"))

        # 总曲线
        self._curve = self.plot(
            pen=pg.mkPen(color="#4CAF50", width=2), name="Total"
        )

    def update_bands(self, bands: list):
        """更新 EQ 曲线（与 APP 算法一致）"""
        for c in self._band_curves:
            self.removeItem(c)
        self._band_curves.clear()
        for p in self._band_points:
            self.removeItem(p)
        self._band_points.clear()

        self._bands = bands
        # 使用梅尔刻度均匀分布的频率点（与 APP 的对数均匀分布等效）
        freqs = mel_space_freqs(20, 20000, 200)
        mels = hz_to_mel(freqs)

        total_response = np.zeros_like(freqs)

        for i, band in enumerate(bands):
            if not band.get("enable", True):
                continue
            response = self._compute_band_response(freqs, band)
            total_response += response

            # 单频段曲线
            color = self.BAND_COLORS[i % len(self.BAND_COLORS)]
            curve = self.plot(pen=pg.mkPen(color=color, width=1, style=Qt.DashLine))
            curve.setData(mels, response)
            self._band_curves.append(curve)

            # 频段控制点
            f0 = band.get("f0", 1000)
            gain = band.get("gain", 0.0)
            mel_f0 = hz_to_mel(f0)
            point = pg.ScatterPlotItem()
            point.addPoints([{'pos': (mel_f0, gain), 'size': 12, 'brush': color, 'pen': 'w'}])
            self.addItem(point)
            self._band_points.append(point)

        # 钳位总增益到 [-18, +18]
        total_response = np.clip(total_response, self.MIN_GAIN, self.MAX_GAIN)
        self._curve.setData(mels, total_response)

    def _compute_band_response(self, freqs, band):
        """计算单个频段的频率响应（与 APP EqCurveView 算法一致）

        APP 使用高斯近似而非标准 biquad 传递函数：
        - Peaking: exp(-(log10(f/f0) / (bandwidth*0.3))^2) * gain
        - Low Shelf: gain / (1 + (f/f0)^(2*Q))
        - High Shelf: gain / (1 + (f0/f)^(2*Q))
        - 其他类型回退到 Peaking
        """
        f0 = band.get("f0", 1000)
        Q = band.get("Q", 1.0)
        gain_db = band.get("gain", 0.0)
        filter_type = band.get("type", 0)

        if not band.get("enable", True) or abs(gain_db) < 0.01:
            return np.zeros_like(freqs)

        # 避免除零
        f0 = max(20, f0)
        Q = max(0.1, Q)

        try:
            if filter_type == 0:  # Peaking - 高斯近似
                ratio = freqs / f0
                log_ratio = np.log10(np.maximum(ratio, 1e-10))
                bandwidth = 1.0 / Q
                response = np.exp(-(log_ratio / (bandwidth * 0.3)) ** 2)
                return gain_db * response

            elif filter_type == 1:  # Low Shelf
                ratio = freqs / f0
                response = 1.0 / (1.0 + np.power(ratio, 2.0 * Q))
                return gain_db * response

            elif filter_type == 2:  # High Shelf
                ratio = f0 / freqs
                response = 1.0 / (1.0 + np.power(ratio, 2.0 * Q))
                return gain_db * response

            else:  # LP, HP, BP, Notch - 回退到 Peaking 高斯近似
                ratio = freqs / f0
                log_ratio = np.log10(np.maximum(ratio, 1e-10))
                bandwidth = 1.0 / Q
                response = np.exp(-(log_ratio / (bandwidth * 0.3)) ** 2)
                return gain_db * response

        except Exception:
            return np.zeros_like(freqs)


class EqBandControl(QGroupBox):
    """单个 EQ 频段控制（紧凑版，支持手动输入频率）"""
    changed = pyqtSignal()

    # 梅尔刻度范围
    MEL_MIN = hz_to_mel(20)
    MEL_MAX = hz_to_mel(20000)

    def __init__(self, band_idx: int, freq: int, parent=None):
        super().__init__(parent)
        self.band_idx = band_idx
        self._freq = freq
        self._updating = False
        self.setTitle(f"B{band_idx + 1}")
        self.setStyleSheet("""
            QGroupBox {
                background-color: #16213e; border: 1px solid #2d3a5e;
                border-radius: 4px; margin-top: 6px; padding-top: 10px;
                font-weight: bold; color: #aaa; font-size: 9px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 4px; padding: 0 2px; }
        """)
        self._setup_ui()

    def _hz_to_slider(self, hz):
        mel = hz_to_mel(max(20, min(20000, hz)))
        return int((mel - self.MEL_MIN) / (self.MEL_MAX - self.MEL_MIN) * 1000)

    def _slider_to_hz(self, val):
        mel = self.MEL_MIN + (val / 1000.0) * (self.MEL_MAX - self.MEL_MIN)
        return int(mel_to_hz(mel))

    def _setup_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        # 第1行：启用 + 类型
        self.enable_cb = QCheckBox("")
        self.enable_cb.setChecked(True)
        self.enable_cb.setFixedSize(16, 16)
        self.enable_cb.setStyleSheet("QCheckBox { spacing: 0; } QCheckBox::indicator { width: 14px; height: 14px; }")
        self.enable_cb.toggled.connect(lambda: self.changed.emit())
        layout.addWidget(self.enable_cb, 0, 0)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["PK", "LS", "HS", "LP", "HP", "BP", "NT"])
        self.type_combo.setFixedWidth(42)
        self.type_combo.setStyleSheet(
            "QComboBox { background-color: #1a1a2e; color: #E0E0E0; border: 1px solid #333; "
            "border-radius: 2px; padding: 1px 2px; font-size: 9px; }"
            "QComboBox QAbstractItemView { background-color: #1a1a2e; color: #E0E0E0; }"
        )
        self.type_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.type_combo, 0, 1)

        # 第2行：频率输入（可手动编辑）
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(self._freq)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.setStyleSheet(
            "background: #1a1a2e; color: #00ff88; border: 1px solid #333; "
            "border-radius: 2px; font-size: 9px; padding: 1px;"
        )
        self.freq_spin.valueChanged.connect(self._on_freq_spin)
        layout.addWidget(self.freq_spin, 1, 0, 1, 2)

        # 第3行：频率滑块（梅尔刻度）
        self.freq_slider = QSlider(Qt.Horizontal)
        self.freq_slider.setRange(0, 1000)
        self.freq_slider.setValue(self._hz_to_slider(self._freq))
        self.freq_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #1a1a2e; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #4a90d9; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
        """)
        self.freq_slider.valueChanged.connect(self._on_freq_slider)
        layout.addWidget(self.freq_slider, 2, 0, 1, 2)

        # 第4行：Q 值
        q_lbl = QLabel("Q")
        q_lbl.setStyleSheet("font-size: 9px; color: #888;")
        layout.addWidget(q_lbl, 3, 0)
        self.q_spin = QDoubleSpinBox()
        self.q_spin.setRange(0.1, 50.0)
        self.q_spin.setValue(1.0)
        self.q_spin.setSingleStep(0.1)
        self.q_spin.setDecimals(1)
        self.q_spin.setFixedWidth(52)
        self.q_spin.setStyleSheet(
            "background: #1a1a2e; color: #00ff88; border: 1px solid #333; "
            "border-radius: 2px; font-size: 9px; padding: 1px;"
        )
        self.q_spin.valueChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.q_spin, 3, 1)

        # 第5行：增益（支持手动输入，范围与 APP 一致 -12~+12 dB）
        gain_lbl = QLabel("dB")
        gain_lbl.setStyleSheet("font-size: 9px; color: #888;")
        layout.addWidget(gain_lbl, 4, 0)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-12.0, 12.0)
        self.gain_spin.setValue(0.0)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setFixedWidth(62)
        self.gain_spin.setStyleSheet(
            "background: #1a1a2e; color: #00ff88; border: 1px solid #333; "
            "border-radius: 2px; font-size: 9px; padding: 1px;"
        )
        self.gain_spin.valueChanged.connect(self._on_gain_spin)
        layout.addWidget(self.gain_spin, 4, 1)

        # 第6行：增益滑块（-120~120 映射到 -12.0~+12.0 dB）
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(-120, 120)
        self.gain_slider.setValue(0)
        self.gain_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #1a1a2e; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #4a90d9; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
        """)
        self.gain_slider.valueChanged.connect(self._on_gain_slider)
        layout.addWidget(self.gain_slider, 5, 0, 1, 2)

    def _on_freq_slider(self, val):
        if self._updating:
            return
        hz = self._slider_to_hz(val)
        self._freq = hz
        self._updating = True
        self.freq_spin.setValue(hz)
        self._updating = False
        self.changed.emit()

    def _on_freq_spin(self, val):
        if self._updating:
            return
        self._freq = val
        self._updating = True
        self.freq_slider.setValue(self._hz_to_slider(val))
        self._updating = False
        self.changed.emit()

    def _on_gain_slider(self, val):
        if self._updating:
            return
        db_val = val / 10.0
        self._updating = True
        self.gain_spin.setValue(db_val)
        self._updating = False
        self.changed.emit()

    def _on_gain_spin(self, val):
        if self._updating:
            return
        self._updating = True
        self.gain_slider.setValue(int(val * 10))
        self._updating = False
        self.changed.emit()

    def get_band_data(self):
        return {
            "f0": self._freq,
            "Q": self.q_spin.value(),
            "gain": self.gain_spin.value(),
            "type": self.type_combo.currentIndex(),
            "enable": self.enable_cb.isChecked(),
        }


class EqPanel(QWidget):
    """均衡器面板（3x4 网格布局，可滚动）"""

    bandChanged = pyqtSignal(int, dict)  # node_id, band_data
    nodeChanged = pyqtSignal(int)        # node_id
    saveClicked = pyqtSignal()

    # EQ 节点定义
    EQ_NODES = {
        4: "乐器L EQ",
        5: "乐器R EQ",
        6: "麦克风L EQ",
        7: "麦克风R EQ",
        14: "USB/BT EQ",
    }

    DEFAULT_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_node = 4
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶部：节点选择 + 保存
        header = QHBoxLayout()
        header.addWidget(QLabel("EQ 节点:"))
        self.node_combo = QComboBox()
        for nid, name in self.EQ_NODES.items():
            self.node_combo.addItem(name, nid)
        self.node_combo.currentIndexChanged.connect(self._on_node_changed)
        header.addWidget(self.node_combo)

        header.addStretch()

        save_btn = QPushButton("保存 EQ")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #2e86c1; color: white; border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        save_btn.clicked.connect(self.saveClicked.emit)
        header.addWidget(save_btn)

        layout.addLayout(header)

        # EQ 曲线
        self.curve_view = EqCurveView()
        self.curve_view.setFixedHeight(200)
        layout.addWidget(self.curve_view)

        # 频段控制区域（3x4 网格，可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        bands_widget = QWidget()
        bands_layout = QGridLayout(bands_widget)
        bands_layout.setContentsMargins(4, 4, 4, 4)
        bands_layout.setSpacing(4)

        self.band_controls = []
        cols = 3
        for i in range(10):
            bc = EqBandControl(i, self.DEFAULT_FREQS[i])
            bc.changed.connect(self._on_band_changed)
            self.band_controls.append(bc)
            row = i // cols
            col = i % cols
            bands_layout.addWidget(bc, row, col)

        # 最后一行拉伸
        bands_layout.setRowStretch((10 - 1) // cols + 1, 1)

        scroll.setWidget(bands_widget)
        layout.addWidget(scroll, 1)

        # 初始化曲线
        self._update_curve()

    def _on_node_changed(self, idx):
        nid = self.node_combo.currentData()
        if nid is not None:
            self._current_node = nid
            self.nodeChanged.emit(nid)

    def _on_band_changed(self):
        self._update_curve()
        # 发送当前频段数据
        for bc in self.band_controls:
            if bc == self.sender():
                self.bandChanged.emit(self._current_node, bc.get_band_data())
                break

    def _update_curve(self):
        bands = [bc.get_band_data() for bc in self.band_controls]
        self.curve_view.update_bands(bands)

    def current_node_id(self):
        return self._current_node


# ============================================================
# 系统设置面板
# ============================================================

class SystemPanel(QWidget):
    """系统设置面板"""

    lpChanged = pyqtSignal(bool)           # 低功耗开关
    lpTimeoutChanged = pyqtSignal(int)     # 低功耗超时
    modeMainClicked = pyqtSignal()
    modeSecondaryClicked = pyqtSignal()
    saveClicked = pyqtSignal()
    rebootClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # 低功耗设置
        lp_group = QGroupBox("低功耗设置")
        lp_group.setStyleSheet(self._group_style("#2ecc71"))
        lp_layout = QGridLayout(lp_group)

        self.lp_switch = QCheckBox("启用自动低功耗")
        self.lp_switch.setChecked(True)
        self.lp_switch.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.lp_switch.toggled.connect(self.lpChanged.emit)
        lp_layout.addWidget(self.lp_switch, 0, 0, 1, 2)

        lp_layout.addWidget(QLabel("空闲超时:"), 1, 0)
        self.lp_timeout = QSpinBox()
        self.lp_timeout.setRange(1, 60)
        self.lp_timeout.setValue(5)
        self.lp_timeout.setSuffix(" 分钟")
        self.lp_timeout.setStyleSheet("background: #1a1a2e; color: #00ff88; border: 1px solid #333;")
        self.lp_timeout.valueChanged.connect(self.lpTimeoutChanged.emit)
        lp_layout.addWidget(self.lp_timeout, 1, 1)

        layout.addWidget(lp_group)

        # 设备模式
        mode_group = QGroupBox("设备模式")
        mode_group.setStyleSheet(self._group_style("#3498db"))
        mode_layout = QVBoxLayout(mode_group)

        self.mode_main_btn = QRadioButton("主音箱 (Main)")
        self.mode_main_btn.setChecked(True)
        self.mode_main_btn.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.mode_main_btn.toggled.connect(lambda c: self.modeMainClicked.emit() if c else None)
        mode_layout.addWidget(self.mode_main_btn)

        self.mode_secondary_btn = QRadioButton("副音箱 (Secondary)")
        self.mode_secondary_btn.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.mode_secondary_btn.toggled.connect(lambda c: self.modeSecondaryClicked.emit() if c else None)
        mode_layout.addWidget(self.mode_secondary_btn)

        layout.addWidget(mode_group)

        # 参数管理
        param_group = QGroupBox("参数管理")
        param_group.setStyleSheet(self._group_style("#f39c12"))
        param_layout = QVBoxLayout(param_group)

        save_btn = QPushButton("保存所有参数")
        save_btn.clicked.connect(self.saveClicked.emit)
        param_layout.addWidget(save_btn)

        reboot_btn = QPushButton("重启设备")
        reboot_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; border-radius: 4px; padding: 8px; }"
            "QPushButton:hover { background-color: #e74c3c; }"
        )
        reboot_btn.clicked.connect(self.rebootClicked.emit)
        param_layout.addWidget(reboot_btn)

        layout.addWidget(param_group)

        # 语音识别设置
        from speech_to_text import SttSettingsPanel
        self.stt_settings = SttSettingsPanel()
        layout.addWidget(self.stt_settings)

        # 大语言模型设置
        from ai.llm_settings import LlmSettingsPanel
        self.llm_settings = LlmSettingsPanel()
        self.llm_settings.settingsChanged.connect(self._on_llm_settings_changed)
        layout.addWidget(self.llm_settings)

        # 智能家居设置
        from iot_control import HAS_MQTT, HAS_REQUESTS, HAS_BAN_IOT
        iot_group = QGroupBox("🏠 智能家居")
        iot_group.setStyleSheet(self._group_style("#9b59b6"))
        iot_layout = QGridLayout()

        # 控制方式
        iot_layout.addWidget(QLabel("控制方式:"), 0, 0)
        self.iot_mode_combo = QComboBox()
        self.iot_mode_combo.addItem("Ban-IOT (巴法云)", "ban_iot")
        self.iot_mode_combo.addItem("MQTT", "mqtt")
        self.iot_mode_combo.addItem("Home Assistant", "ha")
        if not HAS_BAN_IOT:
            self.iot_mode_combo.model().item(0).setEnabled(False)
            self.iot_mode_combo.setCurrentIndex(1)
        self.iot_mode_combo.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.iot_mode_combo, 0, 1)

        # Ban-IOT (巴法云) 设置
        iot_layout.addWidget(QLabel("巴法云 UID:"), 1, 0)
        self.bemfa_uid_edit = QLineEdit()
        self.bemfa_uid_edit.setPlaceholderText("巴法云私钥")
        self.bemfa_uid_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.bemfa_uid_edit, 1, 1)

        # MQTT 设置
        iot_layout.addWidget(QLabel("MQTT 地址:"), 2, 0)
        self.mqtt_host_edit = QLineEdit()
        self.mqtt_host_edit.setPlaceholderText("例如: 192.168.1.100")
        self.mqtt_host_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.mqtt_host_edit, 2, 1)

        iot_layout.addWidget(QLabel("MQTT 端口:"), 3, 0)
        self.mqtt_port_spin = QSpinBox()
        self.mqtt_port_spin.setRange(1, 65535)
        self.mqtt_port_spin.setValue(1883)
        self.mqtt_port_spin.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.mqtt_port_spin, 3, 1)

        iot_layout.addWidget(QLabel("MQTT 用户名:"), 4, 0)
        self.mqtt_user_edit = QLineEdit()
        self.mqtt_user_edit.setPlaceholderText("可选")
        self.mqtt_user_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.mqtt_user_edit, 4, 1)

        iot_layout.addWidget(QLabel("MQTT 密码:"), 5, 0)
        self.mqtt_pass_edit = QLineEdit()
        self.mqtt_pass_edit.setEchoMode(QLineEdit.Password)
        self.mqtt_pass_edit.setPlaceholderText("可选")
        self.mqtt_pass_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.mqtt_pass_edit, 5, 1)

        # Home Assistant 设置
        iot_layout.addWidget(QLabel("HA URL:"), 6, 0)
        self.ha_url_edit = QLineEdit()
        self.ha_url_edit.setPlaceholderText("例如: http://192.168.1.100:8123")
        self.ha_url_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.ha_url_edit, 6, 1)

        iot_layout.addWidget(QLabel("HA Token:"), 7, 0)
        self.ha_token_edit = QLineEdit()
        self.ha_token_edit.setEchoMode(QLineEdit.Password)
        self.ha_token_edit.setPlaceholderText("长期访问令牌")
        self.ha_token_edit.setStyleSheet("background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; padding: 4px;")
        iot_layout.addWidget(self.ha_token_edit, 7, 1)

        # 连接/断开按钮
        self.iot_connect_btn = QPushButton("连接")
        self.iot_connect_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        self.iot_connect_btn.clicked.connect(self._on_iot_connect)
        iot_layout.addWidget(self.iot_connect_btn, 8, 0, 1, 2)

        # 设备列表显示
        self.iot_device_list_lbl = QLabel("")
        self.iot_device_list_lbl.setStyleSheet("font-size: 10px; color: #bbb;")
        self.iot_device_list_lbl.setWordWrap(True)
        iot_layout.addWidget(self.iot_device_list_lbl, 9, 0, 1, 2)

        # 状态标签
        ban_iot_status = "✓" if HAS_BAN_IOT else "✗ 未安装"
        mqtt_status = "✓" if HAS_MQTT else "✗ 未安装"
        ha_status = "✓" if HAS_REQUESTS else "✗ 未安装"
        iot_hint = QLabel(f"BanIOT: {ban_iot_status} | MQTT: {mqtt_status} | HA: {ha_status}\n对AI说\"打开客厅灯\"即可控制")
        iot_hint.setStyleSheet("font-size: 10px; color: #888;")
        iot_layout.addWidget(iot_hint, 10, 0, 1, 2)

        iot_group.setLayout(iot_layout)
        layout.addWidget(iot_group)

        # AI 助手设置
        ai_group = QGroupBox("🤖 AI助手")
        ai_group.setStyleSheet(self._group_style("#e67e22"))
        ai_layout = QVBoxLayout()

        # 语音输入
        self.ai_voice_input_cb = QCheckBox("语音输入（说话识别后发给AI）")
        self.ai_voice_input_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.ai_voice_input_cb.setChecked(True)  # 默认开启
        self.ai_voice_input_cb.toggled.connect(self._on_ai_voice_input)
        ai_layout.addWidget(self.ai_voice_input_cb)

        # 唤醒词监听
        self.ai_wake_listen_cb = QCheckBox("唤醒词监听（持续监听，唤醒后自动对话）")
        self.ai_wake_listen_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.ai_wake_listen_cb.toggled.connect(self._on_ai_wake_listen)
        ai_layout.addWidget(self.ai_wake_listen_cb)

        # 语音闪避
        self.ai_ducking_cb = QCheckBox("语音闪避（说话时自动静音媒体）")
        self.ai_ducking_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.ai_ducking_cb.toggled.connect(self._on_ai_ducking)
        ai_layout.addWidget(self.ai_ducking_cb)

        # 语音输入（听写）
        self.ai_dictation_cb = QCheckBox("语音输入/听写（识别文字输出到光标处）")
        self.ai_dictation_cb.setStyleSheet("font-size: 12px; color: #E0E0E0;")
        self.ai_dictation_cb.toggled.connect(self._on_ai_dictation)
        ai_layout.addWidget(self.ai_dictation_cb)

        # 清空对话
        self.ai_clear_btn = QPushButton("清空对话记录")
        self.ai_clear_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; color: white; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background-color: #c0392b; }"
        )
        self.ai_clear_btn.clicked.connect(self._on_ai_clear_chat)
        ai_layout.addWidget(self.ai_clear_btn)

        ai_hint = QLabel("语音输入和唤醒词监听不可同时开启\n唤醒后说\"语音输入\"可切换到听写模式")
        ai_hint.setStyleSheet("font-size: 10px; color: #888;")
        ai_layout.addWidget(ai_hint)

        ai_group.setLayout(ai_layout)
        layout.addWidget(ai_group)

        # 加载 IoT 设置
        self._load_iot_settings()

        layout.addStretch()

    def _load_iot_settings(self):
        from PyQt5.QtCore import QSettings
        settings = QSettings("BanBox", "BGAICard")
        mode = settings.value("iot/mode", "ban_iot")
        idx = self.iot_mode_combo.findData(mode)
        if idx >= 0:
            self.iot_mode_combo.setCurrentIndex(idx)
        self.bemfa_uid_edit.setText(settings.value("ban_iot/uid", ""))
        self.mqtt_host_edit.setText(settings.value("iot/mqtt_host", ""))
        self.mqtt_port_spin.setValue(settings.value("iot/mqtt_port", 1883, type=int))
        self.mqtt_user_edit.setText(settings.value("iot/mqtt_user", ""))
        self.mqtt_pass_edit.setText(settings.value("iot/mqtt_pass", ""))
        self.ha_url_edit.setText(settings.value("iot/ha_url", ""))
        self.ha_token_edit.setText(settings.value("iot/ha_token", ""))

    def _on_iot_connect(self):
        from PyQt5.QtCore import QSettings
        settings = QSettings("BanBox", "BGAICard")
        mode = self.iot_mode_combo.currentData()

        # 保存设置
        settings.setValue("iot/mode", mode)
        settings.setValue("ban_iot/uid", self.bemfa_uid_edit.text())
        settings.setValue("iot/mqtt_host", self.mqtt_host_edit.text())
        settings.setValue("iot/mqtt_port", self.mqtt_port_spin.value())
        settings.setValue("iot/mqtt_user", self.mqtt_user_edit.text())
        settings.setValue("iot/mqtt_pass", self.mqtt_pass_edit.text())
        settings.setValue("iot/ha_url", self.ha_url_edit.text())
        settings.setValue("iot/ha_token", self.ha_token_edit.text())

        # 获取 AI 面板的 IoT 实例
        main_window = self.window()
        if not hasattr(main_window, 'ai_panel') or not hasattr(main_window.ai_panel, '_iot'):
            return

        iot = main_window.ai_panel._iot

        if mode == "ban_iot":
            uid = self.bemfa_uid_edit.text().strip()
            if not uid:
                self.iot_connect_btn.setText("请输入UID")
                return
            ban_iot = iot.get_ban_iot()
            if ban_iot is None:
                self.iot_connect_btn.setText("BanIOT不可用")
                return
            ban_iot.configure(uid)
            if ban_iot.connect():
                self.iot_connect_btn.setText("连接中...")
                self.iot_connect_btn.setStyleSheet(
                    "QPushButton { background-color: #f39c12; color: white; border-radius: 4px; padding: 6px; }"
                )
                # 延迟检查连接状态
                from PyQt5.QtCore import QTimer
                def check_ban_iot():
                    if ban_iot.is_connected():
                        self.iot_connect_btn.setText("已连接(巴法云)")
                        self.iot_connect_btn.setStyleSheet(
                            "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 6px; }"
                        )
                        # 显示设备列表
                        devices = ban_iot.get_devices()
                        if devices:
                            lines = [f"  {d['name']} ({d['type_label']}) - {d['topic']}" for d in devices]
                            self.iot_device_list_lbl.setText("已发现设备:\n" + "\n".join(lines))
                        else:
                            self.iot_device_list_lbl.setText("已连接，暂无设备")
                    else:
                        self.iot_connect_btn.setText("连接失败")
                        self.iot_connect_btn.setStyleSheet(
                            "QPushButton { background-color: #c0392b; color: white; border-radius: 4px; padding: 6px; }"
                        )
                QTimer.singleShot(5000, check_ban_iot)
        elif mode == "mqtt":
            host = self.mqtt_host_edit.text().strip()
            if not host:
                self.iot_connect_btn.setText("请输入地址")
                return
            port = self.mqtt_port_spin.value()
            user = self.mqtt_user_edit.text().strip() or None
            pwd = self.mqtt_pass_edit.text().strip() or None
            if iot.configure_mqtt(host, port, user, pwd):
                self.iot_connect_btn.setText("已连接")
                self.iot_connect_btn.setStyleSheet(
                    "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 6px; }"
                )
            else:
                self.iot_connect_btn.setText("连接失败")
        else:
            # HA 模式
            self.iot_connect_btn.setText("HA 已配置")
            self.iot_connect_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 6px; }"
            )

    def _group_style(self, color):
        return f"""
            QGroupBox {{
                background-color: #16213e; border: 1px solid {color};
                border-radius: 6px; margin-top: 12px; padding-top: 18px;
                font-weight: bold; color: {color}; font-size: 13px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }}
        """

    # ---- AI 助手设置回调 ----

    def _get_ai_panel(self):
        """获取 AI 助手面板实例"""
        main_window = self.window()
        if hasattr(main_window, 'ai_panel'):
            return main_window.ai_panel
        return None

    def _on_ai_voice_input(self, checked):
        """语音输入开关"""
        ai = self._get_ai_panel()
        if ai is None:
            return
        if checked:
            # 语音输入和唤醒词监听互斥
            self.ai_wake_listen_cb.setChecked(False)
            self.ai_dictation_cb.setChecked(False)
        ai.set_voice_input_enabled(checked)

    def _on_ai_wake_listen(self, checked):
        """唤醒词监听开关"""
        ai = self._get_ai_panel()
        if ai is None:
            return
        if checked:
            # 语音输入和唤醒词监听互斥
            self.ai_voice_input_cb.setChecked(False)
            self.ai_dictation_cb.setChecked(False)
        ai.set_wake_listening_enabled(checked)

    def _on_ai_ducking(self, checked):
        """语音闪避开关"""
        ai = self._get_ai_panel()
        if ai is None:
            return
        ai.set_ducking_enabled(checked)

    def _on_ai_dictation(self, checked):
        """语音输入/听写开关"""
        ai = self._get_ai_panel()
        if ai is None:
            return
        if checked:
            # 听写和语音输入/唤醒词监听互斥
            self.ai_voice_input_cb.setChecked(False)
            self.ai_wake_listen_cb.setChecked(False)
        ai.set_dictation_enabled(checked)

    def _on_ai_clear_chat(self):
        """清空对话记录"""
        ai = self._get_ai_panel()
        if ai is None:
            return
        ai._clear_chat()

    def _on_llm_settings_changed(self):
        """LLM 模型切换后通知 AI 面板"""
        ai = self._get_ai_panel()
        if ai is not None and hasattr(ai, "on_llm_model_changed"):
            ai.on_llm_model_changed()
