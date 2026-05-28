"""
TikTok / 多平台视频下载核心模块
TikTok: tikwm.com API（无需登录）
其他平台: yt-dlp（YouTube Shorts / Instagram Reels / Bilibili 等）
"""

import os
import re
import json
import time
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


# ========== 重试配置 ==========
MAX_RETRIES = 2       # 失败后最大重试次数
RETRY_DELAY = 2        # 初始重试延迟（秒），每次翻倍


def _retry_with_backoff(func, *args, **kwargs):
    """带退避的重试执行"""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = str(e)
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
    raise Exception(f"重试 {MAX_RETRIES} 次后仍失败: {last_error}")


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
    """从 URL 提取视频 ID"""
    # TikTok
    m = re.search(r"/(video|photo|t)/(\d+)", url)
    if m:
        return m.group(2)
    m = re.search(r"vm\.tiktok\.com/(\w+)", url)
    if m:
        return m.group(1)
    # Instagram Reel
    m = re.search(r"instagram\.com/(reel|p)/([\w-]+)", url)
    if m:
        return f"ig_{m.group(2)}"
    # YouTube Shorts
    m = re.search(r"youtube\.com/shorts/([\w-]+)", url)
    if m:
        return f"yt_{m.group(1)}"
    # YouTube 普通视频
    m = re.search(r"[?&]v=([\w-]+)", url)
    if m:
        return f"yt_{m.group(1)}"
    m = re.search(r"youtu\.be/([\w-]+)", url)
    if m:
        return f"yt_{m.group(1)}"
    # Bilibili
    m = re.search(r"bilibili\.com/video/(BV[\w]+)", url)
    if m:
        return f"bili_{m.group(1)}"
    # 通用 fallback
    return str(abs(hash(url)))[:12]


def detect_platform(url: str) -> str:
    """自动识别视频平台"""
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "instagram.com" in url_lower:
        return "instagram"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "bilibili.com" in url_lower:
        return "bilibili"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    return "unknown"


def _clean_filename(title: str, max_len: int = 80) -> str:
    """清理文件名中的非法字符"""
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", title)
    return safe[:max_len].strip()


def _unique_filepath(save_dir: Path, safe_title: str, job_id: str) -> Path:
    """生成不冲突的文件名，已存在则添加序号"""
    base = f"{safe_title}_{job_id}"
    filepath = save_dir / f"{base}.mp4"
    if not filepath.exists():
        return filepath

    # 文件已存在，尝试加序号
    counter = 1
    while True:
        filepath = save_dir / f"{base}_{counter}.mp4"
        if not filepath.exists():
            return filepath
        counter += 1
        if counter > 99:  # 安全上限
            suffix = str(abs(hash(str(counter))))[:6]
            filepath = save_dir / f"{base}_{suffix}.mp4"
            return filepath


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
    # 无水印优先：hdplay(高清) > play(标清)，避开 wmplay(水印)
    video_url = video_info.get("hdplay") or video_info.get("play")

    if not video_url:
        raise Exception("未找到视频下载链接")

    _progress_store[job_id].update({
        "status": "downloading",
        "title": title,
    })

    # Step 2: 下载视频文件（避免覆盖已有文件）
    safe_title = _clean_filename(title)
    filepath = _unique_filepath(save_dir, safe_title, job_id)
    filename = filepath.name

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
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",  # 优先合并为 mp4，失败则保持原格式
        "noplaylist": True,
        "overwrites": False,  # 不覆盖已有文件
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
        # 平台特定错误提示优化
        if "login" in error_msg.lower() or "cookies" in error_msg.lower():
            error_msg = "需要登录认证，yt-dlp 方案不可用。"
        elif "instagram" in error_msg.lower() and ("empty" in error_msg.lower() or "granting" in error_msg.lower()):
            error_msg = "Instagram 需要登录认证（或该帖子为私密/不存在）。请使用 --cookies 或浏览器登录后重试。"
        elif "javascript" in error_msg.lower() or "js runtime" in error_msg.lower():
            error_msg = "建议安装 Node.js 以获得更好的 YouTube 支持（非必须）。"
        elif "ffmpeg" in error_msg.lower():
            error_msg = "建议安装 FFmpeg 以获得最佳视频质量。当前使用备选格式下载。"
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
    # 重置进度（避免同一视频重复下载时残留旧状态）
    _progress_store[job_id] = {
        "status": "pending",
        "percent": 0,
        "title": "",
        "filename": "",
        "filepath": "",
        "error": "",
        "url": url,
    }

    # 智能平台路由
    platform = detect_platform(url)
    methods = []

    if platform == "tiktok":
        methods = ["tikwm", "ytdlp"]  # TikTok: tikwm API 优先
    else:
        methods = ["ytdlp"]           # 其他平台: 直接用 yt-dlp
        if platform == "unknown":
            # 未知平台也用 yt-dlp 尝试
            pass

    last_error = None

    for method in methods:
        try:
            if method == "tikwm":
                return _retry_with_backoff(_download_via_tikwm, url, save_dir, job_id, proxy)
            elif method == "ytdlp":
                return _retry_with_backoff(_download_via_ytdlp, url, save_dir, job_id, proxy)
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
