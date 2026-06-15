"""非阻塞音频播放与语音打断监听"""

import threading
import queue
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    import webrtcvad
    HAS_WEBRTCVAD = True
except ImportError:
    HAS_WEBRTCVAD = False

from waveform import find_bg_audio_device_index


def find_bg_output_device():
    """查找 BG Audio Card 输出设备"""
    if not HAS_SOUNDDEVICE:
        return None
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_output_channels"] > 0 and "BG" in dev["name"]:
                return i
    except Exception:
        pass
    return None


class NonBlockingPlayer(QThread):
    """基于 OutputStream 的非阻塞顺序播放器"""

    playback_finished = pyqtSignal()
    segment_started = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._running = False
        self._stop_flag = False
        self._device_index = find_bg_output_device()
        self._stream = None
        self._current_audio = None
        self._current_pos = 0
        self._current_sr = 22050
        self._lock = threading.Lock()
        self._idle_emitted = False

    def enqueue(self, audio_data, sample_rate):
        self._queue.put((np.asarray(audio_data, dtype=np.float32), sample_rate))
        self._idle_emitted = False

    def clear_queue(self):
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._current_audio = None
            self._current_pos = 0

    def stop_playback(self):
        """立即停止当前播放并清空队列"""
        self._stop_flag = True
        self.clear_queue()
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass

    def is_playing(self):
        with self._lock:
            if self._current_audio is not None and self._current_pos < len(self._current_audio):
                return True
            return not self._queue.empty()

    def has_pending_audio(self):
        return self.is_playing()

    def _audio_callback(self, outdata, frames, time_info, status):
        with self._lock:
            filled = 0
            while filled < len(outdata):
                if self._stop_flag:
                    outdata[filled:] = 0
                    return

                if self._current_audio is None or self._current_pos >= len(self._current_audio):
                    try:
                        audio, sr = self._queue.get_nowait()
                        # 动态重采样：如果音频采样率与播放采样率不同，重采样
                        if sr != self._playback_sr and sr > 0:
                            try:
                                import scipy.signal
                                num_samples = int(len(audio) * self._playback_sr / sr)
                                audio = scipy.signal.resample(audio, num_samples).astype(np.float32)
                            except ImportError:
                                # 无 scipy 时用线性插值
                                indices = np.linspace(0, len(audio) - 1, int(len(audio) * self._playback_sr / sr))
                                audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
                        self._current_audio = audio
                        self._current_pos = 0
                    except queue.Empty:
                        outdata[filled:] = 0
                        return

                remaining = len(self._current_audio) - self._current_pos
                need = len(outdata) - filled
                take = min(remaining, need)
                outdata[filled:filled + take, 0] = self._current_audio[self._current_pos:self._current_pos + take]
                self._current_pos += take
                filled += take

                if self._current_pos >= len(self._current_audio):
                    self._current_audio = None
                    self._current_pos = 0

    def run(self):
        if not HAS_SOUNDDEVICE:
            self.error.emit("sounddevice 未安装")
            return

        self._running = True
        self._stop_flag = False
        blocksize = 1024
        self._playback_sr = 22050  # 播放设备采样率

        try:
            self._stream = sd.OutputStream(
                device=self._device_index,
                samplerate=self._playback_sr,
                channels=1,
                dtype="float32",
                blocksize=blocksize,
                callback=self._audio_callback,
            )
            self._stream.start()

            while self._running:
                if self._stop_flag:
                    self._stop_flag = False
                    self.msleep(50)
                    continue

                playing = self.is_playing()
                if playing:
                    self.segment_started.emit()
                    self._idle_emitted = False
                else:
                    self.msleep(50)
                    if not self._queue.empty():
                        continue
                    if not self._running:
                        break
                    if self._current_audio is None and not self._idle_emitted:
                        self._idle_emitted = True
                        self.playback_finished.emit()
                    self.msleep(100)

                self.msleep(30)

        except Exception as e:
            self.error.emit(f"播放错误: {e}")
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            self._running = False

    def stop(self):
        self._running = False
        self.stop_playback()
        self.wait(3000)


class InterruptListener(QThread):
    """TTS 播放期间监听用户语音以触发打断"""

    interrupted = pyqtSignal()

    SAMPLE_RATE = 16000
    FRAME_MS = 30
    INTERRUPT_RMS = 2000       # RMS 阈值提高到 2000，避免 TTS 回声误触发
    INTERRUPT_FRAMES = 8       # 连续 8 帧（240ms）有声才触发，避免短噪声误触
    START_DELAY_MS = 1500      # TTS 开始播放后延迟 1.5 秒再监听，避免开头回声

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._device_index = None

    def set_device_index(self, index):
        self._device_index = index

    def start_listening(self):
        if self._device_index is None:
            self._device_index = find_bg_audio_device_index()
        self._active = True
        if not self.isRunning():
            self.start()

    def stop_listening(self):
        self._active = False

    def run(self):
        if not HAS_SOUNDDEVICE or not HAS_WEBRTCVAD:
            return

        # 启动延迟：等 TTS 声音稳定后再开始监听
        self.msleep(self.START_DELAY_MS)
        if not self._active:
            return

        frame_samples = int(self.SAMPLE_RATE * self.FRAME_MS / 1000)
        vad = webrtcvad.Vad(2)
        speech_count = 0

        try:
            with sd.InputStream(
                device=self._device_index,
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=frame_samples,
            ) as stream:
                while self._active:
                    data, _ = stream.read(frame_samples)
                    if not self._active:
                        break
                    frame = data.tobytes()
                    rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
                    if vad.is_speech(frame, self.SAMPLE_RATE) and rms > self.INTERRUPT_RMS:
                        speech_count += 1
                        if speech_count >= self.INTERRUPT_FRAMES:
                            self.interrupted.emit()
                            self._active = False
                            break
                    else:
                        speech_count = 0
        except Exception as e:
            print(f"[Interrupt] 监听错误: {e}")


# 向后兼容：旧版阻塞播放线程
class AudioPlayThread(QThread):
    """兼容旧 API 的阻塞播放线程"""

    playback_finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio = None
        self._sample_rate = 22050
        self._device_index = find_bg_output_device()

    def set_audio(self, audio_data, sample_rate, device_index=None):
        self._audio = audio_data
        self._sample_rate = sample_rate
        if device_index is not None:
            self._device_index = device_index

    def run(self):
        if self._audio is None or len(self._audio) == 0:
            return
        try:
            sd.play(self._audio, samplerate=self._sample_rate, device=self._device_index, blocking=True)
            self.playback_finished.emit()
        except Exception as e:
            self.error.emit(f"音频播放错误: {e}")
