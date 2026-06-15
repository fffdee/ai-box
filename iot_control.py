"""智能家居 IoT 控制模块 - 支持 Ban-IOT / MQTT / Home Assistant

架构设计：
- IoTSmartHome 是统一入口，解析 LLM 输出的 JSON 指令
- 通过桥接器(Bridge)模式支持多种后端
- BanIOTBridge 是可选模块，删除 ban_iot_bridge.py 即可裁剪
"""

import json
import re
import threading
from PyQt5.QtCore import QObject, pyqtSignal

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# BanIOT 桥接器 - 可选，裁剪时删除 ban_iot_bridge.py 即可
try:
    from ban_iot_bridge import BanIOTBridge, is_ban_iot_available
    HAS_BAN_IOT = is_ban_iot_available()
except ImportError:
    HAS_BAN_IOT = False
    BanIOTBridge = None


class IoTSmartHome(QObject):
    """智能家居控制 - 解析 LLM 输出的 JSON 指令并执行

    支持三种后端（优先级从高到低）：
    1. BanIOT (巴法云) - 用户自有 IoT 系统，可裁剪
    2. MQTT - 通用物联网协议
    3. Home Assistant - 通过 REST API
    """

    command_executed = pyqtSignal(str, bool, str)  # device, success, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mqtt_client = None
        self._mqtt_connected = False

        # BanIOT 桥接器（可选）
        self._ban_iot = None
        if HAS_BAN_IOT:
            self._ban_iot = BanIOTBridge(self)
            self._ban_iot.command_result.connect(self._on_ban_iot_result)
            self._ban_iot.log.connect(self._on_ban_iot_log)
            # 加载保存的 UID
            from PyQt5.QtCore import QSettings
            settings = QSettings("BanBox", "BGAICard")
            uid = settings.value("ban_iot/uid", "")
            if uid:
                self._ban_iot.configure(uid)
            self._ban_iot._load_device_ips()

    def get_ban_iot(self):
        """获取 BanIOT 桥接器实例（供设置面板使用）"""
        return self._ban_iot

    def has_ban_iot(self):
        """BanIOT 模块是否可用"""
        return self._ban_iot is not None

    # ---- MQTT ----

    def configure_mqtt(self, host, port=1883, username=None, password=None):
        if not HAS_MQTT:
            print("[IoT] paho-mqtt 未安装")
            return False
        try:
            if self._mqtt_client is not None:
                self._mqtt_client.disconnect()
            self._mqtt_client = mqtt.Client(client_id="banbox-ai")
            if username:
                self._mqtt_client.username_pw_set(username, password)
            self._mqtt_client.on_connect = self._on_mqtt_connect
            self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self._mqtt_client.connect_async(host, port, 60)
            self._mqtt_client.loop_start()
            print(f"[IoT] MQTT 连接中: {host}:{port}")
            return True
        except Exception as e:
            print(f"[IoT] MQTT 连接失败: {e}")
            return False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        self._mqtt_connected = True
        print(f"[IoT] MQTT 已连接 (rc={rc})")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self._mqtt_connected = False

    def disconnect_mqtt(self):
        if self._mqtt_client is not None:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._mqtt_client = None
            self._mqtt_connected = False

    def is_mqtt_connected(self):
        return self._mqtt_connected

    # ---- 指令解析与执行 ----

    def parse_and_execute(self, llm_output):
        """解析 LLM 输出中的 IoT JSON 指令并执行

        支持两种格式（与 Ban-IOT app 兼容）：
        1. 新格式: {"action": "control", "topic": "xxx", "msg": "on/off", "reply": "回复"}
        2. 旧格式: {"iot": {"device": "灯", "action": "on", "params": {}}}

        返回: (clean_text, commands_found)
        """
        commands = self._extract_iot_commands(llm_output)
        if not commands:
            return llm_output, False

        for cmd in commands:
            self._execute_command(cmd)

        # 清理输出文本中的 JSON
        clean = llm_output
        for cmd_json in commands:
            json_str = json.dumps(cmd_json, ensure_ascii=False)
            clean = clean.replace(f"```json\n{json_str}\n```", "")
            clean = clean.replace(f"```{json_str}```", "")
            clean = clean.replace(json_str, "")
        clean = re.sub(r'```\n?', '', clean).strip()
        return clean, True

    def _extract_iot_commands(self, text):
        commands = []
        # ```json ... ``` 包裹
        json_blocks = re.findall(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        for block in json_blocks:
            cmd = self._parse_json_safe(block)
            if cmd and ("iot" in cmd or cmd.get("action") == "control"):
                commands.append(cmd)
        if commands:
            return commands
        # 裸 JSON - 新格式 {"action": "control", ...}
        for match in re.findall(r'\{[^{}]*"action"\s*:\s*"control"[^{}]*\}', text):
            cmd = self._parse_json_safe(match)
            if cmd:
                commands.append(cmd)
        if commands:
            return commands
        # 裸 JSON - 旧格式 {"iot": {...}}
        for match in re.findall(r'\{"iot"\s*:\s*\{[^}]*\}\s*\}', text):
            cmd = self._parse_json_safe(match)
            if cmd and "iot" in cmd:
                commands.append(cmd)
        return commands

    def _parse_json_safe(self, text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _execute_command(self, cmd):
        """执行 IoT 控制指令，支持新格式和旧格式"""
        # 新格式: {"action": "control", "topic": "xxx", "msg": "on/off", "reply": "回复"}
        if cmd.get("action") == "control" and cmd.get("topic"):
            topic = cmd["topic"]
            msg = cmd.get("msg", "on")
            reply = cmd.get("reply", "")
            print(f"[IoT] 执行指令: topic={topic}, msg={msg}, reply={reply}")
            thread = threading.Thread(
                target=self._execute_direct,
                args=(topic, msg),
                daemon=True,
            )
            thread.start()
            return

        # 旧格式: {"iot": {"device": "灯", "action": "on", "params": {}}}
        iot = cmd.get("iot", {})
        device = iot.get("device", "未知")
        action = iot.get("action", "")
        params = iot.get("params", {})
        print(f"[IoT] 执行指令: 设备={device}, 动作={action}, 参数={params}")

        thread = threading.Thread(
            target=self._execute_in_background,
            args=(device, action, params),
            daemon=True,
        )
        thread.start()

    def _execute_direct(self, topic, msg):
        """直接通过 topic+msg 控制设备（与 Ban-IOT app 一致）"""
        try:
            success = False

            # 优先 BanIOT
            if self._ban_iot and self._ban_iot.is_connected():
                success = self._ban_iot.control_device(topic, msg)

            # 回退 MQTT
            if not success and self._mqtt_connected and self._mqtt_client is not None:
                self._mqtt_client.publish(topic, msg)
                success = True

            # 回退 Home Assistant
            if not success:
                success = self._execute_http_direct(topic, msg)

            self.command_executed.emit(topic, success, f"{topic}: {msg}")
        except Exception as e:
            print(f"[IoT] 执行失败: {e}")
            self.command_executed.emit(topic, False, str(e))

    def _execute_http_direct(self, topic, msg):
        """通过 Home Assistant REST API 控制（从 topic 推断 entity）"""
        if not HAS_REQUESTS:
            return False
        from PyQt5.QtCore import QSettings
        settings = QSettings("BanBox", "BGAICard")
        ha_url = settings.value("iot/ha_url", "")
        ha_token = settings.value("iot/ha_token", "")
        if not ha_url:
            return False

        # 从 topic 后缀推断设备类型
        suffix = topic[-3:] if len(topic) >= 3 else "000"
        suffix_to_domain = {
            "001": "switch", "002": "light", "003": "fan",
            "005": "climate", "006": "switch", "009": "cover",
        }
        domain = suffix_to_domain.get(suffix, "light")
        entity_id = f"{domain}.{topic.replace('/', '_').lower()}"
        service = f"{domain}.turn_on" if msg == "on" else f"{domain}.turn_off"

        url = f"{ha_url}/api/services/{service}"
        headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
        data = {"entity_id": entity_id}

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _execute_in_background(self, device, action, params):
        try:
            success = False

            # 优先 BanIOT
            if self._ban_iot and self._ban_iot.is_connected():
                controls = self._ban_iot.map_llm_command({"device": device, "action": action, "params": params})
                if controls:
                    for topic, msg in controls:
                        success = self._ban_iot.control_device(topic, msg)
                else:
                    print(f"[IoT] BanIOT 未找到匹配设备: {device}")

            # 回退 MQTT
            if not success and self._mqtt_connected and self._mqtt_client is not None:
                success = self._execute_mqtt(device, action, params)

            # 回退 Home Assistant
            if not success:
                success = self._execute_http(device, action, params)

            msg = f"{device} {action}" + (f" {params}" if params else "")
            self.command_executed.emit(device, success, msg)
        except Exception as e:
            print(f"[IoT] 执行失败: {e}")
            self.command_executed.emit(device, False, str(e))

    def _on_ban_iot_result(self, topic, success, message):
        """BanIOT 执行结果"""
        self.command_executed.emit(topic, success, message)

    def _on_ban_iot_log(self, msg):
        """BanIOT 日志"""
        print(msg)

    # ---- MQTT 执行 ----

    def _execute_mqtt(self, device, action, params):
        room = params.get("room", "default")
        topic = f"banbox/iot/{device}/{room}"
        payload = {"device": device, "action": action, "params": params}
        result = self._mqtt_client.publish(topic, json.dumps(payload, ensure_ascii=False))
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    # ---- Home Assistant 执行 ----

    def _execute_http(self, device, action, params):
        if not HAS_REQUESTS:
            return False
        from PyQt5.QtCore import QSettings
        settings = QSettings("BanBox", "BGAICard")
        ha_url = settings.value("iot/ha_url", "")
        ha_token = settings.value("iot/ha_token", "")
        if not ha_url:
            return False

        entity_id = self._map_to_ha_entity(device, params)
        service = self._map_to_ha_service(device, action)
        if not entity_id or not service:
            return False

        url = f"{ha_url}/api/services/{service}"
        headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
        data = {"entity_id": entity_id}

        if action == "brightness" and "value" in params:
            data["brightness_pct"] = params["value"]
        elif action == "temperature" and "value" in params:
            data["temperature"] = params["value"]
        elif action == "color" and "color" in params:
            data["color_name"] = params["color"]
        elif action == "position" and "value" in params:
            data["position"] = params["value"]

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _map_to_ha_entity(self, device, params):
        room = params.get("room", "")
        room_map = {"客厅": "living_room", "卧室": "bedroom", "书房": "study",
                     "厨房": "kitchen", "卫生间": "bathroom", "阳台": "balcony"}
        device_map = {"灯": "light", "灯光": "light", "空调": "climate",
                      "窗帘": "cover", "开关": "switch", "插座": "switch", "传感器": "sensor"}
        room_en = room_map.get(room, room.lower() if room else "default")
        domain = device_map.get(device, "light")
        if domain == "climate":
            return f"climate.{room_en}"
        elif domain == "cover":
            return f"cover.{room_en}_curtain"
        elif domain == "sensor":
            return f"sensor.{room_en}_{params.get('type', 'temperature')}"
        return f"{domain}.{room_en}"

    def _map_to_ha_service(self, device, action):
        device_service_map = {"灯": "light", "灯光": "light", "空调": "climate",
                              "窗帘": "cover", "开关": "switch", "插座": "switch"}
        action_map = {"on": "turn_on", "off": "turn_off", "brightness": "turn_on",
                      "color": "turn_on", "temperature": "set_temperature",
                      "mode": "set_hvac_mode", "open": "open_cover",
                      "close": "close_cover", "position": "set_cover_position"}
        domain = device_service_map.get(device, "light")
        service_action = action_map.get(action, "turn_on")
        return f"{domain}.{service_action}"
