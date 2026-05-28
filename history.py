"""
下载历史管理器 — 基于 JSON 文件持久化
"""

import json
import time
from pathlib import Path
from collections import OrderedDict

HISTORY_FILE = Path(__file__).parent / "download_history.json"
MAX_HISTORY = 500  # 最多保留记录数


def load_history() -> dict:
    """加载下载历史"""
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_history(history: dict):
    """保存下载历史，超过上限时清理旧记录"""
    if len(history) > MAX_HISTORY:
        # 保留最新的 MAX_HISTORY 条
        items = sorted(history.values(), key=lambda x: x.get("time", ""), reverse=True)
        history = {item["url"]: item for item in items[:MAX_HISTORY]}
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def record_download(url: str, job_id: str, title: str, filepath: str = ""):
    """记录一次下载"""
    history = load_history()
    history[url] = {
        "url": url,
        "job_id": job_id,
        "title": title,
        "filepath": filepath,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_history(history)


def check_duplicates(urls: list[str]) -> dict:
    """
    检查 URL 是否已下载过
    返回: {"duplicates": [...], "new": [...]}
    """
    history = load_history()
    duplicates = []
    new_urls = []

    for url in urls:
        if url in history:
            duplicates.append({"url": url, "record": history[url]})
        else:
            new_urls.append(url)

    return {"duplicates": duplicates, "new": new_urls, "total_history": len(history)}
