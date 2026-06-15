"""TTS 语音合成引擎 - 并发合成 + 有序播放队列"""

import os
import threading
import heapq
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, QThread

try:
    import sherpa_onnx
    HAS_SHERPA = True
except ImportError:
    HAS_SHERPA = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
TTS_MODEL_DIR = os.path.join(PROJECT_ROOT, "tts-models", "vits-zh-ll")


class TTSPipeline(QObject):
    """TTS 流水线：并发合成，按序号有序投递播放"""

    audio_ready = pyqtSignal(np.ndarray, int)  # audio, sample_rate
    synthesis_started = pyqtSignal()
    synthesis_finished = pyqtSignal()
    error = pyqtSignal(str)

    _shared_tts = None
    _tts_lock = threading.Lock()

    def __init__(self, parent=None, max_workers=2):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._seq_counter = 0
        self._pending = 0
        self._next_play_seq = 0
        self._buffer = {}  # seq -> (audio, sr)
        self._buffer_lock = threading.Lock()

    @classmethod
    def load_model(cls):
        if cls._shared_tts is not None:
            return True
        if not HAS_SHERPA:
            return False
        try:
            model_onnx = os.path.join(TTS_MODEL_DIR, "model.onnx")
            tokens = os.path.join(TTS_MODEL_DIR, "tokens.txt")
            lexicon = os.path.join(TTS_MODEL_DIR, "lexicon.txt")
            dict_dir = os.path.join(TTS_MODEL_DIR, "dict")
            if not os.path.exists(model_onnx):
                return False

            tts_config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=model_onnx,
                        tokens=tokens,
                        lexicon=lexicon,
                        dict_dir=dict_dir,
                    ),
                ),
                max_num_sentences=1,
            )
            if not tts_config.validate():
                return False
            cls._shared_tts = sherpa_onnx.OfflineTts(tts_config)
            print("[TTS] 模型加载成功")
            return True
        except Exception as e:
            print(f"[TTS] 模型加载失败: {e}")
            return False

    def speak(self, text):
        """提交一句文本进行合成"""
        text = text.strip()
        if not text:
            return
        if not self.load_model():
            self.error.emit("TTS 模型加载失败")
            return

        seq = self._seq_counter
        self._seq_counter += 1
        self._pending += 1
        self.synthesis_started.emit()
        self._executor.submit(self._synthesize, seq, text)

    def _synthesize(self, seq, text):
        try:
            with self._tts_lock:
                audio = self._shared_tts.generate(text, sid=0, speed=1.0)
            samples = np.array(audio.samples, dtype=np.float32)
            sr = audio.sample_rate
            if len(samples) > 0:
                with self._buffer_lock:
                    self._buffer[seq] = (samples, sr)
                    self._flush_ready()
        except Exception as e:
            self.error.emit(f"TTS 合成错误: {e}")
        finally:
            self._pending -= 1
            if self._pending <= 0:
                self.synthesis_finished.emit()

    def _flush_ready(self):
        """按序号顺序投递已完成的音频"""
        while self._next_play_seq in self._buffer:
            audio, sr = self._buffer.pop(self._next_play_seq)
            self._next_play_seq += 1
            self.audio_ready.emit(audio, sr)

    def reset_sequence(self):
        """打断时重置序号"""
        with self._buffer_lock:
            self._buffer.clear()
            self._seq_counter = 0
            self._next_play_seq = 0
            self._pending = 0

    def shutdown(self):
        self._executor.shutdown(wait=False)
