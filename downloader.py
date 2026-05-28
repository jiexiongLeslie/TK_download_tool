"""
TikTok 视频下载核心模块
优先使用 tikwm.com API（无需登录，已验证可行），yt-dlp 作为备选方案
"""

import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ========== 代理配置 ==========
# 默认代理地址，设为 None 则不走代理
DEFAULT_PROXY = "http://127.0.0.1:7897"


def _build_opener(proxy: str = None):
    """创建带代理的 urllib opener"""
    if proxy is None:
        proxy = DEFAULT_PROXY
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy,
            "https": proxy,
        })
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()


# ========== 全局进度追踪 ==========
_progress_store: dict[str, dict] = defaultdict(lambda: {
    "status": "pending",
    "percent": 0,
    "title": "",
    "filename": "",
    "filepath": "",
    "error": "",
    "url": "",
})


def get_progress(job_id: str = None):
    """获取下载进度"""
    if job_id:
        return _progress_store.get(job_id, {})
    return dict(_progress_store)


def extract_job_id(url: str) -> str:
    """从 TikTok URL 提取视频 ID"""
    m = re.search(r"/(video|photo|t)/(\d+)", url)
    if m:
        return m.group(2)
    m = re.search(r"vm\.tiktok\.com/(\w+)", url)
    if m:
        return m.group(1)
    return str(abs(hash(url)))[:12]


def _clean_filename(title: str, max_len: int = 80) -> str:
    """清理文件名中的非法字符"""
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", title)
    return safe[:max_len].strip()


# ========== 方法一：tikwm.com API（主方案） ==========
def _download_via_tikwm(url: str, save_dir: Path, job_id: str, proxy: str = None) -> dict:
    """通过 tikwm.com API 获取下载链接并下载"""
    opener = _build_opener(proxy)

    # Step 1: 调用 API 获取视频信息
    api_url = f"https://www.tikwm.com/api/?url={urllib.request.quote(url, safe='')}"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    try:
        resp = opener.open(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise Exception(f"API 请求失败（请确认代理 {proxy or DEFAULT_PROXY} 可用）: {e}")
    except json.JSONDecodeError as e:
        raise Exception(f"API 返回数据解析失败: {e}")

    if data.get("code") != 0:
        raise Exception(f"API 返回错误: {data.get('msg', '未知错误')}")

    video_info = data["data"]
    title = video_info.get("title", "untitled")
    video_url = video_info.get("wmplay") or video_info.get("play")  # 优先无水印

    if not video_url:
        raise Exception("未找到视频下载链接")

    _progress_store[job_id].update({
        "status": "downloading",
        "title": title,
    })

    # Step 2: 下载视频文件
    safe_title = _clean_filename(title)
    filename = f"{safe_title}_{job_id}.mp4"
    filepath = save_dir / filename

    dl_req = urllib.request.Request(video_url, headers={
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": "https://www.tiktok.com/",
    })

    resp2 = opener.open(dl_req, timeout=120)
    total = int(resp2.headers.get("Content-Length", 0))

    downloaded = 0
    chunk_size = 65536
    with open(filepath, "wb") as f:
        while True:
            chunk = resp2.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                _progress_store[job_id]["percent"] = round(downloaded / total * 100, 1)

    file_size = filepath.stat().st_size
    _progress_store[job_id].update({
        "status": "done",
        "percent": 100,
        "title": title,
        "filename": filename,
        "filepath": str(filepath),
        "filesize": file_size,
    })

    return {
        "job_id": job_id,
        "title": title,
        "filepath": str(filepath),
        "filesize": file_size,
        "status": "done",
        "method": "tikwm_api",
    }


# ========== 方法二：yt-dlp（备选方案） ==========
def _download_via_ytdlp(url: str, save_dir: Path, job_id: str, proxy: str = None) -> dict:
    """通过 yt-dlp 下载（需要浏览器 cookies 或有效期内的 token）"""
    try:
        import yt_dlp
    except ImportError:
        raise Exception("yt-dlp 未安装，请先安装: pip install yt-dlp")

    outtmpl = str(save_dir / "%(title).80s_%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        },
    }

    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "unknown")
            ext = info.get("ext", "mp4")
            filename = f"{_clean_filename(title)}_{info['id']}.{ext}"
            filepath = save_dir / filename

            if not filepath.exists():
                candidates = list(save_dir.glob(f"{_clean_filename(title)}_{info['id']}.*"))
                if candidates:
                    filepath = candidates[0]

            file_size = filepath.stat().st_size if filepath.exists() else 0
            _progress_store[job_id].update({
                "status": "done",
                "percent": 100,
                "title": title,
                "filename": filename,
                "filepath": str(filepath),
                "filesize": file_size,
            })

            return {
                "job_id": job_id,
                "title": title,
                "filepath": str(filepath),
                "filesize": file_size,
                "status": "done",
                "method": "yt_dlp",
            }

    except Exception as e:
        error_msg = str(e)
        # 常见错误提示优化
        if "login" in error_msg.lower() or "cookies" in error_msg.lower() or "impersonation" in error_msg.lower():
            error_msg = "需要 TikTok 登录认证。yt-dlp 方案不可用，请使用 tikwm 方案。"
        raise Exception(error_msg)


# ========== 主下载入口 ==========
def download_video(
    url: str,
    save_dir: str = None,
    proxy: str = None,
    prefer_method: str = "tikwm",  # tikwm | ytdlp | auto
) -> dict:
    """
    下载单个 TikTok 视频（自动选择最优方案）

    参数:
        url: TikTok 视频链接
        save_dir: 保存目录，默认 downloads/
        proxy: HTTP 代理地址，默认 127.0.0.1:7897
        prefer_method: 优先方案 tikwm / ytdlp / auto

    返回:
        dict: {"job_id": ..., "title": ..., "filepath": ..., "status": ..., "method": ...}
    """
    if save_dir is None:
        save_dir = DOWNLOADS_DIR
    else:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    job_id = extract_job_id(url)
    _progress_store[job_id].update({
        "url": url,
        "status": "pending",
        "percent": 0,
    })

    methods = []
    if prefer_method == "tikwm":
        methods = ["tikwm", "ytdlp"]
    elif prefer_method == "ytdlp":
        methods = ["ytdlp", "tikwm"]
    else:
        methods = ["tikwm", "ytdlp"]

    last_error = None

    for method in methods:
        try:
            if method == "tikwm":
                return _download_via_tikwm(url, save_dir, job_id, proxy)
            elif method == "ytdlp":
                return _download_via_ytdlp(url, save_dir, job_id, proxy)
        except Exception as e:
            last_error = str(e)
            continue

    # 全部失败
    _progress_store[job_id].update({
        "status": "error",
        "error": last_error or "所有下载方案均失败",
    })
    return {
        "job_id": job_id,
        "status": "error",
        "error": last_error or "所有下载方案均失败",
    }
