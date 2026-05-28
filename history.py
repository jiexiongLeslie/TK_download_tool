"""
下载历史管理器 — 按 IP 隔离，基于 JSON 文件持久化
数据结构: {"ip1": {url: record, ...}, "ip2": {...}}
"""

import json
import time
from pathlib import Path

HISTORY_FILE = Path(__file__).parent / "download_history.json"
MAX_HISTORY_PER_IP = 200  # 每个 IP 最多保留记录数


def _load_all() -> dict:
    """加载全部历史，自动迁移旧格式"""
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

    # 检测并迁移旧格式 {url: record} → {"127.0.0.1": {url: record}}
    if data:
        sample_key = next(iter(data))
        if isinstance(data[sample_key], dict) and "url" in data[sample_key]:
            # 旧格式: key 是 URL，value 是 record
            data = {"_migrated_local": data}
            _save_all(data)
    return data


def _save_all(all_history: dict):
    """保存全部历史"""
    # 每个 IP 不超过上限
    for ip in list(all_history):
        records = all_history[ip]
        if len(records) > MAX_HISTORY_PER_IP:
            items = sorted(records.values(), key=lambda x: x.get("time", ""), reverse=True)
            all_history[ip] = {item["url"]: item for item in items[:MAX_HISTORY_PER_IP]}
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(all_history, f, ensure_ascii=False, indent=2)


def load_history(ip: str) -> dict:
    """加载指定 IP 的下载历史"""
    all_history = _load_all()
    return all_history.get(ip, {})


def all_history() -> dict:
    """加载全部历史（导出用）"""
    return _load_all()


def record_download(ip: str, url: str, job_id: str, title: str, filepath: str = ""):
    """记录一次下载"""
    all_history = _load_all()
    if ip not in all_history:
        all_history[ip] = {}
    all_history[ip][url] = {
        "url": url,
        "job_id": job_id,
        "title": title,
        "filepath": filepath,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_all(all_history)


def check_duplicates(ip: str, urls: list[str], save_dir: str = "") -> dict:
    """
    检查 URL 是否已被该 IP 下载过，且文件仍存在于磁盘
    返回: {"duplicates": [...], "new": [...]}
    """
    history = load_history(ip)
    duplicates = []
    new_urls = []

    for url in urls:
        if url in history and _file_still_exists(history[url].get("filepath", "")):
            duplicates.append({"url": url, "record": history[url]})
        else:
            new_urls.append(url)

    return {"duplicates": duplicates, "new": new_urls, "total_history": len(history)}


def _file_still_exists(filepath: str) -> bool:
    """检查文件是否仍在磁盘上"""
    if not filepath:
        return False
    try:
        return Path(filepath).is_file()
    except Exception:
        return False


def clear_ip_history(ip: str) -> int:
    """清除指定 IP 的下载历史，返回清除数量"""
    all_history = _load_all()
    count = len(all_history.get(ip, {}))
    if ip in all_history:
        del all_history[ip]
        _save_all(all_history)
    return count
