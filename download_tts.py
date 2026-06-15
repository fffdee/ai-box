"""下载 sherpa-onnx 中文 TTS 模型 (vits-zh-ll)"""

import os
import ssl
import sys
import requests

# 禁用 SSL 验证
ssl._create_default_https_context = ssl._create_unverified_context

# 配置
MIRROR = "https://hf-mirror.com"
REPO = "csukuangfj/sherpa-onnx-vits-zh-ll"
SAVE_DIR = r"E:\DeepLearn\BGAICard\tts-models\vits-zh-ll"

# 核心模型文件
REQUIRED_FILES = [
    "model.onnx",
    "tokens.txt",
    "lexicon.txt",
]

# 中文文本规范化所需文件 (FST + jieba 分词字典)
EXTRA_FILES = [
    "date.fst",
    "number.fst",
    "phone.fst",
    "new_heteronym.fst",
    "G_multisperaker_latest.json",
    "dict/jieba.dict.utf8",
    "dict/hmm_model.utf8",
    "dict/user.dict.utf8",
    "dict/idf.utf8",
    "dict/stop_words.utf8",
    "dict/pos_dict/char_state_tab.utf8",
    "dict/pos_dict/prob_emit.utf8",
    "dict/pos_dict/prob_start.utf8",
    "dict/pos_dict/prob_trans.utf8",
]


def get_repo_file_list():
    """通过 API 获取仓库文件列表"""
    api_url = f"{MIRROR}/api/models/{REPO}"
    print(f"正在获取文件列表: {api_url}")
    resp = requests.get(api_url, verify=False, proxies=None, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    files = []
    siblings = data.get("siblings", [])
    for s in siblings:
        rfname = s.get("rfilename", "")
        fsize = s.get("size", 0)
        files.append((rfname, fsize))
    return files


def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def download_file(filename, save_dir):
    """下载单个文件，显示进度"""
    url = f"{MIRROR}/{REPO}/resolve/main/{filename}"
    save_path = os.path.join(save_dir, filename)

    # 确保子目录存在
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    if os.path.exists(save_path):
        print(f"  [跳过] {filename} 已存在")
        return True

    print(f"  正在下载: {filename}")
    print(f"  URL: {url}")

    try:
        resp = requests.get(url, verify=False, proxies=None, stream=True, timeout=60)
        resp.raise_for_status()

        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        block_size = 8192

        # 临时文件
        tmp_path = save_path + ".tmp"
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = downloaded / total_size * 100
                        bar_len = 40
                        filled = int(bar_len * downloaded / total_size)
                        bar = "█" * filled + "░" * (bar_len - filled)
                        sys.stdout.write(
                            f"\r  [{bar}] {pct:.1f}% ({format_size(downloaded)}/{format_size(total_size)})"
                        )
                        sys.stdout.flush()
                    else:
                        sys.stdout.write(f"\r  已下载: {format_size(downloaded)}")
                        sys.stdout.flush()

        print()  # 换行

        # 重命名临时文件
        os.rename(tmp_path, save_path)
        print(f"  [完成] {filename} -> {save_path}")
        return True

    except Exception as e:
        print(f"\n  [错误] 下载 {filename} 失败: {e}")
        # 清理临时文件
        tmp_path = save_path + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def main():
    # 创建目录
    os.makedirs(SAVE_DIR, exist_ok=True)
    print(f"保存目录: {SAVE_DIR}\n")

    # 获取文件列表
    try:
        all_files = get_repo_file_list()
        print(f"仓库文件列表 ({len(all_files)} 个):")
        for fname, fsize in all_files:
            print(f"  {fname} ({format_size(fsize)})")
        print()
    except Exception as e:
        print(f"获取文件列表失败: {e}")
        print("将只下载预设的必要文件\n")

    # 下载核心文件
    print("=" * 60)
    print("开始下载核心模型文件")
    print("=" * 60)

    success = 0
    fail = 0
    for fname in REQUIRED_FILES:
        if download_file(fname, SAVE_DIR):
            success += 1
        else:
            fail += 1
        print()

    # 下载额外文件
    print("=" * 60)
    print("开始下载中文文本规范化文件 (FST + jieba)")
    print("=" * 60)

    for fname in EXTRA_FILES:
        if download_file(fname, SAVE_DIR):
            success += 1
        else:
            fail += 1
        print()

    print("=" * 60)
    print(f"下载完成: 成功 {success}, 失败 {fail}")
    print(f"文件保存在: {SAVE_DIR}")
    print("=" * 60)

    # 列出已下载的文件
    print("\n已下载文件:")
    for root, dirs, files in os.walk(SAVE_DIR):
        rel = os.path.relpath(root, SAVE_DIR)
        for f in sorted(files):
            fpath = os.path.join(root, f)
            display = f if rel == "." else os.path.join(rel, f)
            print(f"  {display} ({format_size(os.path.getsize(fpath))})")


if __name__ == "__main__":
    # 抑制 SSL 警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()
