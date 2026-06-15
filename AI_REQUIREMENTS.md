# BGAICard - AI 语音助手模块需求文档

> 本文档面向 AI 开发者，描述 BGAICard 项目中 AI 语音助手子系统的完整功能需求、架构设计和接口规范。

---

## 1. 项目概述

BGAICard 是 BanBox 智能音箱的 Windows 上位机应用（PyQt5），其中 AI 语音助手模块提供语音交互、智能对话和智能家居控制能力。所有 AI 推理均在本地离线运行，不依赖云端 API。

### 核心能力

| 能力 | 引擎/模型 | 说明 |
|------|-----------|------|
| 语音识别 (STT) | Vosk / faster-whisper | 双引擎，Vosk 轻量中文，Whisper 支持中英混合 |
| 大语言模型 (LLM) | llama-cpp-python + Qwen2.5-1.5B-Instruct (Q4_K_M) | 离线推理，流式输出 |
| 语音合成 (TTS) | sherpa-onnx VITS (vits-zh-ll) | 中文语音合成，流式分段 |
| 智能家居 (IoT) | BanIOT(巴法云) / MQTT / Home Assistant | 三后端，BanIOT 可裁剪 |

---

## 2. 模块架构

```
┌─────────────────────────────────────────────────────────┐
│                    AIAssistantPanel                      │
│  (UI + 状态机 + 调度中心)                                │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ STT 线程  │→│ LLM 线程  │→│ TTS 线程  │→│ 播放线程 │ │
│  │(QThread)  │  │(QThread)  │  │(QThread)  │  │(QThread)│ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│       ↑                                     ↓            │
│  sounddevice 采集                    sounddevice 播出    │
│  (BG Audio Card 输入)               (BG Audio Card 输出) │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                      │
│  │ 语音闪避      │  │ IoT 控制     │                      │
│  │ (Ducking)    │  │ (IoTSmartHome)│                     │
│  │ 串口 set_mute│  │ BanIOT/MQTT/HA│                     │
│  └──────────────┘  └──────────────┘                      │
└─────────────────────────────────────────────────────────┘
```

### 文件结构

| 文件 | 职责 |
|------|------|
| `ai_assistant.py` | AI 助手面板 UI + 所有线程类 + 唤醒词状态机 + 语音闪避 + 听写 |
| `speech_to_text.py` | 独立的 STT 模块（波形面板使用，与 ai_assistant 中的副本独立） |
| `iot_control.py` | IoT 统一入口，解析 LLM JSON 指令，三后端执行 |
| `ban_iot_bridge.py` | 巴法云 TCP + 局域网 HTTP 桥接器（**可裁剪**） |
| `widgets.py` | 系统设置面板，包含 STT/LLM/IoT/AI 助手设置 |
| `serial_comm.py` | BanBox 串口通信，提供 `set_mute(0/1)` 接口 |
| `waveform.py` | 波形/频谱显示，提供 `find_bg_audio_device_index()` |

---

## 3. 功能需求详述

### 3.1 语音识别 (STT)

#### 双引擎

- **Vosk**：轻量级，仅中文，流式识别（KaldiRecognizer），延迟低
- **Whisper**：faster-whisper，支持中英混合，分段录音（5秒一段），带 VAD 静音过滤

#### 配置项（QSettings: `stt/` 前缀）

| Key | 默认值 | 说明 |
|-----|--------|------|
| `stt/engine` | `"vosk"` (如可用) | 引擎选择: `"vosk"` / `"whisper"` |
| `stt/whisper_model` | `"base"` | Whisper 模型: `"tiny"` / `"base"` / `"small"` |
| `stt/language` | `"auto"` | 语言: `"auto"` / `"zh"` / `"en"` |
| `stt/wake_word` | `"小班"` | 唤醒词 |
| `stt/wake_enabled` | `false` | 是否启用唤醒词 |
| `stt/wake_timeout` | `30` | 唤醒后对话窗口秒数 |
| `stt/wake_reply` | `"我在，请说"` | 唤醒回复语 |

#### 音频输入

- 采集设备：自动查找 `BG Audio Card` 输入设备（`find_bg_audio_device_index()`）
- 采样率：16000Hz，单声道，int16
- Whisper 静音阈值：RMS < 300 跳过

#### 唤醒词过滤机制

STT 线程内部有 `_is_wake_word_match(text)` 方法：
- `_bypass_wake_word = True`：不过滤，所有识别结果直接发送
- `_bypass_wake_word = False` + 唤醒词启用：只发送包含唤醒词的文本
- `_bypass_wake_word = False` + 唤醒词禁用：所有文本直接发送

---

### 3.2 唤醒词状态机

```
                    ┌─────────────┐
                    │  空闲/监听   │ ← 初始状态，STT 运行中
                    │ (wake_mode) │    唤醒词过滤开启
                    └──────┬──────┘
                           │ 检测到唤醒词
                           ↓
                    ┌─────────────┐
                    │   已唤醒     │ → 播放唤醒回复 TTS
                    │(activated)  │    停止旧 STT，重启为不过滤模式
                    └──────┬──────┘
                           │ 收到有效语音
                           ↓
                    ┌─────────────┐
                    │  LLM 对话   │ → 停止 STT，发给 LLM
                    │(generating) │    流式 TTS 朗读回复
                    └──────┬──────┘
                           │ LLM + TTS 完成
                           ↓
                    ┌─────────────┐
                    │  倒计时窗口  │ → 30秒倒计时 + 重启 STT
                    │ (countdown) │    不过滤模式（bypass=True）
                    └──────┬──────┘
                      ┌────┴────┐
                      │         │
               收到语音    超时(30s)
                      ↓         ↓
               发给 LLM    回到空闲/监听
               (重启流程)   (唤醒词过滤开启)
```

#### 关键状态变量

| 变量 | 类型 | 说明 |
|------|------|------|
| `_wake_mode` | bool | 是否在持续监听模式（用户开启） |
| `_wake_activated` | bool | 是否已被唤醒，处于对话窗口内 |
| `_wake_timer` | QTimer | 倒计时定时器（单次触发） |
| `_bypass_wake_word` | bool | STT 是否跳过唤醒词过滤 |
| `_pending_wake_countdown` | bool | LLM+TTS 完成后需要启动倒计时的标志 |

#### 倒计时重启机制

LLM 和 TTS 异步完成，倒计时必须在两者都完成后才启动：

1. `_on_llm_finished`：如果 `_is_playing=False`（TTS 已完成），直接启动倒计时；否则设置 `_pending_wake_countdown=True`
2. `_play_next`（TTS 播放队列清空时）：检查 `_pending_wake_countdown`，如果为 True 则启动倒计时
3. `_on_tts_error`：TTS 出错时也检查是否需要启动倒计时

#### 唤醒词后额外内容

如果唤醒词后面还有额外内容（如"小班你好"→"你好"），直接把额外内容发给 LLM，无需再等一轮对话。

#### "语音输入"命令

唤醒后说"语音输入"或"语音打字"，进入听写模式（见 3.5）。

---

### 3.3 大语言模型 (LLM)

#### 模型配置

- 引擎：`llama-cpp-python` v0.2.90（v0.3.29 有非法指令 bug）
- 模型：`qwen2.5-1.5b-instruct-q4_k_m.gguf`
- 上下文：`n_ctx=2048`，线程：`n_threads=4`
- 生成参数：`max_tokens=256`，`temperature=0.7`，`top_p=0.9`

#### System Prompt

```
你是BanBox智能音箱助手，名字叫小班。你擅长音频、音乐和DSP相关话题，也乐于闲聊。
回答简洁友好，不超过100字。如果用户要求你改名，请接受并使用新名字。

## 智能家居控制
当用户想要控制智能家居设备时，你必须输出JSON指令，格式如下：
{"iot": {"device": "设备名", "action": "动作", "params": {}}}

支持的设备和动作：
- 灯光: device="灯/灯光", action="on/off", params: {"room":"房间名"}
- 空调: device="空调", action="on/off", params: {"room":"房间名"}
- 窗帘: device="窗帘", action="on/off/open/close", params: {"room":"房间名"}
- 开关/插座: device="开关/插座", action="on/off", params: {"room":"房间名"}
- 风扇: device="风扇", action="on/off", params: {"room":"房间名"}
- 传感器: device="传感器", action="query", params: {"room":"房间名", "type":"温度/湿度"}

如果只是闲聊不涉及设备控制，正常回复即可，不要输出JSON。
如果涉及设备控制，先输出JSON指令（独占一行），然后简短回复确认。
```

#### 流式输出

- `stream=True`，逐 token 通过 `token_generated` 信号发送
- `_append_token` 方法实时更新聊天显示
- 检测句子结尾（`。！？；\n`）或累积超过 50 字符时，触发流式 TTS

#### 类级别共享

`LLMThread._shared_llm` 是类变量，模型只加载一次，所有线程共享。

---

### 3.4 语音合成 (TTS) 与流式播放

#### 模型配置

- 引擎：`sherpa-onnx`
- 模型：`vits-zh-ll`（中文 VITS）
- 路径：`tts-models/vits-zh-ll/model.onnx`

#### 流式 TTS 流程

```
LLM 生成 token → _append_token → 累积到句子结尾
                                      ↓
                              _speak_sentence(sentence)
                                      ↓
                              TTSThread.start() → 合成音频
                                      ↓
                      _on_sentence_audio_ready → _tts_queue.put(audio)
                                      ↓
                              _play_next → AudioPlayThread
                                      ↓
                              sd.play(blocking=True) → BG Audio Card 输出
                                      ↓
                              playback_finished → _play_next (下一段)
```

#### 播放队列

- `queue.Queue` 线程安全队列
- 多个 TTS 线程可同时合成，音频按完成顺序入队
- `_play_next` 串行播放，播放完一段自动取下一段
- 队列空时：`_is_playing = False`，检查是否需要启动倒计时

#### 音频输出设备

- 优先查找 `BG Audio Card` 输出设备（名称含 "BG"）
- 找不到时回退到系统默认输出

---

### 3.5 语音输入（听写模式）

#### 功能

识别到的文字通过剪贴板 + Ctrl+V 输出到当前鼠标光标位置。

#### 触发方式

1. 系统设置中开启"语音输入/听写"
2. 唤醒后说"语音输入"或"语音打字"

#### 实现

1. 将识别文字设置到系统剪贴板
2. 发送 Ctrl+V 按键（优先用 `pyautogui`，回退到 Windows API `keybd_event`）
3. 500ms 后恢复剪贴板原内容

#### 与其他模式互斥

语音输入、唤醒词监听、听写三者互斥，开启一个自动关闭其他。

---

### 3.6 语音闪避 (Ducking)

#### 功能

说话或 AI 朗读时，自动静音媒体播放；停止说话后延迟恢复。

#### 触发

- 用户说话：`_on_speech_partial` 检测到非静音片段 → `_duck_mute()`
- AI 朗读：`_play_next` 播放音频时 → `_duck_mute()`

#### 恢复

- 用户停止说话：`_on_speech_result` → `_duck_schedule_unmute(1500ms)`
- AI 朗读结束：`_play_next` 队列空 → `_duck_schedule_unmute(800ms)`

#### 串口控制

通过 `BanBoxSerial.set_mute(1)` 静音，`set_mute(0)` 恢复。串口协议：`audio -m 1\r\n` / `audio -m 0\r\n`。

---

### 3.7 智能家居控制 (IoT)

#### 架构：Bridge 模式

```
用户语音 → STT → LLM → JSON 指令 → IoTSmartHome.parse_and_execute()
                                              ↓
                                    ┌─────────┼─────────┐
                                    ↓         ↓         ↓
                                BanIOT     MQTT      Home Assistant
                               (优先)    (回退)      (回退)
```

#### LLM 输出 JSON 指令格式

```json
{"iot": {"device": "灯", "action": "on", "params": {"room": "客厅"}}}
```

#### 指令解析

`IoTSmartHome._extract_iot_commands(text)` 支持两种格式：
1. ` ```json ... ``` ` 代码块包裹
2. 裸 JSON `{"iot": {...}}`

解析后从 LLM 输出文本中移除 JSON，只保留自然语言回复。

#### 执行优先级

1. **BanIOT**（巴法云）：如果已连接，优先使用
2. **MQTT**：BanIOT 不可用时回退
3. **Home Assistant**：最后回退，通过 REST API

#### BanIOT（可裁剪模块）

- **云端**：巴法云 TCP 长连接（`bemfa.com:8344`），30 秒心跳
- **局域网**：HTTP `/control` 接口，低延迟
- **执行策略**：优先局域网 HTTP，回退云端 TCP
- **设备类型**：Topic 后缀编码（001=插座, 002=灯, 003=风扇, 004=传感器, 005=空调, 006=开关, 009=窗帘, 010=自定义, 052=温湿度传感器, 099=通用）
- **裁剪方式**：删除 `ban_iot_bridge.py` 即可，`iot_control.py` 通过 `try/except` 导入，`HAS_BAN_IOT = False` 时自动跳过

#### MQTT 执行

- Topic 格式：`banbox/iot/{device}/{room}`
- Payload：`{"device": "...", "action": "...", "params": {...}}`

#### Home Assistant 执行

- API：`POST {ha_url}/api/services/{domain}.{service}`
- 认证：`Bearer {ha_token}`
- 实体映射：`{domain}.{room_en}`（如 `light.living_room`）

---

### 3.8 AI 助手面板 UI

#### 输入栏（精简版）

| 控件 | 说明 |
|------|------|
| 🔊 按钮 (checkable) | 回复声音开关，checked=True 时 TTS 朗读 |
| 输入框 (QLineEdit) | 文字输入，Enter 发送 |
| 发送按钮 | 发送文字给 LLM |

#### 系统设置中的 AI 助手设置

| 控件 | 说明 |
|------|------|
| 语音输入 checkbox | 说话识别后发给 AI |
| 唤醒词监听 checkbox | 持续监听，唤醒后自动对话 |
| 语音闪避 checkbox | 说话时自动静音媒体 |
| 语音输入/听写 checkbox | 识别文字输出到光标处 |
| 清空对话记录按钮 | 清空聊天历史 |

---

## 4. 线程模型

| 线程类 | 基类 | 生命周期 | 信号 |
|--------|------|----------|------|
| `SpeechRecognizerThread` | QThread | 监听期间持续运行 | `text_result(str)`, `partial_result(str)`, `status_changed(str)`, `error(str)` |
| `LLMThread` | QThread | 单次推理 | `token_generated(str)`, `finished_response(str)`, `error(str)` |
| `TTSThread` | QThread | 单句合成 | `audio_ready(ndarray, int)`, `error(str)` |
| `AudioPlayThread` | QThread | 单段播放 | `playback_finished()`, `error(str)` |

#### 共享资源

- `LLMThread._shared_llm`：类变量，模型只加载一次
- `TTSThread._shared_tts`：类变量，模型只加载一次
- `_tts_queue`：`queue.Queue`，TTS 音频缓冲队列

#### 线程安全

- 所有 UI 更新通过 Qt 信号/槽机制（自动跨线程）
- `_tts_queue` 是线程安全队列
- 状态变量（`_is_playing`, `_is_generating`, `_is_listening`）仅在主线程访问

---

## 5. 数据流

### 5.1 完整语音对话流程

```
用户说话 → sounddevice 采集 → SpeechRecognizerThread
    → text_result 信号 → _on_speech_result
    → _cancel_wake_timeout + _stop_listening
    → _send_to_llm(text)
    → LLMThread.start() → 流式 token
    → _append_token → 聊天显示 + 累积句子
    → _speak_sentence → TTSThread → _tts_queue
    → _play_next → AudioPlayThread → sounddevice 播出
    → playback_finished → _play_next (下一段或队列空)
    → _on_llm_finished → _pending_wake_countdown = True
    → 队列空时 → _start_wake_countdown → 30s 倒计时 + 重启 STT
```

### 5.2 IoT 控制流程

```
用户: "打开客厅的灯"
    → STT → LLM → 输出: {"iot": {"device": "灯", "action": "on", "params": {"room": "客厅"}}}
    → IoTSmartHome.parse_and_execute()
    → _extract_iot_commands() → 解析 JSON
    → _execute_command() → 后台线程执行
    → _execute_in_background():
        1. BanIOT: map_llm_command() → control_device() (局域网优先)
        2. MQTT: publish("banbox/iot/灯/客厅", payload)
        3. HA: POST /api/services/light.turn_on
    → command_executed 信号 → 状态栏显示结果
```

---

## 6. 模型文件

| 模型 | 路径 | 大小约 | 来源 |
|------|------|--------|------|
| Vosk 中文 | `vosk-model/vosk-model-small-cn-0.22/` | 50MB | vosk-model-small-cn-0.22 |
| Whisper | `whisper-models/models--Systran--faster-whisper-base/` | 150MB | HuggingFace (hf-mirror.com) |
| LLM | `llm-models/qwen2.5-1.5b-instruct-q4_k_m.gguf` | 1.1GB | Qwen2.5-1.5B-Instruct Q4_K_M 量化 |
| TTS | `tts-models/vits-zh-ll/` | 100MB | sherpa-onnx VITS 中文 |

---

## 7. 依赖

| 包 | 版本约束 | 用途 |
|----|----------|------|
| `PyQt5` | - | UI 框架 |
| `sounddevice` | - | 音频采集/播放 |
| `numpy` | - | 音频数据处理 |
| `vosk` | - | 语音识别引擎 1 |
| `faster-whisper` | - | 语音识别引擎 2 |
| `llama-cpp-python` | `==0.2.90` | LLM 推理（v0.3.29 有非法指令 bug） |
| `sherpa-onnx` | - | TTS 语音合成 |
| `pyautogui` | 可选 | 听写模式键盘模拟 |
| `paho-mqtt` | 可选 | MQTT IoT 后端 |
| `requests` | 可选 | HA IoT 后端 + BanIOT 局域网控制 |

---

## 8. 已知问题与注意事项

1. **SpeechRecognizerThread 重复**：`ai_assistant.py` 和 `speech_to_text.py` 各有一份 `SpeechRecognizerThread`，代码重复，未来需统一
2. **llama-cpp-python 版本**：v0.3.29 在某些 CPU 上触发 `0xc000001d` 非法指令，必须使用 v0.2.90
3. **Whisper 模型下载**：国内需设置 `HF_ENDPOINT=hf-mirror.com` 和禁用 SSL 验证
4. **倒计时竞态**：LLM 和 TTS 异步完成，需 `_pending_wake_countdown` 标志确保倒计时可靠启动
5. **BanIOT 裁剪**：删除 `ban_iot_bridge.py` 即可，`iot_control.py` 通过 `try/except` 自动适配
6. **听写模式剪贴板**：会临时覆盖剪贴板内容，500ms 后恢复
