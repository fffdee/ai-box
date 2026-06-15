"""AI 语音助手模块 - 兼容入口，实际实现位于 ai/ 子包"""

from ai.assistant_panel import AIAssistantPanel
from ai.stt_engine import SpeechRecognizerThread, HAS_VOSK, HAS_FASTER_WHISPER, HAS_SOUNDDEVICE
from ai.llm_engine import LLMThread, HAS_LLAMA, SYSTEM_PROMPT, LLM_MODEL_PATH, get_selected_model_id, build_system_prompt
from ai.llm_models import LLM_MODELS, DEFAULT_MODEL_ID, get_model_info
from ai.llm_settings import LlmSettingsPanel
from ai.tts_engine import TTSPipeline, HAS_SHERPA, TTS_MODEL_DIR
from ai.audio_player import NonBlockingPlayer, AudioPlayThread, InterruptListener
from ai.wake_state_machine import WakeState, WakeStateMachine

# 向后兼容：旧代码可能引用 TTSThread / AudioPlayThread
from ai.tts_engine import TTSPipeline as TTSThread  # noqa: F401

__all__ = [
    "AIAssistantPanel",
    "SpeechRecognizerThread",
    "LLMThread",
    "build_system_prompt",
    "TTSPipeline",
    "TTSThread",
    "NonBlockingPlayer",
    "AudioPlayThread",
    "InterruptListener",
    "WakeStateMachine",
    "WakeState",
    "HAS_VOSK",
    "HAS_FASTER_WHISPER",
    "HAS_SOUNDDEVICE",
    "HAS_LLAMA",
    "HAS_SHERPA",
    "SYSTEM_PROMPT",
    "LLM_MODEL_PATH",
    "TTS_MODEL_DIR",
    "LLM_MODELS",
    "DEFAULT_MODEL_ID",
    "get_model_info",
    "get_selected_model_id",
    "LlmSettingsPanel",
]
