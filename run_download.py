"""
单次下载脚本 - 下载指定的 TikTok 视频
用法: python run_download.py <url>
"""

import sys

sys.path.insert(0, ".")

from downloader import download_video, get_progress

# 默认 URL
default_url = "https://www.tiktok.com/@sunlu_us_online/video/7642707869439102239"
url = sys.argv[1] if len(sys.argv) > 1 else default_url

print(f"🎬 开始下载: {url}\n")
result = download_video(url)

if result["status"] == "done":
    print(f"\n✅ 下载成功! (方案: {result.get('method', 'unknown')})")
    print(f"   标题: {result['title']}")
    print(f"   路径: {result['filepath']}")
    size_mb = result.get("filesize", 0) / 1024 / 1024
    print(f"   大小: {size_mb:.1f} MB")
else:
    print(f"\n❌ 下载失败: {result.get('error', '未知错误')}")
