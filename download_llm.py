"""下载 Qwen2.5 GGUF 量化模型（支持多模型、断点续传、自动重试）"""

import argparse
import ssl
import sys
import os
import time
import warnings

# 确保可导入 ai 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ssl._create_default_https_context = ssl._create_unverified_context

# 抑制 SSL 警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ai.llm_models import (
    LLM_MODELS, DEFAULT_MODEL_ID, LLM_MODELS_DIR,
    get_model_path, get_download_urls, get_model_info, is_model_downloaded,
    get_model_filenames,
)

MAX_RETRIES = 10  # 单个文件最大重试次数


def _create_session() -> requests.Session:
    """创建带重试策略的 requests Session"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.verify = False
    return session


def download_with_progress(url: str, save_path: str) -> bool:
    """下载文件，支持断点续传和自动重试"""
    tmp_path = save_path + ".tmp"
    chunk_size = 1024 * 1024  # 1MB

    for attempt in range(1, MAX_RETRIES + 1):
        session = _create_session()
        downloaded = 0

        # 检查是否有未完成的下载
        if os.path.exists(tmp_path):
            downloaded = os.path.getsize(tmp_path)
            if downloaded > 0:
                print(f"续传: 已有 {downloaded / (1024**3):.2f} GB，从断点继续...")

        try:
            headers = {}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            resp = session.get(url, stream=True, headers=headers, timeout=120)
            if resp.status_code == 416:
                # Range 不满足，从头开始
                downloaded = 0
                resp = session.get(url, stream=True, timeout=120)
            resp.raise_for_status()

            # 确定总大小
            if resp.status_code == 206:
                # 部分内容，从 Range 头获取总大小
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    total = int(content_range.split("/")[1])
                else:
                    total = downloaded + int(resp.headers.get("content-length", 0))
            else:
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0  # 服务器不支持 Range，从头开始

            mode = "ab" if downloaded > 0 else "wb"
            last_pct = int(downloaded / total * 100) if total > 0 else -1

            with open(tmp_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        f.flush()  # 确保写入磁盘
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded / total * 100)
                            if pct != last_pct:
                                size_gb = downloaded / (1024**3)
                                total_gb = total / (1024**3)
                                bar_len = 30
                                filled = int(bar_len * downloaded / total)
                                bar = "█" * filled + "░" * (bar_len - filled)
                                print(f"[{bar}] {pct}%  {size_gb:.2f}/{total_gb:.2f} GB")
                                last_pct = pct
                        else:
                            if downloaded % (100 * 1024 * 1024) < chunk_size:
                                print(f"已下载: {downloaded / (1024**3):.2f} GB")

            # 下载完成，重命名
            if os.path.exists(save_path):
                os.remove(save_path)
            os.rename(tmp_path, save_path)
            final_size = os.path.getsize(save_path)
            print(f"下载完成! 文件大小: {final_size / (1024**3):.2f} GB")
            return True

        except (requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ConnectionResetError,
                OSError) as e:
            print(f"\n连接中断: {e}")
            if attempt < MAX_RETRIES:
                wait = min(attempt * 3, 30)  # 递增等待，最多30秒
                print(f"第 {attempt}/{MAX_RETRIES} 次重试，{wait}秒后继续...")
                time.sleep(wait)
                continue
            else:
                print(f"已达到最大重试次数 ({MAX_RETRIES})，下载失败")
                # 保留 tmp 文件以便下次续传
                return False

        except Exception as e:
            print(f"\n下载出错: {e}")
            if attempt < MAX_RETRIES:
                wait = min(attempt * 3, 30)
                print(f"第 {attempt}/{MAX_RETRIES} 次重试，{wait}秒后继续...")
                time.sleep(wait)
                continue
            else:
                return False

    return False


def download_model(model_id: str) -> bool:
    if model_id not in LLM_MODELS:
        print(f"未知模型: {model_id}")
        print(f"可用: {', '.join(LLM_MODELS.keys())}")
        return False

    info = get_model_info(model_id)
    os.makedirs(LLM_MODELS_DIR, exist_ok=True)

    if is_model_downloaded(model_id):
        print(f"模型已存在: {info['name']}")
        print(f"路径: {LLM_MODELS_DIR}")
        return True

    print(f"开始下载: {info['name']} ({info['size']})")
    file_urls = get_download_urls(model_id)  # [(filename, mirror, official), ...]

    for filename, mirror, official in file_urls:
        save_path = os.path.join(LLM_MODELS_DIR, filename)
        if os.path.isfile(save_path) and os.path.getsize(save_path) > 1024 * 1024:
            print(f"文件已存在，跳过: {filename}")
            continue

        print(f"\n--- 下载文件: {filename} ---")
        success = False
        for url in (mirror, official):
            print(f"下载源: {url}")
            if download_with_progress(url, save_path):
                success = True
                break
            print("尝试下一个下载源...")

        if not success:
            # 保留 tmp 文件以便下次续传，不删除
            print(f"文件 {filename} 下载失败（已保留临时文件，下次可续传）")
            return False

    # 所有文件下载完成
    if is_model_downloaded(model_id):
        print(f"\n模型 {info['name']} 下载完成！")
        return True
    else:
        print("下载完成但文件校验失败")
        return False


def main():
    parser = argparse.ArgumentParser(description="下载 BGAICard LLM 模型")
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL_ID,
        choices=list(LLM_MODELS.keys()),
        help="模型 ID（默认内置基础版 qwen2.5-1.5b）",
    )
    parser.add_argument("--list", action="store_true", help="列出所有可用模型")
    args = parser.parse_args()

    if args.list:
        print("可用模型:")
        for mid, info in LLM_MODELS.items():
            tag = "内置" if info.get("builtin") else "可选"
            status = "已下载" if is_model_downloaded(mid) else "未下载"
            print(f"  {mid:16} [{tag}] [{status}] {info['name']} ({info['size']})")
        return

    if not download_model(args.model):
        print("下载失败，请检查网络后重试。已下载的部分会自动续传。")
        sys.exit(1)


if __name__ == "__main__":
    main()
