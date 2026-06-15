"""内置 VLC 运行时 - 统一入口，实际逻辑在 vlc_bundle"""

import os

from ai.vlc_bundle import (
    find_vlc_exe,
    get_bundled_vlc_dir,
    get_bundled_vlc_exe,
    get_vlc_cwd,
    get_vlc_env,
    is_bundled_vlc_available,
    ensure_vlc_plugins_cache,
)


def is_vlc_available() -> bool:
    path, _ = find_vlc_exe()
    return path is not None


def find_vlc():
    path, _ = find_vlc_exe()
    return path


def get_vlc_launch_context(vlc_path: str):
    return get_vlc_env(vlc_path), get_vlc_cwd(vlc_path)


def get_vlc_status_text() -> str:
    if is_bundled_vlc_available():
        exe = get_bundled_vlc_exe()
        ensure_vlc_plugins_cache(exe)
        plugins_dat = os.path.join(get_bundled_vlc_dir() or "", "plugins", "plugins.dat")
        cache_ok = os.path.isfile(plugins_dat)
        size_mb = os.path.getsize(exe) / (1024 * 1024) if exe else 0
        cache_txt = "插件缓存已就绪" if cache_ok else "插件缓存未生成"
        return f"内置 VLC 已就绪 (vlc-3.0.20, {size_mb:.1f} MB, {cache_txt})"
    path, source = find_vlc_exe()
    if path:
        if source == "system":
            return f"使用系统 VLC: {os.path.basename(path)}"
        return f"✓ 内置 VLC: {path}"
    return "✗ 未找到 VLC，请确认 vlc-3.0.20 目录完整"
