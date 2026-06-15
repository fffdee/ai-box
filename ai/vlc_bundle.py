"""内置 VLC 路径解析与初始化 - 优先使用项目自带的便携版 VLC"""

import glob
import os
import subprocess
from typing import Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_bundled_vlc_dir() -> Optional[str]:
    """返回内置 VLC 目录（含 plugins）"""
    candidates = [
        os.path.join(PROJECT_ROOT, "vlc-3.0.20"),
        os.path.join(PROJECT_ROOT, "vlc"),
    ]
    for d in candidates:
        if os.path.isfile(os.path.join(d, "vlc.exe")):
            return os.path.abspath(d)
    for path in sorted(glob.glob(os.path.join(PROJECT_ROOT, "vlc-*"))):
        if os.path.isfile(os.path.join(path, "vlc.exe")):
            return os.path.abspath(path)
    return None


def get_bundled_vlc_exe() -> Optional[str]:
    vlc_dir = get_bundled_vlc_dir()
    if vlc_dir:
        return os.path.join(vlc_dir, "vlc.exe")
    return None


def is_bundled_vlc_available() -> bool:
    return get_bundled_vlc_exe() is not None


def find_vlc_exe() -> Tuple[Optional[str], str]:
    """查找 VLC 可执行文件，返回 (路径, 来源)"""
    bundled = get_bundled_vlc_exe()
    if bundled:
        return bundled, "bundled"

    for path in (
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ):
        if os.path.isfile(path):
            return path, "system"

    import shutil
    which = shutil.which("vlc")
    if which:
        return which, "system"

    return None, "none"


def _plugins_dir(vlc_dir: str) -> str:
    return os.path.join(vlc_dir, "plugins")


def ensure_vlc_plugins_cache(vlc_exe: str) -> bool:
    """
    生成 plugins.dat 缓存（便携版 VLC 首次运行必需）。
    缺少此文件会报「找不到插件」。
    """
    vlc_dir = os.path.dirname(os.path.abspath(vlc_exe))
    plugins = _plugins_dir(vlc_dir)
    plugins_dat = os.path.join(plugins, "plugins.dat")

    if os.path.isfile(plugins_dat) and os.path.getsize(plugins_dat) > 0:
        return True

    cache_gen = os.path.join(vlc_dir, "vlc-cache-gen.exe")
    if not os.path.isfile(cache_gen):
        print("[VLC] 警告: 未找到 vlc-cache-gen.exe，无法生成 plugins.dat")
        return os.path.isdir(plugins)

    try:
        print(f"[VLC] 正在生成插件缓存: {plugins}")
        proc = subprocess.run(
            [cache_gen, plugins],
            cwd=vlc_dir,
            capture_output=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        ok = proc.returncode == 0 and os.path.isfile(plugins_dat)
        if ok:
            print("[VLC] 插件缓存生成成功")
        else:
            err = proc.stderr.decode("utf-8", errors="replace")[:300]
            print(f"[VLC] 插件缓存生成失败: {err}")
        return ok
    except Exception as e:
        print(f"[VLC] 插件缓存生成异常: {e}")
        return False


def ensure_vlc_ready() -> Tuple[Optional[str], str]:
    """确保 VLC 可用且插件缓存就绪"""
    vlc_exe, source = find_vlc_exe()
    if not vlc_exe:
        return None, "none"
    if source == "bundled":
        ensure_vlc_plugins_cache(vlc_exe)
    return vlc_exe, source


def get_vlc_env(vlc_exe: str) -> dict:
    """为便携版 VLC 准备环境变量（绝对路径）"""
    env = os.environ.copy()
    vlc_dir = os.path.dirname(os.path.abspath(vlc_exe))
    plugins = _plugins_dir(vlc_dir)

    if os.path.isdir(plugins):
        env["VLC_PLUGIN_PATH"] = plugins
    env["VLC_DATA_PATH"] = vlc_dir

    # 确保 libvlc.dll 等依赖可被找到
    path = env.get("PATH", "")
    if vlc_dir not in path:
        env["PATH"] = vlc_dir + os.pathsep + path

    return env


def get_vlc_cwd(vlc_exe: str) -> str:
    """VLC 必须从自身目录启动以正确加载 plugins"""
    return os.path.dirname(os.path.abspath(vlc_exe))


# 远程音源流 HTTP 头（国内 CDN / YouTube）
_STREAM_HEADERS = {
    "youtube": (
        "https://www.youtube.com/",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ),
    "netease": (
        "https://music.163.com/",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ),
}


def _stream_header_profile(url: str) -> Optional[str]:
    if not url or not url.startswith(("http://", "https://")):
        return None
    lower = url.lower()
    if "googlevideo.com" in lower or "youtube.com" in lower or "youtu.be/" in lower:
        return "youtube"
    if "music.126.net" in lower or "music.163.com" in lower:
        return "netease"
    return None


def url_needs_stream_headers(url: str) -> bool:
    """远程音源流是否需要额外 HTTP 头"""
    return _stream_header_profile(url) is not None


def build_vlc_command(vlc_exe: str, url: str, title: str) -> list:
    """
    构建 VLC 启动参数。
    注意: 内置 VLC 3.0.20 不支持 --rc-fake-tty，使用 dummy+extraintf rc。
    """
    args = [
        os.path.abspath(vlc_exe),
        "--intf", "dummy",
        "--extraintf", "rc",
        "--no-video",
        "--no-video-title-show",
        "--no-qt-error-dialogs",
        "--meta-title", title,
    ]
    profile = _stream_header_profile(url)
    if profile:
        referrer, user_agent = _STREAM_HEADERS[profile]
        args.extend([
            "--http-referrer", referrer,
            "--http-user-agent", user_agent,
        ])
    args.append(url)
    return args
