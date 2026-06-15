"""唤醒词与对话状态机"""

from enum import Enum, auto
from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class WakeState(Enum):
    IDLE = auto()
    LISTENING = auto()      # 持续监听，等待唤醒词
    ACTIVATED = auto()      # 已唤醒，等待用户说话
    GENERATING = auto()     # LLM 生成中
    PLAYING = auto()        # TTS 播放中
    COUNTDOWN = auto()      # 对话窗口倒计时


class WakeStateMachine(QObject):
    """显式 FSM，分离「用户开启唤醒监听」与「当前 STT 过滤模式」"""

    state_changed = pyqtSignal(WakeState, WakeState)  # old, new

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = WakeState.IDLE
        self._wake_listening_enabled = False  # 用户是否开启唤醒词监听
        self._activated = False               # 是否处于对话窗口（已唤醒）
        self._countdown_timer = None
        self._countdown_seconds = 30
        self._on_countdown_timeout = None
        self._last_wake_time = 0.0

    @property
    def state(self):
        return self._state

    @property
    def wake_listening_enabled(self):
        return self._wake_listening_enabled

    @property
    def activated(self):
        return self._activated

    def is_wake_listening_active(self):
        return self._wake_listening_enabled and self._state in (
            WakeState.LISTENING, WakeState.COUNTDOWN
        )

    def set_wake_listening_enabled(self, enabled):
        self._wake_listening_enabled = enabled
        if enabled:
            self._activated = False
            self._transition(WakeState.LISTENING)
        elif self._state != WakeState.GENERATING and self._state != WakeState.PLAYING:
            self._activated = False
            self._cancel_countdown()
            self._transition(WakeState.IDLE)

    def on_wake_word_detected(self):
        self._activated = True
        self._transition(WakeState.ACTIVATED)

    def on_user_speech(self):
        self._cancel_countdown()
        self._transition(WakeState.GENERATING)

    def on_llm_started(self):
        self._transition(WakeState.GENERATING)

    def on_llm_finished(self, has_tts_pending):
        if has_tts_pending:
            self._transition(WakeState.PLAYING)
        elif self._wake_listening_enabled and self._activated:
            self._transition(WakeState.COUNTDOWN)
            self._start_countdown()
        else:
            self._transition(WakeState.IDLE if not self._wake_listening_enabled else WakeState.LISTENING)

    def on_tts_started(self):
        self._transition(WakeState.PLAYING)

    def on_tts_finished(self):
        if self._wake_listening_enabled and self._activated:
            self._transition(WakeState.COUNTDOWN)
            self._start_countdown()
        elif self._wake_listening_enabled:
            self._activated = False
            self._transition(WakeState.LISTENING)
        else:
            self._transition(WakeState.IDLE)

    def on_countdown_timeout(self):
        """超时后回到唤醒词监听（Bug #1 修复点）"""
        self._activated = False
        self._cancel_countdown()
        if self._wake_listening_enabled:
            self._transition(WakeState.LISTENING)
        else:
            self._transition(WakeState.IDLE)

    def on_interrupt(self):
        """用户打断 TTS"""
        self._cancel_countdown()
        if self._wake_listening_enabled and self._activated:
            self._transition(WakeState.COUNTDOWN)
            self._start_countdown()
        elif self._wake_listening_enabled:
            self._transition(WakeState.LISTENING)
        else:
            self._transition(WakeState.IDLE)

    def reset(self):
        self._activated = False
        self._cancel_countdown()
        self._transition(WakeState.IDLE)

    def set_countdown_seconds(self, seconds):
        self._countdown_seconds = max(5, int(seconds))

    @property
    def countdown_seconds(self):
        return self._countdown_seconds

    def set_countdown_callback(self, callback):
        self._on_countdown_timeout = callback

    def get_stt_mode(self):
        """返回 STT 应使用的模式: listen_wake | bypass_wake | manual"""
        if self._state == WakeState.LISTENING:
            return "listen_wake"
        if self._state in (WakeState.ACTIVATED, WakeState.COUNTDOWN):
            return "bypass_wake"
        return "manual"

    def should_filter_wake_word(self):
        return self.get_stt_mode() == "listen_wake"

    def should_bypass_wake_word(self):
        return self.get_stt_mode() == "bypass_wake"

    def _transition(self, new_state):
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        self.state_changed.emit(old, new_state)

    def _start_countdown(self):
        self._cancel_countdown()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setSingleShot(True)
        self._countdown_timer.timeout.connect(self._handle_countdown_timeout)
        self._countdown_timer.start(self._countdown_seconds * 1000)

    def _handle_countdown_timeout(self):
        self.on_countdown_timeout()
        if self._on_countdown_timeout:
            self._on_countdown_timeout()

    def _cancel_countdown(self):
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def cancel_countdown(self):
        self._cancel_countdown()
