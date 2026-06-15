"""波形显示模块 - 使用 pyqtgraph 显示 USB 麦克风波形（梅尔刻度）"""

import subprocess
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False


# ============================================================
# BG Audio Card USB 设备识别
# ============================================================

# USB VID/PID
BG_USB_VID = "1234"
BG_USB_PID = "1234"


def find_bg_audio_device_index():
    """通过 USB VID/PID 查找 BG Audio Card 的音频输入设备索引

    1. 用 PowerShell 查找 USB VID/PID 对应的设备名称
    2. 在 sounddevice 中匹配该名称的输入设备
    """
    if not HAS_SOUNDDEVICE:
        return None

    # 方法1: 通过 USB VID/PID 查找设备名称
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             f"Get-PnpDevice | Where-Object {{ $_.InstanceId -like '*VID_{BG_USB_VID}&PID_{BG_USB_PID}*' -and $_.Status -eq 'OK' }} | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=5
        )
        usb_names = [n.strip() for n in result.stdout.strip().split('\n') if n.strip()]
    except Exception:
        usb_names = []

    # 方法2: 回退到名称匹配
    name_keywords = ["bg card", "bg audio"]

    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                name_lower = dev['name'].lower()
                # 优先匹配 USB VID/PID 找到的设备名
                for usb_name in usb_names:
                    if usb_name.lower() in name_lower or name_lower in usb_name.lower():
                        return i
                # 回退: 名称关键词匹配
                for kw in name_keywords:
                    if kw in name_lower:
                        return i
    except Exception:
        pass

    return None


# ============================================================
# 梅尔刻度工具函数
# ============================================================

def hz_to_mel(hz):
    """Hz 转梅尔刻度"""
    return 2595.0 * np.log10(1.0 + hz / 700.0)

def mel_to_hz(mel):
    """梅尔刻度转 Hz"""
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


class MelAxisItem(pg.AxisItem):
    """梅尔刻度轴 - 内部用梅尔值，显示 Hz 标签"""

    def tickStrings(self, values, scale, spacing):
        return [f"{mel_to_hz(v):.0f}" for v in values]


class AudioCaptureThread(QThread):
    """音频采集线程 - 使用 sounddevice 从 BG Audio Card 采集"""
    data_ready = pyqtSignal(np.ndarray, np.ndarray)  # left, right
    error = pyqtSignal(str)

    SAMPLE_RATE = 48000
    BLOCK_SIZE = 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._device_index = None
        self._stream = None

    def find_device(self):
        """查找 BG Audio Card 设备，返回是否找到"""
        idx = find_bg_audio_device_index()
        if idx is not None:
            self._device_index = idx
            return True
        return False

    @staticmethod
    def list_input_devices():
        """列出所有输入设备"""
        if not HAS_SOUNDDEVICE:
            return []
        devices = []
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    devices.append((i, dev['name'], dev['max_input_channels']))
        except Exception:
            pass
        return devices

    def run(self):
        if not HAS_SOUNDDEVICE:
            self.error.emit("sounddevice 未安装")
            return
        self._running = True
        try:
            if self._device_index is None:
                self.find_device()

            dev_info = sd.query_devices(self._device_index)
            channels = min(dev_info['max_input_channels'], 2)

            with sd.InputStream(
                device=self._device_index,
                channels=channels,
                samplerate=self.SAMPLE_RATE,
                blocksize=self.BLOCK_SIZE,
                dtype='float32',
            ) as stream:
                while self._running:
                    data, overflowed = stream.read(self.BLOCK_SIZE)
                    if not self._running:
                        break

                    audio = np.array(data, dtype=np.float32)

                    if channels >= 2:
                        left = audio[:, 0]
                        right = audio[:, 1]
                    else:
                        left = audio[:, 0]
                        right = audio[:, 0]

                    self.data_ready.emit(left, right)

        except Exception as e:
            if self._running:
                self.error.emit(str(e))

    def stop(self):
        self._running = False
        self.wait(2000)


class WaveformDisplay(pg.PlotWidget):
    """实时波形显示控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_plot()
        self._data_l = np.zeros(1024)
        self._data_r = np.zeros(1024)
        self._init_curves()

    def _setup_plot(self):
        self.setBackground(QColor("#0d1117"))
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("left", "幅度")
        self.setLabel("bottom", "采样点")
        self.setYRange(-1.0, 1.0)
        self.setXRange(0, 1024)

        zero_line = pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen(color="#333", width=1, style=Qt.DashLine)
        )
        self.addItem(zero_line)

        self.getAxis("left").setPen(pg.mkPen("#555"))
        self.getAxis("bottom").setPen(pg.mkPen("#555"))
        self.getAxis("left").setTextPen(pg.mkPen("#888"))
        self.getAxis("bottom").setTextPen(pg.mkPen("#888"))

    def _init_curves(self):
        self._curve_l = self.plot(pen=pg.mkPen(color="#00ff88", width=1.5), name="L")
        self._curve_r = self.plot(pen=pg.mkPen(color="#4a90d9", width=1.5), name="R")

    def update_data(self, data_l, data_r=None):
        if isinstance(data_l, np.ndarray):
            self._data_l = data_l
        else:
            self._data_l = np.array(data_l)

        if data_r is not None:
            if isinstance(data_r, np.ndarray):
                self._data_r = data_r
            else:
                self._data_r = np.array(data_r)
            self._curve_r.setData(self._data_r)
        else:
            self._curve_r.setData(np.zeros_like(self._data_l))

        self._curve_l.setData(self._data_l)


class SpectrumDisplay(pg.PlotWidget):
    """频谱显示控件（梅尔刻度 X 轴）"""

    def __init__(self, parent=None):
        self._mel_axis = MelAxisItem(orientation='bottom')
        super().__init__(parent, axisItems={'bottom': self._mel_axis})
        self._setup_plot()
        self._init_curve()

    def _setup_plot(self):
        self.setBackground(QColor("#0d1117"))
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("left", "幅度 (dB)")
        self.setLabel("bottom", "频率 (Hz)")
        self.setYRange(-80, 0)
        mel_min = hz_to_mel(20)
        mel_max = hz_to_mel(20000)
        self.setXRange(mel_min, mel_max)

        self.getAxis("left").setPen(pg.mkPen("#555"))
        self.getAxis("bottom").setPen(pg.mkPen("#555"))
        self.getAxis("left").setTextPen(pg.mkPen("#888"))
        self.getAxis("bottom").setTextPen(pg.mkPen("#888"))

    def _init_curve(self):
        self._curve = self.plot(
            pen=pg.mkPen(color="#f39c12", width=1.5),
            fillLevel=-80,
            fillBrush=pg.mkBrush(243, 156, 18, 40),
            name="Spectrum"
        )

    def update_data(self, frequencies, magnitudes):
        """更新频谱数据（频率 Hz 自动转为梅尔刻度）"""
        mels = hz_to_mel(frequencies)
        self._curve.setData(mels, magnitudes)
