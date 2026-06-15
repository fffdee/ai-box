"""大语言模型引擎 - 多模型 + GPU 自动检测 + 工具调用"""

import gc
import os
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal, QSettings

try:
    from llama_cpp import Llama
    HAS_LLAMA = True
except ImportError:
    HAS_LLAMA = False

from ai.tools import ToolExecutor
from ai.llm_models import (
    DEFAULT_MODEL_ID, SETTINGS_KEY,
    get_model_path, get_model_info, is_model_downloaded,
)

# 向后兼容：默认内置模型路径
LLM_MODEL_PATH = get_model_path(DEFAULT_MODEL_ID)

SYSTEM_PROMPT_TEMPLATE = """你是BanBox智能音箱助手，名字叫小班。你擅长音频、音乐和DSP相关话题，也乐于闲聊。
回答简洁友好，不超过100字。如果用户要求你改名，请接受并使用新名字。

## 智能家居控制
当用户想要控制智能家居设备时，你必须返回JSON格式响应（纯JSON，不要多余文字）。

可用设备列表：
{device_list}

响应格式：
如果识别到控制设备的指令：
{{"action": "control", "topic": "设备话题", "msg": "on或off", "reply": "简短中文回复"}}

如果没有识别到有效指令：
{{"action": "none", "reply": "简短中文回复"}}

规则：
1. 打开/开启/启动 → msg为on
2. 关闭/关掉/停止 → msg为off
3. 根据设备名称匹配topic，找不到则action为none
4. reply用简短自然的中文，不超过20字
5. 只返回JSON，不要其他内容

如果只是闲聊不涉及设备控制，正常回复即可，不要输出JSON。

## 联网工具
当用户需要实时信息（天气、新闻、股价等）时，必须只输出一行JSON工具指令：
{{"tool": "web_search", "query": "搜索关键词"}}
示例：用户说"今天北京天气" → {{"tool": "web_search", "query": "今天北京天气"}}

## 音乐控制（联网播放，不占用显卡）
当用户要求播放/听歌时，必须只输出一行JSON：
{{"tool": "music_play", "keyword": "歌曲名或歌手"}}
示例：用户说"播放周杰伦的晴天" → {{"tool": "music_play", "keyword": "周杰伦 晴天"}}
暂停: {{"tool": "music_pause"}}
下一首: {{"tool": "music_next"}}
停止: {{"tool": "music_stop"}}

重要：涉及搜索或音乐时，先输出工具JSON（独占一行），不要先说话。工具执行后会再让你回复用户。"""

# 默认无设备时的 prompt
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(device_list="（未连接智能家居设备）")


def build_system_prompt(devices=None):
    """构建 system prompt，动态注入设备列表（与 Ban-IOT app 一致）

    devices: [{"topic": "xxx", "name": "客厅灯", "type_label": "灯泡"}, ...]
    """
    if not devices:
        return SYSTEM_PROMPT_TEMPLATE.format(device_list="（未连接智能家居设备）")

    lines = []
    for d in devices:
        topic = d.get("topic", "")
        name = d.get("name", topic)
        type_label = d.get("type_label", "设备")
        lines.append(f"- 名称: {name}, 话题: {topic}, 类型: {type_label}")
    device_list = "\n".join(lines)
    return SYSTEM_PROMPT_TEMPLATE.format(device_list=device_list)


def detect_gpu_layers() -> int:
    """检测 NVIDIA GPU，有则全部层 offload 到 GPU"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if result.returncode == 0:
            print("[LLM] 检测到 NVIDIA GPU，启用 CUDA 加速")
            return -1
    except Exception:
        pass
    print("[LLM] 未检测到 GPU，使用 CPU 推理")
    return 0


def get_selected_model_id() -> str:
    settings = QSettings("BanBox", "BGAICard")
    return settings.value(SETTINGS_KEY, DEFAULT_MODEL_ID)


class LLMThread(QThread):
    """大语言模型推理线程，支持多模型切换与工具调用"""

    token_generated = pyqtSignal(str)
    finished_response = pyqtSignal(str)
    error = pyqtSignal(str)
    tool_executed = pyqtSignal(str, str)
    model_loaded = pyqtSignal(str)  # model_id

    _shared_llm = None
    _current_model_id = None
    _gpu_layers = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages = []
        self._prompt = ""
        self._running = False
        self._model_id = DEFAULT_MODEL_ID
        self._tool_executor = ToolExecutor()

    @classmethod
    def unload_model(cls):
        cls._shared_llm = None
        cls._current_model_id = None
        gc.collect()

    @classmethod
    def load_model(cls, model_id=None):
        if model_id is None:
            model_id = get_selected_model_id()
        if not HAS_LLAMA:
            return False
        if not is_model_downloaded(model_id):
            print(f"[LLM] 模型未下载: {model_id}")
            return False

        if cls._shared_llm is not None and cls._current_model_id == model_id:
            return True

        if cls._shared_llm is not None:
            print(f"[LLM] 切换模型 {cls._current_model_id} -> {model_id}")
            cls.unload_model()

        info = get_model_info(model_id)
        model_path = get_model_path(model_id)

        try:
            if cls._gpu_layers is None:
                cls._gpu_layers = detect_gpu_layers()
            print(f"[LLM] 加载 {info['name']}: {model_path}, n_gpu_layers={cls._gpu_layers}")
            cls._shared_llm = Llama(
                model_path=model_path,
                n_ctx=info["n_ctx"],
                n_threads=4,
                n_gpu_layers=cls._gpu_layers,
                verbose=False,
            )
            cls._current_model_id = model_id
            print(f"[LLM] 模型加载成功: {info['name']}")
            return True
        except Exception as e:
            print(f"[LLM] 模型加载失败: {e}")
            if cls._gpu_layers == -1:
                print("[LLM] GPU 加载失败，回退 CPU")
                cls._gpu_layers = 0
                try:
                    cls._shared_llm = Llama(
                        model_path=model_path,
                        n_ctx=info["n_ctx"],
                        n_threads=4,
                        n_gpu_layers=0,
                        verbose=False,
                    )
                    cls._current_model_id = model_id
                    return True
                except Exception as e2:
                    print(f"[LLM] CPU 回退也失败: {e2}")
            cls.unload_model()
            return False

    def set_model_id(self, model_id):
        self._model_id = model_id or DEFAULT_MODEL_ID

    def set_prompt(self, prompt):
        self._prompt = prompt

    def set_messages(self, messages):
        self._messages = messages

    def _get_max_tokens(self):
        return get_model_info(self._model_id).get("max_tokens", 256)

    def _get_device_list(self):
        """从 IoT 模块获取设备列表，用于注入 system prompt"""
        try:
            # 尝试从父对象获取 IoT 实例
            iot = getattr(self.parent(), '_iot', None) if self.parent() else None
            if iot and hasattr(iot, 'get_ban_iot') and iot.get_ban_iot():
                ban_iot = iot.get_ban_iot()
                devices = ban_iot.get_devices()
                if devices:
                    return devices
        except Exception:
            pass
        return None

    def _stream_completion(self, messages):
        response = self._shared_llm.create_chat_completion(
            messages=messages,
            max_tokens=self._get_max_tokens(),
            temperature=0.7,
            top_p=0.9,
            stream=True,
        )
        full_text = ""
        for chunk in response:
            if not self._running:
                break
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                full_text += content
                self.token_generated.emit(content)
        return full_text

    def run(self):
        if not HAS_LLAMA:
            self.error.emit("llama-cpp-python 未安装")
            return

        self._model_id = self._model_id or get_selected_model_id()
        info = get_model_info(self._model_id)

        if not is_model_downloaded(self._model_id):
            self.error.emit(
                f"模型未下载: {info['name']}\n"
                f"请运行: python download_llm.py --model {self._model_id}"
            )
            return

        if not self.load_model(self._model_id):
            self.error.emit(f"模型加载失败: {info['name']}")
            return

        self.model_loaded.emit(self._model_id)
        self._running = True
        try:
            # 动态构建 system prompt（注入设备列表）
            devices = self._get_device_list()
            system_prompt = build_system_prompt(devices)
            messages = [{"role": "system", "content": system_prompt}] + self._messages
            messages.append({"role": "user", "content": self._prompt})

            full_text = self._stream_completion(messages)

            clean_text, tools = self._tool_executor.extract_tool_calls(full_text)

            # 小模型未输出工具JSON时，从用户原话推断意图
            if not tools:
                tools = self._tool_executor.detect_intent_from_user(self._prompt)

            if tools:
                tool_results = []
                for tool_obj in tools:
                    result = self._tool_executor.execute(tool_obj)
                    tool_name = tool_obj.get("tool", "unknown")
                    self.tool_executed.emit(tool_name, result)
                    tool_results.append(f"[{tool_name}] {result}")

                followup_messages = messages + [
                    {"role": "assistant", "content": full_text},
                    {"role": "user", "content": "工具执行结果：\n" + "\n".join(tool_results) + "\n请根据结果简短回复用户。"},
                ]
                self.token_generated.emit("\n")
                followup = self._stream_completion(followup_messages)
                full_text = clean_text + "\n" + followup if clean_text else followup
            else:
                full_text = clean_text or full_text

            self.finished_response.emit(full_text.strip())
        except Exception as e:
            self.error.emit(f"LLM 推理错误: {e}")
        finally:
            self._running = False

    def stop(self):
        self._running = False
        self.wait(5000)

    @classmethod
    def get_current_model_id(cls):
        return cls._current_model_id

    @classmethod
    def get_current_model_name(cls):
        if cls._current_model_id:
            return get_model_info(cls._current_model_id)["name"]
        return "未加载"
