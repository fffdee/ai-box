"""在线音乐播放器 - 内置 VLC 本地播放（不跳转浏览器）"""

import os
import subprocess
import threading
from typing import Optional

from ai.vlc_bundle import (
    find_vlc_exe, get_vlc_env, get_vlc_cwd, is_bundled_vlc_available,
    ensure_vlc_ready, build_vlc_command,
)
from ai.ytdlp_helper import (
    search_audio, extract_audio_url, is_ytdlp_available,
    download_audio_to_cache, search_netease, is_netease_page,
)


class OnlineMusicPlayer:
    """联网搜歌 + 内置 VLC 本地播放，绝不跳转浏览器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_once()
        return cls._instance

    def _init_once(self):
        self._process = None
        self._rc_stdin = None
        self._current_title = ""
        self._proc_lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        with self._proc_lock:
            if self._process is None:
                return False
            return self._process.poll() is None

    @property
    def current_title(self) -> str:
        return self._current_title

    def play(self, keyword: str) -> str:
        keyword = keyword.strip()
        if not keyword:
            return "未指定播放内容"

        vlc = self._find_vlc()
        if not vlc:
            return "未找到内置 VLC，请确认 vlc-3.0.20 目录完整"

        # 确保 plugins.dat 已生成（否则报找不到插件）
        ensure_vlc_ready()

        if not is_ytdlp_available():
            return "本地播放需要 yt-dlp，请运行: pip install yt-dlp"

        # 国内网络：优先网易云下载到本地再播，避免 YouTube/CDN 直链失败
        print(f"[Music] 正在准备音源: {keyword}")
        dl_title, local_path = download_audio_to_cache(keyword)
        if local_path:
            self._current_title = dl_title or keyword
            err = self._play_vlc(vlc, local_path, self._current_title)
            if not err:
                return f"正在本地播放：{self._current_title}"
            print(f"[Music] 缓存播放失败，尝试直链: {err}")

        title, stream_url = self._resolve_stream(keyword)
        if not stream_url:
            return f"未找到可播放的音源：{keyword}，请换首歌试试"

        self._current_title = title or keyword
        err = self._play_vlc(vlc, stream_url, self._current_title)
        if err:
            print(f"[Music] 直链播放失败: {err}")
            dl_title, local_path = download_audio_to_cache(keyword)
            if local_path:
                self._current_title = dl_title or self._current_title
                err = self._play_vlc(vlc, local_path, self._current_title)
        if err:
            return err
        return f"正在本地播放：{self._current_title}"

    def pause(self) -> str:
        if self._send_vlc("pause"):
            return "已暂停/继续播放"
        return "当前没有正在播放的音乐"

    def stop(self) -> str:
        with self._proc_lock:
            if self._process is not None:
                try:
                    self._send_vlc("stop")
                    self._process.terminate()
                    self._process.wait(timeout=3)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None
                self._rc_stdin = None
                self._current_title = ""
                return "已停止播放"
        return "当前没有正在播放的音乐"

    def next_track(self) -> str:
        if self._send_vlc("next"):
            return "已切换到下一首"
        return "当前播放器不支持切歌，请重新说歌名播放"

    def _resolve_stream(self, keyword: str) -> tuple:
        """解析可播放直链，绝不打开浏览器"""
        if keyword.startswith(("http://", "https://")):
            if is_netease_page(keyword):
                return extract_audio_url(keyword)
            if "youtube.com" in keyword or "youtu.be" in keyword:
                return extract_audio_url(keyword)
            return keyword, keyword

        # 网易云直链（备用，主路径已走下载缓存）
        title, page = search_netease(keyword)
        if page:
            t, stream = extract_audio_url(page)
            if stream and self._is_direct_stream(stream):
                return t or title, stream

        title, url = search_audio(keyword)
        if url and self._is_direct_stream(url):
            return title, url

        return keyword, None

    def _is_direct_stream(self, url: str) -> bool:
        """可直链播放的 URL（排除 YouTube 页面链接）"""
        if not url or not url.startswith("http"):
            return False
        lower = url.lower()
        if "youtube.com/watch" in lower or "youtube.com/results" in lower:
            return False
        if "youtu.be/" in lower and "googlevideo" not in lower:
            return False
        return True

    def _find_vlc(self) -> Optional[str]:
        path, _ = find_vlc_exe()
        return path

    def _is_stream_error(self, err: str) -> bool:
        lower = err.lower()
        markers = (
            "tls", "handshake", "http connection", "connection timed out",
            "access stream error", "403", "404", "connection failure",
        )
        return any(m in lower for m in markers)

    def _start_stderr_watcher(self, proc: subprocess.Popen, on_error) -> threading.Thread:
        def _watch():
            try:
                chunks = []
                while proc.poll() is None:
                    line = proc.stderr.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    chunks.append(text)
                    if self._is_stream_error(text):
                        on_error("".join(chunks))
                        return
                rest = proc.stderr.read()
                if rest:
                    chunks.append(rest.decode("utf-8", errors="replace"))
                joined = "".join(chunks)
                if joined and self._is_stream_error(joined):
                    on_error(joined)
            except Exception:
                pass

        t = threading.Thread(target=_watch, daemon=True)
        t.start()
        return t

    def _play_vlc(self, vlc_path: str, url: str, title: str) -> Optional[str]:
        self.stop()
        with self._proc_lock:
            try:
                vlc_args = build_vlc_command(vlc_path, url, title)
                env = get_vlc_env(vlc_path)
                cwd = get_vlc_cwd(vlc_path)

                stream_error = {"msg": ""}

                def _on_stream_error(msg: str):
                    stream_error["msg"] = msg

                self._process = subprocess.Popen(
                    vlc_args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
                self._rc_stdin = self._process.stdin
                watcher = self._start_stderr_watcher(self._process, _on_stream_error)

                import time
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if self._process.poll() is not None:
                        break
                    if stream_error["msg"]:
                        break
                    time.sleep(0.2)
                watcher.join(timeout=0.5)

                if stream_error["msg"]:
                    self._terminate_process()
                    return f"音源连接失败: {stream_error['msg'][:160]}"

                if self._process.poll() is not None:
                    err = ""
                    try:
                        err = self._process.stderr.read(4000).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                    if "plugin" in err.lower() or "模块" in err:
                        ensure_vlc_ready()
                    return f"VLC 启动失败: {err[:160] or '进程已退出'}"

                src = "内置VLC" if is_bundled_vlc_available() else "系统VLC"
                mode = "缓存文件" if not url.startswith(("http://", "https://")) else "直链"
                print(f"[Music] {src} {mode}播放: {title}")
                if url.startswith(("http://", "https://")):
                    print(f"[Music] URL: {url[:80]}...")
                return None
            except Exception as e:
                return f"VLC 播放失败: {e}"

    def _terminate_process(self):
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=3)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None
        self._rc_stdin = None

    def _send_vlc(self, command: str) -> bool:
        try:
            if self._rc_stdin is not None:
                self._rc_stdin.write(command.encode() + b"\n")
                self._rc_stdin.flush()
                return True
        except Exception:
            pass
        return False


_player = OnlineMusicPlayer()


def music_play(keyword: str) -> str:
    return _player.play(keyword)


def music_pause() -> str:
    return _player.pause()


def music_stop() -> str:
    return _player.stop()


def music_next() -> str:
    return _player.next_track()


def is_music_playing() -> bool:
    return _player.is_playing


def get_now_playing() -> str:
    return _player.current_title
