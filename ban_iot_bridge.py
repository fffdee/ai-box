"""Ban-IOT 桥接模块 - 巴法云 TCP + 局域网 HTTP 控制

此模块是可选的，可裁剪。删除此文件后应用仍可正常运行。
用于接入用户自有的 Ban-IOT 智能家居系统。

通信协议：
- 云端：巴法云 TCP (bemfa.com:8344)
- 局域网：HTTP /control 接口
- 设备类型通过 Topic 后缀识别 (001=插座, 002=灯, 003=风扇, ...)
"""

import json
import socket
import threading
import time
import re
from PyQt5.QtCore import QObject, pyqtSignal, QSettings

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ============ 设备类型映射 ============

DEVICE_TYPE_MAP = {
    "001": ("plug", "插座"),
    "002": ("light", "灯泡"),
    "003": ("fan", "风扇"),
    "004": ("sensor", "传感器"),
    "005": ("ac", "空调"),
    "006": ("switch", "开关"),
    "009": ("curtain", "窗帘"),
    "010": ("custom", "自定义"),
    "052": ("temp_sensor", "温湿度传感器"),
    "099": ("universal", "通用设备"),
    "000": ("generic", "通用"),
}

# 中文设备名到 Topic 后缀的反向映射
DEVICE_NAME_TO_SUFFIX = {
    "插座": "001", "插头": "001",
    "灯": "002", "灯泡": "002", "灯光": "002",
    "风扇": "003",
    "传感器": "004",
    "空调": "005",
    "开关": "006",
    "窗帘": "009",
    "猫车": "010",
    "温湿度": "052", "温度": "052", "湿度": "052",
    "通用": "099",
}


class BanIOTBridge(QObject):
    """巴法云 IoT 桥接 - TCP 长连接 + 局域网 HTTP"""

    # 信号
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    message_received = pyqtSignal(str, str)  # topic, msg
    device_list_updated = pyqtSignal(list)    # 设备列表
    command_result = pyqtSignal(str, bool, str)  # topic, success, message
    log = pyqtSignal(str)  # 日志输出

    BEMFA_HOST = "bemfa.com"
    BEMFA_PORT = 8344
    BEMFA_IP = "119.91.109.180"  # 备用 IP
    HEARTBEAT_INTERVAL = 55  # 心跳间隔(秒)，与 Ban-IOT app 一致
    RECONNECT_DELAY = 5  # 重连延迟(秒)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._uid = ""
        self._sock = None
        self._connected = False
        self._running = False
        self._recv_thread = None
        self._heartbeat_thread = None
        self._subscribed_topics = []
        self._devices = []  # 设备列表缓存
        self._device_ips = {}  # topic -> ip 映射（局域网控制）

    def configure(self, uid):
        """配置巴法云 UID"""
        self._uid = uid.strip()
        if self._uid:
            QSettings("BanBox", "BGAICard").setValue("ban_iot/uid", self._uid)

    def get_uid(self):
        return self._uid

    def connect(self):
        """连接巴法云"""
        if not self._uid:
            self.log.emit("[BanIOT] 未配置 UID")
            return False
        if self._connected:
            return True

        self._running = True
        # 在后台线程连接
        t = threading.Thread(target=self._connect_worker, daemon=True)
        t.start()
        return True

    def disconnect(self):
        """断开连接"""
        self._running = False
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self.disconnected.emit()

    def is_connected(self):
        return self._connected

    def get_devices(self):
        """获取设备列表"""
        return list(self._devices)

    def set_device_ip(self, topic, ip):
        """设置设备的局域网 IP（优先局域网控制）"""
        self._device_ips[topic] = ip
        QSettings("BanBox", "BGAICard").setValue(f"ban_iot/ip/{topic}", ip)

    def _load_device_ips(self):
        """从设置加载设备 IP 映射"""
        settings = QSettings("BanBox", "BGAICard")
        settings.beginGroup("ban_iot/ip")
        for key in settings.childKeys():
            self._device_ips[key] = settings.value(key)
        settings.endGroup()

    def _connect_worker(self):
        """连接工作线程"""
        try:
            self.log.emit(f"[BanIOT] 连接 {self.BEMFA_HOST}:{self.BEMFA_PORT}...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((self.BEMFA_HOST, self.BEMFA_PORT))
            sock.settimeout(None)  # 阻塞模式
            self._sock = sock
            self._connected = True
            self.log.emit("[BanIOT] 已连接")
            self.connected.emit()

            # 订阅已保存的 topic
            for topic in self._subscribed_topics:
                self._send_subscribe(topic)

            # 启动接收线程
            self._recv_thread = threading.Thread(target=self._recv_worker, daemon=True)
            self._recv_thread.start()

            # 启动心跳线程
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
            self._heartbeat_thread.start()

            # 获取设备列表
            self._fetch_device_list()

        except socket.timeout:
            # 尝试备用 IP
            self.log.emit("[BanIOT] 主地址超时，尝试备用 IP...")
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((self.BEMFA_IP, self.BEMFA_PORT))
                sock.settimeout(None)
                self._sock = sock
                self._connected = True
                self.log.emit("[BanIOT] 已连接(备用IP)")
                self.connected.emit()
                for topic in self._subscribed_topics:
                    self._send_subscribe(topic)
                self._recv_thread = threading.Thread(target=self._recv_worker, daemon=True)
                self._recv_thread.start()
                self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
                self._heartbeat_thread.start()
                self._fetch_device_list()
            except Exception as e:
                self.log.emit(f"[BanIOT] 连接失败: {e}")
                self._connected = False
        except Exception as e:
            self.log.emit(f"[BanIOT] 连接失败: {e}")
            self._connected = False

    def _recv_worker(self):
        """接收消息工作线程"""
        buf = ""
        while self._running and self._connected:
            try:
                data = self._sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="ignore")

                # 按换行分割消息
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                    self._process_message(line.strip())

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log.emit(f"[BanIOT] 接收错误: {e}")
                break

        if self._connected:
            self._connected = False
            self.disconnected.emit()
            self.log.emit("[BanIOT] 连接断开")
            # 自动重连（与 Ban-IOT app 一致）
            if self._running:
                self.log.emit(f"[BanIOT] {self.RECONNECT_DELAY}秒后重连...")
                threading.Timer(self.RECONNECT_DELAY, self._reconnect).start()

    def _heartbeat_worker(self):
        """心跳保活"""
        while self._running and self._connected:
            time.sleep(self.HEARTBEAT_INTERVAL)
            if self._connected and self._sock:
                try:
                    self._sock.sendall(b"ping\r\n")
                except Exception:
                    break

    def _reconnect(self):
        """自动重连"""
        if not self._running or self._connected:
            return
        self.log.emit("[BanIOT] 正在重连...")
        self.connect()

    def _process_message(self, line):
        """处理收到的消息"""
        if not line or line == "ping":
            return

        # 解析消息: &topic=xxx&msg=yyy
        topic_match = re.search(r'topic=([^&\s]+)', line)
        msg_match = re.search(r'msg=([^&\s]*)', line)

        if topic_match:
            topic = topic_match.group(1)
            msg = msg_match.group(1) if msg_match else ""
            self.message_received.emit(topic, msg)
            self.log.emit(f"[BanIOT] 收到: {topic} -> {msg}")

    def _send_subscribe(self, topic):
        """订阅主题（加 /app 后缀，与 Ban-IOT app 一致）"""
        if self._connected and self._sock:
            # app 协议：topic 后加 /app 表示客户端订阅
            app_topic = topic + "/app"
            cmd = f"cmd=1&uid={self._uid}&topic={app_topic}\r\n"
            try:
                self._sock.sendall(cmd.encode("utf-8"))
                self.log.emit(f"[BanIOT] 订阅: {app_topic}")
            except Exception as e:
                self.log.emit(f"[BanIOT] 订阅失败: {e}")

    def publish(self, topic, msg):
        """发布消息（控制设备）"""
        if not self._connected or not self._sock:
            self.log.emit("[BanIOT] 未连接，无法发送")
            self.command_result.emit(topic, False, "未连接")
            return False

        cmd = f"cmd=2&uid={self._uid}&topic={topic}&msg={msg}\r\n"
        try:
            self._sock.sendall(cmd.encode("utf-8"))
            self.log.emit(f"[BanIOT] 发送: {topic} -> {msg}")
            self.command_result.emit(topic, True, f"{topic}: {msg}")
            return True
        except Exception as e:
            self.log.emit(f"[BanIOT] 发送失败: {e}")
            self.command_result.emit(topic, False, str(e))
            return False

    def control_local(self, topic, msg, ip=None):
        """局域网 HTTP 控制（优先）"""
        device_ip = ip or self._device_ips.get(topic)
        if not device_ip:
            return False

        try:
            url = f"http://{device_ip}/control"
            data = {"topic": topic, "msg": msg}
            resp = requests.post(url, json=data, timeout=3)
            if resp.status_code == 200:
                self.log.emit(f"[BanIOT] 局域网控制成功: {topic} -> {msg}")
                self.command_result.emit(topic, True, f"LAN: {topic}: {msg}")
                return True
            else:
                self.log.emit(f"[BanIOT] 局域网控制失败: {resp.status_code}")
                return False
        except Exception as e:
            self.log.emit(f"[BanIOT] 局域网控制失败: {e}")
            return False

    def control_device(self, topic, msg):
        """控制设备（优先局域网，回退云端）"""
        # 先尝试局域网
        if self.control_local(topic, msg):
            return True
        # 回退云端
        return self.publish(topic, msg)

    def _fetch_device_list(self):
        """从巴法云 API 获取设备列表"""
        if not HAS_REQUESTS or not self._uid:
            return

        try:
            url = f"http://apis.bemfa.com/vb/api/v2/allTopic"
            params = {"uid": self._uid}
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    topics = data.get("data", [])
                    self._devices = []
                    for t in topics:
                        topic_name = t.get("topic", "")
                        name = t.get("name", topic_name)
                        # 从 topic 后缀识别设备类型
                        suffix = topic_name[-3:] if len(topic_name) >= 3 else "000"
                        type_info = DEVICE_TYPE_MAP.get(suffix, ("unknown", "未知"))
                        self._devices.append({
                            "topic": topic_name,
                            "name": name,
                            "type_code": suffix,
                            "type_key": type_info[0],
                            "type_label": type_info[1],
                        })
                    self.device_list_updated.emit(self._devices)
                    self.log.emit(f"[BanIOT] 获取到 {len(self._devices)} 个设备")

                    # 自动订阅所有 topic
                    for dev in self._devices:
                        topic = dev["topic"]
                        if topic not in self._subscribed_topics:
                            self._subscribed_topics.append(topic)
                            self._send_subscribe(topic)
        except Exception as e:
            self.log.emit(f"[BanIOT] 获取设备列表失败: {e}")

    # ============ LLM 指令映射 ============

    def map_llm_command(self, iot_cmd):
        """将 LLM 输出的 IoT JSON 指令映射为 Ban-IOT 控制

        iot_cmd: {"device": "灯", "action": "on", "params": {"room": "客厅"}}
        返回: [(topic, msg), ...] 控制指令列表
        """
        device = iot_cmd.get("device", "")
        action = iot_cmd.get("action", "")
        params = iot_cmd.get("params", {})
        room = params.get("room", "")

        # 查找匹配的设备
        matched_devices = self._find_devices(device, room)

        if not matched_devices:
            # 没有找到匹配设备，尝试通过名称猜测 topic
            topic = self._guess_topic(device, room)
            if topic:
                msg = self._action_to_msg(action, params)
                return [(topic, msg)]
            return []

        results = []
        for dev in matched_devices:
            topic = dev["topic"]
            msg = self._action_to_msg(action, params, dev)
            results.append((topic, msg))

        return results

    def _find_devices(self, device_name, room=""):
        """查找匹配的设备"""
        results = []
        for dev in self._devices:
            # 匹配设备类型
            suffix = dev.get("type_code", "000")
            type_info = DEVICE_TYPE_MAP.get(suffix, ("unknown", "未知"))

            # 设备名匹配
            name_match = (
                device_name in dev.get("name", "") or
                device_name in type_info[1] or
                DEVICE_NAME_TO_SUFFIX.get(device_name) == suffix
            )

            # 房间匹配（如果指定了房间）
            room_match = not room or room in dev.get("name", "")

            if name_match and room_match:
                results.append(dev)

        return results

    def _guess_topic(self, device_name, room=""):
        """通过设备名猜测 topic"""
        suffix = DEVICE_NAME_TO_SUFFIX.get(device_name, "000")
        # 尝试构造 topic
        if room:
            pinyin_map = {
                "客厅": "living", "卧室": "bedroom", "书房": "study",
                "厨房": "kitchen", "浴室": "bathroom", "阳台": "balcony",
            }
            room_en = pinyin_map.get(room, room)
            return f"{room_en}_{device_name}{suffix}"
        return None

    def _action_to_msg(self, action, params, device=None):
        """将动作转换为消息"""
        dev_type = device.get("type_key", "generic") if device else "generic"

        if action in ("on", "off"):
            return action

        if action == "brightness":
            value = params.get("value", 50)
            return f"on"  # 简化处理，灯只有开/关

        if action == "temperature":
            value = params.get("value", 26)
            return f"on"  # 空调简化

        if action == "open":
            return "on"
        if action == "close":
            return "off"
        if action == "position":
            value = params.get("value", 50)
            return "on" if value > 50 else "off"

        # 通用设备驱动指令
        if action in ("fwd", "back", "stop"):
            return f"d0:{action}"

        if action == "angle":
            value = params.get("value", 90)
            return f"d0:angle={value}"

        return action


# ============ 模块可用性检测 ============

def is_ban_iot_available():
    """检测 Ban-IOT 模块是否可用"""
    import os
    bridge_file = os.path.join(os.path.dirname(__file__), "ban_iot_bridge.py")
    return os.path.exists(bridge_file)
