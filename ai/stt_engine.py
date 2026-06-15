"""统一语音识别引擎 - Vosk / Whisper + WebRTC VAD 动态端点检测"""

import os
import json
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    HAS_VOSK = True
except ImportError:
    HAS_VOSK = False

try:
    from faster_whisper import WhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False

try:
    import webrtcvad
    HAS_WEBRTCVAD = True
except ImportError:
    HAS_WEBRTCVAD = False

from waveform import find_bg_audio_device_index

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
VOSK_MODEL_PATH = os.path.join(PROJECT_ROOT, "vosk-model", "vosk-model-small-cn-0.22")
WHISPER_MODELS_ROOT = os.path.join(PROJECT_ROOT, "whisper-models")


class SpeechRecognizerThread(QThread):
    """语音识别线程 - 支持 Vosk 和 Whisper，Whisper 使用 VAD 动态端点"""

    text_result = pyqtSignal(str)
    partial_result = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    SAMPLE_RATE = 16000
    SILENCE_THRESHOLD = 300
    VAD_FRAME_MS = 30
    VAD_SILENCE_MS = 600
    MAX_SEGMENT_SECONDS = 15

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._device_index = None
        self._model = None
        self._engine = "vosk" if HAS_VOSK else "whisper"
        self._whisper_model_name = "base"
        self._language = "auto"
        self._wake_word = ""
        self._wake_word_enabled = False
        self._bypass_wake_word = False

    def set_engine(self, engine):
        self._engine = engine
        self._model = None

    def set_whisper_model(self, model_name):
        self._whisper_model_name = model_name
        self._model = None

    def set_language(self, lang):
        self._language = lang

    def set_wake_word(self, word):
        self._wake_word = word.strip()

    def set_wake_word_enabled(self, enabled):
        self._wake_word_enabled = enabled

    def set_bypass_wake_word(self, bypass):
        self._bypass_wake_word = bypass

    def _load_vosk_model(self):
        if self._model is not None:
            return True
        if not os.path.exists(VOSK_MODEL_PATH):
            self.error.emit(f"Vosk 模型不存在: {VOSK_MODEL_PATH}")
            return False
        try:
            self.status_changed.emit("正在加载 Vosk 模型...")
            self._model = VoskModel(VOSK_MODEL_PATH)
            return True
        except Exception as e:
            self.error.emit(f"Vosk 模型加载失败: {e}")
            return False

    def _get_whisper_local_path(self):
        repo_map = {
            "tiny": "Systran/faster-whisper-tiny",
            "base": "Systran/faster-whisper-base",
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
            "large-v3": "Systran/faster-whisper-large-v3",
        }
        repo_id = repo_map.get(self._whisper_model_name)
        if not repo_id:
            return None
        local_path = os.path.join(
            WHISPER_MODELS_ROOT,
            "models--" + repo_id.replace("/", "--"),
            "snapshots", "main",
        )
        if os.path.exists(os.path.join(local_path, "model.bin")):
            return local_path
        return None

    def _load_whisper_model(self):
        if self._model is not None:
            return True
        try:
            self.status_changed.emit(f"正在加载 Whisper 模型 {self._whisper_model_name}...")
            local_path = self._get_whisper_local_path()
            if local_path:
                self._model = WhisperModel(local_path, device="cpu", compute_type="int8")
            else:
                self._model = WhisperModel(
                    self._whisper_model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=WHISPER_MODELS_ROOT,
                )
            return True
        except Exception as e:
            self.error.emit(f"Whisper 模型加载失败: {e}")
            return False

    def find_device(self):
        idx = find_bg_audio_device_index()
        if idx is not None:
            self._device_index = idx
            return True
        return False

    def _is_wake_word_match(self, text):
        if self._bypass_wake_word:
            return True
        if not self._wake_word_enabled or not self._wake_word:
            return True
        return self._wake_word.lower() in text.lower()

    def _emit_text(self, text):
        text = text.strip()
        if text and self._is_wake_word_match(text):
            self.text_result.emit(text)

    def _run_vosk(self):
        if not self._load_vosk_model():
            return
        rec = KaldiRecognizer(self._model, self.SAMPLE_RATE)
        block_size = 4000
        with sd.InputStream(
            device=self._device_index,
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=block_size,
        ) as stream:
            while self._running:
                try:
                    data, _ = stream.read(block_size)
                    if not self._running:
                        break
                    if rec.AcceptWaveform(data.tobytes()):
                        result = json.loads(rec.Result())
                        self._emit_text(result.get("text", ""))
                    else:
                        partial = json.loads(rec.PartialResult())
                        ptext = partial.get("partial", "").strip()
                        if ptext:
                            self.partial_result.emit(ptext)
                except Exception:
                    if self._running:
                        self.msleep(100)
            final = json.loads(rec.FinalResult())
            self._emit_text(final.get("text", ""))

    def _transcribe_segment(self, segment_int16):
        audio_float = segment_int16.flatten().astype(np.float32) / 32768.0
        lang = None if self._language == "auto" else self._language
        segments_iter, _ = self._model.transcribe(
            audio_float,
            language=lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
        )
        parts = [seg.text.strip() for seg in segments_iter if seg.text.strip()]
        return "".join(parts).strip()

    def _collect_vad_segments(self, stream, frame_samples, vad):
        """基于 VAD 的动态端点检测，有声→静音 600ms 截断"""
        voiced_frames = []
        silence_frames = 0
        silence_limit = self.VAD_SILENCE_MS // self.VAD_FRAME_MS
        max_frames = (self.MAX_SEGMENT_SECONDS * 1000) // self.VAD_FRAME_MS
        speech_started = False

        while self._running:
            data, _ = stream.read(frame_samples)
            if not self._running:
                break

            frame = data.tobytes()
            is_speech = vad.is_speech(frame, self.SAMPLE_RATE)

            if is_speech:
                speech_started = True
                voiced_frames.append(frame)
                silence_frames = 0
                if len(voiced_frames) >= max_frames:
                    yield b"".join(voiced_frames)
                    voiced_frames.clear()
                    speech_started = False
            elif speech_started:
                voiced_frames.append(frame)
                silence_frames += 1
                if silence_frames >= silence_limit:
                    if voiced_frames:
                        yield b"".join(voiced_frames)
                    voiced_frames.clear()
                    silence_frames = 0
                    speech_started = False

    def _run_whisper_vad(self):
        """Whisper + WebRTC VAD 动态分段"""
        if not self._load_whisper_model():
            return

        frame_samples = int(self.SAMPLE_RATE * self.VAD_FRAME_MS / 1000)
        vad = webrtcvad.Vad(2)

        with sd.InputStream(
            device=self._device_index,
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
        ) as stream:
            for audio_bytes in self._collect_vad_segments(stream, frame_samples, vad):
                if not self._running:
                    break
                segment = np.frombuffer(audio_bytes, dtype=np.int16).reshape(-1, 1)
                rms = np.sqrt(np.mean(segment.astype(np.float32) ** 2))
                if rms < self.SILENCE_THRESHOLD:
                    self.partial_result.emit("(静音中...)")
                    continue
                self.partial_result.emit("正在识别...")
                full_text = self._transcribe_segment(segment)
                if full_text:
                    if self._is_wake_word_match(full_text):
                        self.text_result.emit(full_text)
                    else:
                        self.partial_result.emit(f"(唤醒词未匹配: {full_text})")

    def _run_whisper_fixed(self):
        """无 webrtcvad 时的回退：较短固定窗口 + RMS"""
        if not self._load_whisper_model():
            return
        record_seconds = 3
        with sd.InputStream(
            device=self._device_index,
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.SAMPLE_RATE,
        ) as stream:
            audio_buffer = np.zeros((0, 1), dtype=np.int16)
            while self._running:
                try:
                    data, _ = stream.read(self.SAMPLE_RATE)
                    if not self._running:
                        break
                    audio_buffer = np.concatenate([audio_buffer, data], axis=0)
                    needed = self.SAMPLE_RATE * record_seconds
                    if len(audio_buffer) >= needed:
                        segment = audio_buffer[:needed]
                        audio_buffer = audio_buffer[needed // 2:]
                        rms = np.sqrt(np.mean(segment.astype(np.float32) ** 2))
                        if rms < self.SILENCE_THRESHOLD:
                            self.partial_result.emit("(静音中...)")
                            continue
                        self.partial_result.emit("正在识别...")
                        full_text = self._transcribe_segment(segment)
                        if full_text:
                            if self._is_wake_word_match(full_text):
                                self.text_result.emit(full_text)
                            else:
                                self.partial_result.emit(f"(唤醒词未匹配: {full_text})")
                except Exception:
                    if self._running:
                        self.msleep(100)

    def _run_whisper(self):
        if HAS_WEBRTCVAD:
            self._run_whisper_vad()
        else:
            self._run_whisper_fixed()

    def run(self):
        if not HAS_SOUNDDEVICE:
            self.error.emit("sounddevice 未安装")
            return
        if self._device_index is None and not self.find_device():
            self.error.emit("未找到 BG Audio Card 音频输入设备")
            return

        self._running = True
        self.status_changed.emit("正在监听...")
        try:
            if self._engine == "vosk":
                if not HAS_VOSK:
                    self.error.emit("Vosk 未安装")
                    return
                self._run_vosk()
            else:
                if not HAS_FASTER_WHISPER:
                    self.error.emit("faster-whisper 未安装")
                    return
                self._run_whisper()
        except Exception as e:
            if self._running:
                self.error.emit(str(e))
        finally:
            self.status_changed.emit("已停止")

    def stop(self):
        self._running = False
        self.wait(5000)
