"""yt-dlp 音源解析 - 国内网易云优先，YouTube 仅作备用"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_CACHE_DIR = os.path.join(PROJECT_ROOT, "temp", "music_cache")

_NETEASE_SEARCH = "https://music.163.com/api/search/get/web"
_NETEASE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_NETEASE_REFERER = "https://music.163.com/"

_YTDLP_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestaudio/best",
    "noplaylist": True,
    "socket_timeout": 20,
}

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False


def _netease_headers() -> dict:
    return {"User-Agent": _NETEASE_UA, "Referer": _NETEASE_REFERER}


def is_netease_page(url: str) -> bool:
    return _is_netease_page(url)
    lower = (url or "").lower()
    return "music.163.com" in lower or "y.music.163.com" in lower


def _netease_page_url(song_id: int) -> str:
    return f"https://music.163.com/song?id={song_id}"


def search_netease(keyword: str) -> Tuple[str, Optional[str]]:
    """网易云搜索，返回 (标题, 歌曲页面URL)"""
    keyword = keyword.strip()
    if not keyword:
        return "", None
    try:
        params = {"s": keyword, "type": 1, "limit": 8}
        url = _NETEASE_SEARCH + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=_netease_headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        songs = data.get("result", {}).get("songs") or []
        if not songs:
            return "", None
        song = _pick_best_netease_match(keyword, songs)
        song_id = song.get("id")
        if not song_id:
            return "", None
        name = song.get("name", keyword)
        artists = song.get("artists") or []
        artist = artists[0].get("name", "") if artists else ""
        title = f"{name} - {artist}" if artist else name
        page = _netease_page_url(song_id)
        print(f"[Music] 网易云搜索: {title}")
        return title, page
    except Exception as e:
        print(f"[Music] 网易云搜索失败: {e}")
        return "", None


def _pick_best_netease_match(keyword: str, songs: list) -> dict:
    """在搜索结果中挑选更贴近用户歌名的条目"""
    kw = keyword.lower().replace(" ", "")
    best = songs[0]
    best_score = -1
    for song in songs:
        name = (song.get("name") or "").lower().replace(" ", "")
        artists = " ".join(a.get("name", "") for a in (song.get("artists") or []))
        artist = artists.lower().replace(" ", "")
        combined = name + artist
        score = 0
        for token in re.split(r"[\s\-—]+", keyword.lower()):
            token = token.strip()
            if not token:
                continue
            if token in combined or token in name or token in artist:
                score += 2
        if kw and (kw in combined or name in kw or kw in name):
            score += 3
        if score > best_score:
            best_score = score
            best = song
    return best


def _extract_via_module(page_or_query: str, *, is_youtube_search: bool = False) -> Tuple[str, Optional[str]]:
    opts = dict(_YTDLP_OPTS_BASE)
    if is_youtube_search:
        opts["default_search"] = "ytsearch1"
        target = f"ytsearch1:{page_or_query}"
    else:
        target = page_or_query
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
    if not info:
        return "", None
    entries = info.get("entries") or [info]
    entry = entries[0] if entries else info
    title = entry.get("title", page_or_query)
    url = entry.get("url") or entry.get("webpage_url")
    return title, url


def _parse_ytdlp_json(stdout: str) -> Tuple[str, Optional[str]]:
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        title = info.get("title", "")
        url = info.get("url") or info.get("webpage_url")
        return title, url
    return "", None


def _extract_via_subprocess(target: str) -> Tuple[str, Optional[str]]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "-j", "--no-playlist",
             "-f", "bestaudio/best", target],
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode != 0:
            print(f"[yt-dlp] 子进程失败: {proc.stderr[:200]}")
            return "", None
        return _parse_ytdlp_json(proc.stdout)
    except Exception as e:
        print(f"[yt-dlp] 子进程异常: {e}")
        return "", None


def _extract_page_url(page_url: str) -> Tuple[str, Optional[str]]:
    if HAS_YTDLP:
        try:
            return _extract_via_module(page_url, is_youtube_search=False)
        except Exception as e:
            print(f"[yt-dlp] 提取失败: {e}")
    return _extract_via_subprocess(page_url)


def is_ytdlp_available() -> bool:
    if HAS_YTDLP:
        return True
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return proc.returncode == 0
    except Exception:
        return False


def search_audio(keyword: str) -> Tuple[str, Optional[str]]:
    """按歌名搜索可播放直链：网易云优先，YouTube 备用"""
    keyword = keyword.strip()
    if not keyword:
        return "", None

    title, page = search_netease(keyword)
    if page:
        t, url = _extract_page_url(page)
        if url and not _is_youtube_page(url):
            return t or title, url

    print(f"[Music] 网易云未命中，尝试 YouTube: {keyword}")
    if HAS_YTDLP:
        try:
            return _extract_via_module(keyword, is_youtube_search=True)
        except Exception as e:
            print(f"[yt-dlp] YouTube 搜索失败: {e}")
    return _extract_via_subprocess(f"ytsearch1:{keyword}")


def extract_audio_url(page_url: str) -> Tuple[str, Optional[str]]:
    """从歌曲页面 URL 提取直链"""
    return _extract_page_url(page_url)


def _is_youtube_page(url: str) -> bool:
    lower = (url or "").lower()
    return (
        "youtube.com/watch" in lower
        or "youtube.com/results" in lower
        or ("youtu.be/" in lower and "googlevideo" not in lower)
    )


def _cleanup_music_cache(max_files: int = 12, max_age_hours: float = 24) -> None:
    try:
        if not os.path.isdir(MUSIC_CACHE_DIR):
            return
        entries = []
        for name in os.listdir(MUSIC_CACHE_DIR):
            path = os.path.join(MUSIC_CACHE_DIR, name)
            if os.path.isfile(path):
                entries.append((os.path.getmtime(path), path))
        entries.sort(reverse=True)
        cutoff = time.time() - max_age_hours * 3600
        for idx, (mtime, path) in enumerate(entries):
            if idx >= max_files or mtime < cutoff:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except Exception:
        pass


def _download_page(page_url: str) -> Tuple[str, Optional[str]]:
    os.makedirs(MUSIC_CACHE_DIR, exist_ok=True)
    opts = dict(_YTDLP_OPTS_BASE)
    opts["outtmpl"] = os.path.join(MUSIC_CACHE_DIR, "%(id)s.%(ext)s")
    if HAS_YTDLP:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(page_url, download=True)
            if not info:
                return "", None
            title = info.get("title", "")
            filepath = info.get("filepath") or ydl.prepare_filename(info)
        if filepath and os.path.isfile(filepath):
            _cleanup_music_cache()
            return title, os.path.abspath(filepath)
        return title, None

    proc = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "-f", "bestaudio/best",
         "-o", opts["outtmpl"], page_url],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode != 0:
        print(f"[yt-dlp] 下载失败: {proc.stderr[:200]}")
        return "", None
    title, _ = _parse_ytdlp_json(proc.stdout)
    song_id = re.search(r"id=(\d+)", page_url)
    if song_id:
        for name in os.listdir(MUSIC_CACHE_DIR):
            if name.startswith(song_id.group(1)):
                path = os.path.join(MUSIC_CACHE_DIR, name)
                if os.path.isfile(path):
                    _cleanup_music_cache()
                    return title, os.path.abspath(path)
    return title, None


def download_audio_to_cache(keyword: str, page_url: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """下载音频到本地缓存，国内网络下比直链更稳"""
    keyword = keyword.strip()
    if not keyword and not page_url:
        return "", None
    if not is_ytdlp_available():
        return "", None

    if not page_url:
        title, page_url = search_netease(keyword)
        if not page_url:
            print(f"[Music] 网易云下载失败，尝试 YouTube: {keyword}")
            page_url = f"ytsearch1:{keyword}"
    else:
        title = keyword

    try:
        t, path = _download_page(page_url)
        if path:
            print(f"[Music] 已缓存: {t or title}")
            return t or title, path
    except Exception as e:
        print(f"[yt-dlp] 下载异常: {e}")

    if page_url and not page_url.startswith("ytsearch1:"):
        return "", None

    try:
        if HAS_YTDLP:
            opts = dict(_YTDLP_OPTS_BASE)
            opts["default_search"] = "ytsearch1"
            opts["outtmpl"] = os.path.join(MUSIC_CACHE_DIR, "%(id)s.%(ext)s")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{keyword}", download=True)
                if not info:
                    return "", None
                entries = info.get("entries") or [info]
                entry = entries[0] if entries else info
                title = entry.get("title", keyword)
                filepath = entry.get("filepath") or ydl.prepare_filename(entry)
            if filepath and os.path.isfile(filepath):
                _cleanup_music_cache()
                return title, os.path.abspath(filepath)
    except Exception as e:
        print(f"[yt-dlp] YouTube 下载失败: {e}")
    return "", None
