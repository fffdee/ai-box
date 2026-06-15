"""BanBox USB CDC 串口通信层"""

import serial
import serial.tools.list_ports
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QMutex


class SerialWorker(QThread):
    """后台线程读取串口数据"""
    data_received = pyqtSignal(str)
    raw_data_received = pyqtSignal(bytes)
    connection_lost = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial_port = None
        self._running = False
        self._mutex = QMutex()

    def set_port(self, serial_port):
        self.serial_port = serial_port

    def run(self):
        self._running = True
        buf = b""
        while self._running:
            if self.serial_port is None or not self.serial_port.is_open:
                self.msleep(50)
                continue
            try:
                data = self.serial_port.read(self.serial_port.in_waiting or 1)
                if data:
                    self.raw_data_received.emit(data)
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", errors="replace").rstrip("\r")
                        if text:
                            self.data_received.emit(text)
            except serial.SerialException:
                self.connection_lost.emit()
                break
            except OSError:
                self.connection_lost.emit()
                break

    def stop(self):
        self._running = False
        self.wait(2000)


class BanBoxSerial(QObject):
    """BanBox 设备串口通信管理"""

    response_received = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    # EQ 节点定义 (与 APP 一致)
    EQ_NODES = {
        4: "乐器L EQ",
        5: "乐器R EQ",
        6: "麦克风L EQ",
        7: "麦克风R EQ",
        14: "USB/BT EQ",
    }

    # EQ 默认频段频率
    EQ_DEFAULT_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    # 滤波器类型
    FILTER_TYPES = {
        0: "Peaking",
        1: "Low Shelf",
        2: "High Shelf",
        3: "Low Pass",
        4: "High Pass",
        5: "Band Pass",
        6: "Notch",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial_port = None
        self.worker = SerialWorker()
        self.worker.data_received.connect(self._on_data)
        self.worker.connection_lost.connect(self._on_connection_lost)
        self._connected = False
        self._response_buffer = []
        self._waiting_response = False
        self._collecting = False
        self._collected_lines = []

    @staticmethod
    def list_ports():
        """列出可用串口"""
        ports = serial.tools.list_ports.comports()
        return [(p.device, p.description) for p in ports]

    def connect(self, port_name: str) -> bool:
        """连接设备"""
        try:
            self.serial_port = serial.Serial(
                port=port_name,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )
            self.worker.set_port(self.serial_port)
            if not self.worker.isRunning():
                self.worker.start()
            self._connected = True
            self.connection_changed.emit(True)
            return True
        except serial.SerialException as e:
            self.error_occurred.emit(f"连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        self._connected = False
        self.worker.stop()
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.serial_port = None
        self.connection_changed.emit(False)

    def is_connected(self) -> bool:
        return self._connected

    def send_command(self, cmd: str, wait_response: bool = True):
        """发送文本命令"""
        if not self._connected or self.serial_port is None:
            return
        if not cmd.endswith("\r\n"):
            cmd += "\r\n"
        try:
            if wait_response:
                self._waiting_response = True
                self._collected_lines = []
                self._collecting = True
            self.serial_port.write(cmd.encode("utf-8"))
        except serial.SerialException as e:
            self.error_occurred.emit(f"发送失败: {e}")

    def send_command_and_collect(self, cmd: str, callback=None):
        """发送命令并收集多行响应"""
        if not self._connected or self.serial_port is None:
            return
        if not cmd.endswith("\r\n"):
            cmd += "\r\n"
        self._waiting_response = True
        self._collected_lines = []
        self._collecting = True
        self._collect_callback = callback
        try:
            self.serial_port.write(cmd.encode("utf-8"))
        except serial.SerialException as e:
            self.error_occurred.emit(f"发送失败: {e}")

    def _on_data(self, line: str):
        """处理接收到的数据行"""
        if line.strip() == "$" or line.strip().startswith("$ "):
            if self._collecting:
                self._collecting = False
                self._waiting_response = False
                if hasattr(self, "_collect_callback") and self._collect_callback:
                    self._collect_callback(self._collected_lines)
                self._collected_lines = []
            return

        if self._collecting:
            self._collected_lines.append(line)
        else:
            self.response_received.emit(line)

    def _on_connection_lost(self):
        self._connected = False
        self.connection_changed.emit(False)
        self.error_occurred.emit("连接已断开")

    # ---- 音频控制命令 ----

    def set_volume(self, channel: str, value: int):
        """设置通道音量 (0-100)"""
        self.send_command(f"audio -{channel} {value}", wait_response=False)

    def set_mute(self, mute: int):
        """设置静音 (0=关, 1=开)"""
        self.send_command(f"audio -m {mute}", wait_response=False)

    def save_audio(self):
        """保存音频参数"""
        self.send_command("audio -S", wait_response=False)

    # ---- 音效控制命令 (fx 命令，与 APP 一致) ----

    def fx_set(self, effect_id: int, param: str, value):
        """通过 fx 命令设置音效参数"""
        self.send_command(f"fx {effect_id} {param} {value}", wait_response=False)

    def fx_set_eq_band(self, effect_id: int, band_idx: int, gain_x10: int):
        """设置 EQ 频段增益 (gain_x10 = gain * 10)"""
        self.send_command(f"fx {effect_id} band{band_idx} {gain_x10}", wait_response=False)

    def fx_set_eq_band_type(self, effect_id: int, band_idx: int, filter_type: int):
        """设置 EQ 频段滤波器类型"""
        self.send_command(f"fx {effect_id} band{band_idx}_type {filter_type}", wait_response=False)

    def fx_set_eq_band_f0(self, effect_id: int, band_idx: int, freq: int):
        """设置 EQ 频段中心频率"""
        self.send_command(f"fx {effect_id} band{band_idx}_f0 {freq}", wait_response=False)

    def fx_set_eq_band_q(self, effect_id: int, band_idx: int, q_x100: int):
        """设置 EQ 频段 Q 值 (q_x100 = Q * 100)"""
        self.send_command(f"fx {effect_id} band{band_idx}_Q {q_x100}", wait_response=False)

    def fx_set_eq_band_enable(self, effect_id: int, band_idx: int, enable: int):
        """启用/禁用 EQ 频段"""
        self.send_command(f"fx {effect_id} band{band_idx}_enable {enable}", wait_response=False)

    def fx_query(self, effect_id: int, callback=None):
        """查询音效参数"""
        self.send_command_and_collect(f"param -q effect {effect_id}", callback)

    # ---- DRC 参数 (effect ID 10) ----

    def drc_set_threshold(self, value_db: float):
        """设置 DRC 阈值 (-60 ~ 0 dB)"""
        self.fx_set(10, "threshold", int(value_db * 100))

    def drc_set_ratio(self, ratio: float):
        """设置 DRC 比率 (1 ~ 20)"""
        self.fx_set(10, "ratio", int(ratio * 10))

    def drc_set_attack(self, ms: int):
        """设置 DRC 启动时间 (1 ~ 500 ms)"""
        self.fx_set(10, "attack", ms)

    def drc_set_release(self, ms: int):
        """设置 DRC 释放时间 (10 ~ 2000 ms)"""
        self.fx_set(10, "release", ms)

    # ---- Reverb 参数 (effect ID 12) ----

    def reverb_set_room_size(self, value: int):
        """设置混响房间大小 (0~100)"""
        self.fx_set(12, "room_size", value)

    def reverb_set_damping(self, value: int):
        """设置混响阻尼 (0~100)"""
        self.fx_set(12, "damping", value)

    def reverb_set_wet(self, value: int):
        """设置混响湿声 (0~100)"""
        self.fx_set(12, "wet", value)

    # ---- 系统命令 ----

    def sys_info(self, callback=None):
        """获取系统信息"""
        self.send_command_and_collect("sys -i", callback)

    def battery_value(self):
        """获取电池电量"""
        self.send_command("battery -v")

    # ---- 低功耗 ----

    def lp_set(self, on: bool):
        """设置低功耗开关"""
        self.send_command(f"lp {'on' if on else 'off'}", wait_response=False)

    def lp_timeout(self, minutes: int):
        """设置低功耗超时 (1~60 分钟)"""
        self.send_command(f"lp -t {minutes}", wait_response=False)

    # ---- 设备模式 ----

    def set_mode_main(self):
        """设置为主音箱模式"""
        self.send_command("mode main", wait_response=False)

    def set_mode_secondary(self):
        """设置为副音箱模式"""
        self.send_command("mode secondary", wait_response=False)

    # ---- 参数管理 ----

    def param_save(self, module: str = ""):
        """保存参数"""
        if module:
            self.send_command(f"param -s {module}", wait_response=False)
        else:
            self.send_command("param -s", wait_response=False)

    def param_load(self):
        """加载参数"""
        self.send_command("param -l", wait_response=False)

    def param_default(self):
        """恢复默认参数"""
        self.send_command("param -d", wait_response=False)

    def chain_save(self):
        """保存链路配置"""
        self.send_command("chain -S", wait_response=False)
