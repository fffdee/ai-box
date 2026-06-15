"""AI 助手面板 - 薄 UI 控制层，整合 STT/LLM/TTS/状态机"""

import re
import time
from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QLineEdit

from iot_control import IoTSmartHome
from ai.stt_engine import SpeechRecognizerThread, HAS_VOSK, HAS_FASTER_WHISPER, HAS_SOUNDDEVICE
from ai.llm_engine import LLMThread, HAS_LLAMA, get_selected_model_id
from ai.llm_models import get_model_info, is_model_downloaded, DEFAULT_MODEL_ID
from ai.tts_engine import TTSPipeline, HAS_SHERPA
from ai.audio_player import NonBlockingPlayer, InterruptListener
from ai.wake_state_machine import WakeState, WakeStateMachine

try:
    import sounddevice as sd
except ImportError:
    sd = None


class AIAssistantPanel(QWidget):
    """AI 语音助手面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speech_thread = None
        self._llm_thread = None
        self._chat_messages = []
        self._is_listening = False
        self._voice_input_enabled = False  # 语音输入模式是否开启（独立于 _is_listening）
        self._is_generating = False
        self._current_response = ""
        self._settings = QSettings("BanBox", "BGAICard")
        self._device = None

        self._fsm = WakeStateMachine(self)
        self._fsm.state_changed.connect(self._on_fsm_state_changed)
        self._fsm.set_countdown_callback(self._on_fsm_countdown_restart)

        self._ducking_enabled = False
        self._is_ducked = False
        self._unduck_timer = None
        self._dictation_mode = False
        self._pending_dictation_start = False
        self._last_wake_time = 0.0

        self._iot = IoTSmartHome(self)
        self._iot.command_executed.connect(self._on_iot_command_executed)

        self._tts_pipeline = TTSPipeline(self)
        self._tts_pipeline.audio_ready.connect(self._on_tts_audio_ready)
        self._tts_pipeline.error.connect(self._on_tts_error)

        self._player = NonBlockingPlayer(self)
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.segment_started.connect(self._on_segment_started)
        self._player.error.connect(self._on_tts_error)
        self._player.start()

        self._interrupt_listener = InterruptListener(self)
        self._interrupt_listener.interrupted.connect(self._on_user_interrupt)

        self._pending_tts_text = ""
        self._is_playing = False
        self._pending_wake_countdown = False
        self._pending_music = None  # 待播放音乐（等 TTS 播完后执行）

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()
        self.tts_btn = QPushButton("🔊")
        self.tts_btn.setCheckable(True)
        self.tts_btn.setChecked(True)
        self.tts_btn.setToolTip("语音朗读开关")
        self.tts_btn.setFixedWidth(40)
        self.tts_btn.setStyleSheet(
            "QPushButton { background: #2d2d44; color: #aaa; border-radius: 4px; padding: 4px; }"
            "QPushButton:checked { background: #27ae60; color: white; }"
        )
        ctrl.addWidget(self.tts_btn)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入消息，按 Enter 发送...")
        self.input_edit.setStyleSheet(
            "QLineEdit { background: #1a1a2e; color: #E0E0E0; border: 1px solid #333; "
            "border-radius: 4px; padding: 8px; font-size: 13px; }"
        )
        self.input_edit.returnPressed.connect(self._send_text)
        ctrl.addWidget(self.input_edit, 1)

        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(self._btn_style("#2e86c1", "#3498db"))
        self.send_btn.clicked.connect(self._send_text)
        ctrl.addWidget(self.send_btn)
        layout.addLayout(ctrl)

        self.status_lbl = QLabel("就绪")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #888; padding: 2px;")
        layout.addWidget(self.status_lbl)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet(
            "QTextEdit { background-color: #1a1a2e; color: #E0E0E0; border: 1px solid #333; "
            "border-radius: 6px; font-size: 14px; padding: 10px; }"
        )
        self.chat_display.setPlaceholderText(
            "AI 语音助手对话区\n\n在系统设置中开启语音输入/唤醒词监听\n也可直接打字发送"
        )
        layout.addWidget(self.chat_display, 1)

        hint = QLabel(self._engine_hint_text())
        hint.setStyleSheet("font-size: 9px; color: #555;")
        hint.setAlignment(Qt.AlignCenter)
        self.engine_hint_lbl = hint
        layout.addWidget(hint)

    def _btn_style(self, color, hover):
        return (
            f"QPushButton {{ background-color: {color}; color: white; border-radius: 4px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ background-color: {hover}; }}"
            f"QPushButton:disabled {{ background-color: #555; color: #999; }}"
        )

    def _engine_hint_text(self):
        engines = []
        if HAS_VOSK:
            engines.append("Vosk")
        if HAS_FASTER_WHISPER:
            engines.append("Whisper")
        if HAS_LLAMA:
            engines.append("LLM")
        if HAS_SHERPA:
            engines.append("TTS")
        model_id = self._get_llm_model_id()
        model_name = get_model_info(model_id)["name"]
        return f"可用: {', '.join(engines) if engines else '无'} | LLM: {model_name} | 音源: BG Audio Card"

    def _get_llm_model_id(self):
        try:
            from main_window import MainWindow
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            for widget in app.topLevelWidgets():
                if isinstance(widget, MainWindow):
                    if hasattr(widget, "system_panel") and hasattr(widget.system_panel, "llm_settings"):
                        return widget.system_panel.llm_settings.get_model_id()
        except Exception:
            pass
        return get_selected_model_id()

    def on_llm_model_changed(self):
        LLMThread.unload_model()
        if hasattr(self, "engine_hint_lbl"):
            self.engine_hint_lbl.setText(self._engine_hint_text())

    def set_device(self, device):
        self._device = device

    def device_is_connected(self):
        if self._device is None:
            return False
        return hasattr(self._device, "is_connected") and self._device.is_connected()

    # ---- 公共接口 ----

    def set_voice_input_enabled(self, enabled):
        self._voice_input_enabled = enabled
        if enabled:
            self._fsm.reset()
            self._start_listening(manual=True)
        else:
            self._stop_listening()

    def set_wake_listening_enabled(self, enabled):
        timeout = self._settings.value("stt/wake_timeout", 30, type=int)
        self._fsm.set_countdown_seconds(timeout)
        self._fsm.set_wake_listening_enabled(enabled)
        if enabled:
            self._stop_listening()
            QTimer.singleShot(200, lambda: self._start_listening_from_fsm())
        else:
            self._stop_listening()

    def set_ducking_enabled(self, enabled):
        self._ducking_enabled = enabled
        if not enabled and self._is_ducked:
            self._duck_unmute()

    def set_dictation_enabled(self, enabled):
        self._dictation_mode = enabled
        if enabled:
            self._start_listening(manual=True)
            self.status_lbl.setText("语音输入：请说话，文字将输出到光标处...")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")
        else:
            self._stop_listening()
            self.status_lbl.setText("就绪")

    def is_voice_input_active(self):
        return self._voice_input_enabled and not self._fsm.wake_listening_enabled

    def is_wake_listening_active(self):
        return self._fsm.is_wake_listening_active()

    def is_ducking_active(self):
        return self._ducking_enabled

    def is_dictation_active(self):
        return self._dictation_mode

    # ---- Ducking ----

    def _duck_mute(self):
        if not self._ducking_enabled or self._is_ducked:
            return
        if self._device and self.device_is_connected():
            self._device.set_mute(1)
            self._is_ducked = True
        if self._unduck_timer is not None:
            self._unduck_timer.stop()
            self._unduck_timer = None

    def _duck_unmute(self):
        if not self._is_ducked:
            return
        if self._device and self.device_is_connected():
            self._device.set_mute(0)
            self._is_ducked = False

    def _duck_schedule_unmute(self, delay_ms=1500):
        if self._unduck_timer is not None:
            self._unduck_timer.stop()
        self._unduck_timer = QTimer(self)
        self._unduck_timer.setSingleShot(True)
        self._unduck_timer.timeout.connect(self._duck_unmute)
        self._unduck_timer.start(delay_ms)

    # ---- 设置 ----

    def _load_settings(self):
        self._stt_engine = self._settings.value("stt/engine", "vosk" if HAS_VOSK else "whisper")
        self._whisper_model = self._settings.value("stt/whisper_model", "base")
        self._language = self._settings.value("stt/language", "auto")
        self._wake_word = self._settings.value("stt/wake_word", "小班")
        self._wake_word_enabled = self._settings.value("stt/wake_enabled", False, type=bool)
        timeout = self._settings.value("stt/wake_timeout", 30, type=int)
        self._fsm.set_countdown_seconds(timeout)
        # 默认开启语音输入（无需唤醒词）
        voice_input = self._settings.value("ai/voice_input", True, type=bool)
        if voice_input:
            QTimer.singleShot(500, lambda: self.set_voice_input_enabled(True))

    def _get_stt_settings(self):
        try:
            from main_window import MainWindow
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            for widget in app.topLevelWidgets():
                if isinstance(widget, MainWindow):
                    if hasattr(widget, "system_panel") and hasattr(widget.system_panel, "stt_settings"):
                        stt = widget.system_panel.stt_settings
                        return {
                            "engine": stt.get_engine(),
                            "whisper_model": stt.get_whisper_model_name(),
                            "language": stt.get_language(),
                            "wake_word": stt.get_wake_word(),
                            "wake_word_enabled": stt.is_wake_word_enabled(),
                        }
        except Exception:
            pass
        return {
            "engine": self._stt_engine,
            "whisper_model": self._whisper_model,
            "language": self._language,
            "wake_word": self._wake_word,
            "wake_word_enabled": self._wake_word_enabled,
        }

    # ---- 聊天 UI ----

    def _append_user_message(self, text):
        self._chat_messages.append({"role": "user", "content": text})
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertHtml(
            f'<p style="color: #3498db; font-weight: bold;">你:</p>'
            f'<p style="color: #E0E0E0; margin-left: 10px; margin-bottom: 8px;">{text}</p>'
        )
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def _start_assistant_message(self):
        self._current_response = ""
        self._pending_tts_text = ""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertHtml(
            '<p style="color: #2ecc71; font-weight: bold;">小班:</p>'
            '<p style="color: #E0E0E0; margin-left: 10px; margin-bottom: 8px;" id="assistant">'
        )
        self.chat_display.setTextCursor(cursor)

    _SENTENCE_ENDINGS = re.compile(r"[。！？；\n]")
    # 匹配 JSON 格式的工具/IoT 指令，避免 TTS 朗读
    _JSON_PATTERN = re.compile(
        r'\{[^{}]*"(?:tool|action|iot)"\s*:\s*"[^"]*"[^{}]*\}'
        r'|```json\s*?\{.*?\}\s*?```'
        r'|\{"iot"\s*:\s*\{[^}]*\}\s*\}',
        re.DOTALL,
    )

    def _clean_for_tts(self, text):
        """清理文本中的 JSON 指令，只保留可朗读的自然语言"""
        cleaned = self._JSON_PATTERN.sub("", text)
        # 清理残留的代码块标记
        cleaned = re.sub(r'```\w*\n?', '', cleaned)
        # 清理多余空白
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _append_token(self, token):
        self._current_response += token
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(token)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

        if self.tts_btn.isChecked() and HAS_SHERPA:
            self._pending_tts_text += token

            # 检测 JSON 开始：如果待合成文本以 { 开头，暂停 TTS 直到 JSON 结束
            stripped = self._pending_tts_text.strip()
            if stripped.startswith("{") or stripped.startswith("```"):
                # 统计花括号平衡
                open_braces = self._pending_tts_text.count("{")
                close_braces = self._pending_tts_text.count("}")
                if open_braces > close_braces:
                    # JSON 还没结束，继续累积
                    return
                # JSON 可能已结束，清理后检查
                clean = self._clean_for_tts(self._pending_tts_text)
                self._pending_tts_text = ""
                if clean:
                    self._speak_sentence(clean)
                return

            if self._SENTENCE_ENDINGS.search(token) or len(self._pending_tts_text) > 50:
                sentence = self._pending_tts_text.strip()
                if sentence:
                    clean = self._clean_for_tts(sentence)
                    self._pending_tts_text = ""
                    if clean:
                        self._speak_sentence(clean)

    def _finish_assistant_message(self, full_text):
        if not full_text.strip():
            return
        self._chat_messages.append({"role": "assistant", "content": full_text})
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertHtml("</p>")
        self.chat_display.setTextCursor(cursor)

    # ---- STT ----

    def _configure_speech_thread(self, thread):
        settings = self._get_stt_settings()
        thread.set_engine(settings["engine"])
        thread.set_whisper_model(settings["whisper_model"])
        thread.set_language(settings["language"])

        mode = self._fsm.get_stt_mode()
        wake_word = self._settings.value("stt/wake_word", "小班")

        if mode == "listen_wake":
            thread.set_wake_word(wake_word)
            thread.set_wake_word_enabled(True)
            thread.set_bypass_wake_word(False)
        elif mode == "bypass_wake":
            thread.set_wake_word(wake_word)
            thread.set_wake_word_enabled(True)
            thread.set_bypass_wake_word(True)
        else:
            thread.set_wake_word("")
            thread.set_wake_word_enabled(False)
            thread.set_bypass_wake_word(False)

    def _start_listening(self, manual=False):
        if not HAS_VOSK and not HAS_FASTER_WHISPER:
            self.status_lbl.setText("未安装语音识别引擎")
            return
        if not HAS_SOUNDDEVICE:
            self.status_lbl.setText("未安装 sounddevice")
            return

        if self._is_listening and self._speech_thread is not None:
            self._speech_thread.stop()
            self._speech_thread = None

        self._speech_thread = SpeechRecognizerThread(self)
        self._configure_speech_thread(self._speech_thread)
        self._speech_thread.text_result.connect(self._on_speech_result)
        self._speech_thread.partial_result.connect(self._on_speech_partial)
        self._speech_thread.status_changed.connect(self._on_speech_status)
        self._speech_thread.error.connect(self._on_speech_error)
        self._speech_thread.start()
        self._is_listening = True

        if manual:
            self.status_lbl.setText("正在监听...")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")
        elif self._fsm.state == WakeState.LISTENING:
            ww = self._settings.value("stt/wake_word", "小班")
            self.status_lbl.setText(f"监听中... (唤醒词: {ww})")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #e67e22; padding: 2px;")
        elif self._fsm.state == WakeState.COUNTDOWN:
            timeout = self._fsm.countdown_seconds
            self.status_lbl.setText(f"对话中... ({timeout}秒内请说话)")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #2ecc71; padding: 2px;")

    def _start_listening_from_fsm(self):
        """FSM 状态变化后延迟重启 STT"""
        if self._fsm.state in (WakeState.LISTENING, WakeState.COUNTDOWN, WakeState.ACTIVATED):
            if not self._is_generating and not self._is_playing:
                self._start_listening()

    def _stop_listening(self):
        if self._speech_thread is not None:
            self._speech_thread.stop()
            self._speech_thread = None
        self._is_listening = False
        self._interrupt_listener.stop_listening()

    def _on_speech_result(self, text):
        if self._is_playing or self._is_generating:
            print(f"[AI] 忽略 STT（AI 输出中）: {text[:30]}")
            return

        self._duck_schedule_unmute()

        if self._dictation_mode:
            self._type_text_at_cursor(text)
            return

        if self._fsm.state == WakeState.LISTENING:
            wake_word = self._settings.value("stt/wake_word", "小班")
            if wake_word.lower() in text.lower():
                self._on_wake_word_detected(text)
            return

        if self._fsm.activated or self._fsm.state == WakeState.COUNTDOWN:
            self._fsm.cancel_countdown()
            if "语音输入" in text or "语音打字" in text:
                self._enter_dictation_from_wake()
                return
            self._stop_listening()
            self._fsm.on_user_speech()
            self._send_to_llm(text)
            return

        self._stop_listening()
        self._send_to_llm(text)

    def _on_wake_word_detected(self, text):
        now = time.time()
        if now - self._last_wake_time < 3.0:
            return
        self._last_wake_time = now

        self._stop_listening()
        self._fsm.on_wake_word_detected()

        if "语音输入" in text or "语音打字" in text:
            self._enter_dictation_from_wake()
            return

        wake_word = self._settings.value("stt/wake_word", "小班")
        extra = re.sub(re.escape(wake_word), "", text, count=1, flags=re.IGNORECASE).strip()

        if extra:
            self._fsm.on_user_speech()
            self._send_to_llm(extra)
            return

        wake_reply = self._settings.value("stt/wake_reply", "我在，请说")
        self.status_lbl.setText(f"已唤醒！{wake_reply}")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #2ecc71; padding: 2px;")

        if self.tts_btn.isChecked() and HAS_SHERPA:
            self._speak_sentence(wake_reply)
        else:
            self._fsm.on_tts_finished()
            QTimer.singleShot(1000, self._start_listening_from_fsm)

    def _enter_dictation_from_wake(self):
        self._fsm.reset()
        self._stop_listening()
        self._dictation_mode = True
        self.status_lbl.setText("语音输入：请说话，文字将输出到光标处...")
        prompt = "请说"
        if self.tts_btn.isChecked() and HAS_SHERPA:
            self._pending_dictation_start = True
            self._speak_sentence(prompt)
        else:
            self._start_listening(manual=True)

    def _on_fsm_state_changed(self, old_state, new_state):
        print(f"[FSM] {old_state.name} -> {new_state.name}")

    def _on_fsm_countdown_restart(self):
        """倒计时超时后重启唤醒词监听"""
        self._stop_listening()
        self.status_lbl.setText("对话超时，等待唤醒...")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #e67e22; padding: 2px;")
        QTimer.singleShot(1000, self._start_listening_from_fsm)

    def _on_speech_partial(self, text):
        self.status_lbl.setText(f"识别中: {text}")
        if text and not text.startswith("("):
            self._duck_mute()
        elif text == "(静音中...)":
            self._duck_schedule_unmute()

    def _on_speech_status(self, text):
        self.status_lbl.setText(text)

    def _on_speech_error(self, msg):
        self.status_lbl.setText(f"语音错误: {msg}")
        self._stop_listening()

    def _type_text_at_cursor(self, text):
        try:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            old_text = clipboard.text()
            clipboard.setText(text)
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "v")
            except ImportError:
                import ctypes
                user32 = ctypes.windll.user32
                VK_CONTROL, VK_V = 0x11, 0x56
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 2, 0)
                user32.keybd_event(VK_CONTROL, 0, 2, 0)
            QTimer.singleShot(500, lambda: clipboard.setText(old_text))
        except Exception as e:
            print(f"[Dictation] 输出失败: {e}")

    # ---- LLM ----

    def _send_text(self):
        text = self.input_edit.text().strip()
        if not text or self._is_generating:
            return
        self.input_edit.clear()
        self._send_to_llm(text)

    def _send_to_llm(self, text):
        if self._is_generating:
            return
        if not HAS_LLAMA:
            self._append_user_message(text)
            self._start_assistant_message()
            self._append_token("LLM 未安装，请安装 llama-cpp-python")
            self._finish_assistant_message("LLM 未安装")
            return

        self._is_generating = True
        self._fsm.on_llm_started()
        self._append_user_message(text)
        self._start_assistant_message()

        self._llm_thread = LLMThread(self)
        self._llm_thread.set_model_id(self._get_llm_model_id())
        self._llm_thread.set_prompt(text)
        self._llm_thread.set_messages(list(self._chat_messages[:-1]))
        self._llm_thread.token_generated.connect(self._append_token)
        self._llm_thread.finished_response.connect(self._on_llm_finished)
        self._llm_thread.tool_executed.connect(self._on_tool_executed)
        self._llm_thread.error.connect(self._on_llm_error)
        self._llm_thread.model_loaded.connect(self._on_llm_model_loaded)
        self._llm_thread.start()

        model_name = get_model_info(self._get_llm_model_id())["name"]
        self.status_lbl.setText(f"AI 正在思考... ({model_name})")
        self.send_btn.setEnabled(False)

    def _on_llm_model_loaded(self, model_id):
        if hasattr(self, "engine_hint_lbl"):
            self.engine_hint_lbl.setText(self._engine_hint_text())

    def _on_llm_finished(self, full_text):
        clean_text, has_iot = self._iot.parse_and_execute(full_text)

        # 如果有 IoT 指令，提取 reply 字段作为 TTS 朗读内容
        iot_reply = ""
        if has_iot:
            try:
                # 尝试从原始文本提取 reply
                import json
                for match in re.finditer(r'\{[^{}]*"action"\s*:\s*"control"[^{}]*\}', full_text):
                    obj = json.loads(match.group(0))
                    if obj.get("reply"):
                        iot_reply += obj["reply"]
            except Exception:
                pass

        self._finish_assistant_message(clean_text if has_iot else full_text)

        if self.tts_btn.isChecked() and HAS_SHERPA:
            # 优先朗读 IoT reply，否则朗读残余文本（过滤 JSON）
            if iot_reply:
                self._pending_tts_text = ""
                self._speak_sentence(iot_reply)
            else:
                remaining = self._pending_tts_text.strip()
                if remaining:
                    clean = self._clean_for_tts(remaining)
                    self._pending_tts_text = ""
                    if clean:
                        self._speak_sentence(clean)

        self._is_generating = False
        self.send_btn.setEnabled(True)

        has_tts = self._is_playing or self._player.has_pending_audio()
        if self._fsm.wake_listening_enabled and self._fsm.activated:
            if has_tts:
                self._pending_wake_countdown = True
                self._fsm.on_llm_finished(True)
            else:
                self._fsm.on_llm_finished(False)
                QTimer.singleShot(1000, self._start_listening_from_fsm)
        elif not has_tts:
            # 非唤醒词模式：LLM 完成后重启 STT（持续监听）
            if self.is_voice_input_active() or self._dictation_mode:
                QTimer.singleShot(500, self._start_listening)
            else:
                self.status_lbl.setText("就绪")

    def _on_tool_executed(self, tool_name, result):
        from ai.music_player import is_music_playing, get_now_playing
        if tool_name.startswith("music"):
            if tool_name == "music_play":
                # 延迟播放：等 TTS 播完再播放音乐
                if self._is_playing or self._player.has_pending_audio():
                    self._pending_music = ("music_play", result)
                    self.status_lbl.setText("🎵 TTS播完后播放音乐...")
                    self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")
                else:
                    self._play_music_now(result)
            elif is_music_playing():
                self.status_lbl.setText(f"🎵 正在播放: {get_now_playing()}")
                self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")
            else:
                self.status_lbl.setText(f"🎵 {result[:60]}")
                self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")
        elif tool_name == "web_search":
            self.status_lbl.setText(f"🔍 已搜索")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #3498db; padding: 2px;")
        else:
            self.status_lbl.setText(f"工具 {tool_name}: {result[:40]}...")

    def _play_music_now(self, result=""):
        """立即播放音乐并更新状态"""
        from ai.music_player import is_music_playing, get_now_playing
        if is_music_playing():
            self.status_lbl.setText(f"🎵 正在播放: {get_now_playing()}")
        else:
            self.status_lbl.setText(f"🎵 {result[:60]}")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #9b59b6; padding: 2px;")

    def _on_llm_error(self, msg):
        self._append_token(f"\n[错误: {msg}]")
        self._finish_assistant_message("")
        self._is_generating = False
        self.send_btn.setEnabled(True)
        if self._fsm.wake_listening_enabled and self._fsm.activated and not self._is_playing:
            self._fsm.on_llm_finished(False)
            QTimer.singleShot(1000, self._start_listening_from_fsm)

    def _on_iot_command_executed(self, device, success, message):
        status = f"✓ {message}" if success else f"✗ {message}"
        self.status_lbl.setText(status)

    # ---- TTS + 播放 ----

    def _speak_sentence(self, text):
        if not text.strip():
            return
        self._is_playing = True
        self._fsm.on_tts_started()
        self._tts_pipeline.speak(text)

    def _on_tts_audio_ready(self, audio_data, sample_rate):
        self._player.enqueue(audio_data, sample_rate)
        self._interrupt_listener.start_listening()

    def _on_segment_started(self):
        self._duck_mute()
        self.status_lbl.setText("正在朗读...")

    def _on_playback_finished(self):
        self._interrupt_listener.stop_listening()
        self._is_playing = False
        self._duck_schedule_unmute(800)

        # TTS 播完后执行待播放的音乐
        if self._pending_music:
            tool, result = self._pending_music
            self._pending_music = None
            self._play_music_now(result)
            return

        if self._pending_dictation_start:
            self._pending_dictation_start = False
            self._start_listening(manual=True)
            return

        if self._pending_wake_countdown:
            self._pending_wake_countdown = False
            self._fsm.on_tts_finished()
            QTimer.singleShot(1000, self._start_listening_from_fsm)
        elif self._fsm.wake_listening_enabled and self._fsm.activated:
            self._fsm.on_tts_finished()
            QTimer.singleShot(1000, self._start_listening_from_fsm)
        else:
            # 非唤醒词模式：TTS 播完后重启 STT（持续监听）
            if self.is_voice_input_active() or self._dictation_mode:
                QTimer.singleShot(1000, self._start_listening)
            else:
                self.status_lbl.setText("就绪")

    def _on_user_interrupt(self):
        """用户语音打断 TTS"""
        print("[AI] 用户打断 TTS")
        self._player.stop_playback()
        self._tts_pipeline.reset_sequence()
        self._is_playing = False
        self._interrupt_listener.stop_listening()
        self._fsm.on_interrupt()
        # 唤醒词模式和非唤醒词模式都重启 STT
        if self._fsm.wake_listening_enabled:
            QTimer.singleShot(300, self._start_listening_from_fsm)
        elif self.is_voice_input_active() or self._dictation_mode:
            QTimer.singleShot(300, self._start_listening)

    def _on_tts_error(self, msg):
        self.status_lbl.setText(f"TTS 错误: {msg}")
        if not self._is_playing:
            if self._pending_wake_countdown:
                self._pending_wake_countdown = False
                self._fsm.on_tts_finished()
                QTimer.singleShot(1000, self._start_listening_from_fsm)

    def cleanup(self):
        self._stop_listening()
        self._duck_unmute()
        if self._llm_thread is not None:
            self._llm_thread.stop()
        self._player.stop()
        self._tts_pipeline.shutdown()
        if sd is not None:
            sd.stop()
