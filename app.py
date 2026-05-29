"""
TikTok 视频批量下载器 - Flask Web 应用 (流式直传版)
所有设备统一：浏览器选目录 → 服务器代理解析 → 流式直传客户端
"""

import csv
import io
import time
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from history import load_history, clear_ip_history


def _get_client_ip() -> str:
    """获取客户端真实 IP"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(str(STATIC_DIR), filename)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "version": "2.0",
        "mode": "stream-only",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/stream-download", methods=["POST"])
def api_stream_download():
    """
    流式代理下载：服务器解析视频链接 → 直接流式传输到客户端
    适用于远程设备，不占用服务器磁盘空间
    """
    import urllib.request as urlreq
    import urllib.error as urlerr

    data = request.get_json()
    url = data.get("url", "")
    use_proxy = data.get("use_proxy", True)

    if not url:
        return jsonify({"error": "请提供视频链接"}), 400

    proxy = "http://127.0.0.1:7897" if use_proxy else None
    opener = urlreq.build_opener()
    if proxy:
        opener = urlreq.build_opener(urlreq.ProxyHandler({"http": proxy, "https": proxy}))

    # Step 1: 通过 tikwm API 获取视频下载链接
    api_url = f"https://www.tikwm.com/api/?url={urlreq.quote(url, safe='')}"
    try:
        resp = opener.open(urlreq.Request(api_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }), timeout=30)
        api_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return jsonify({"error": f"解析视频失败: {e}"}), 500

    if api_data.get("code") != 0:
        return jsonify({"error": api_data.get("msg", "解析失败")}), 500

    video_info = api_data["data"]
    video_url = video_info.get("hdplay") or video_info.get("play")
    title = video_info.get("title", "video")

    if not video_url:
        return jsonify({"error": "未找到视频下载链接"}), 500

    # Step 2: 先获取 Content-Length 再流式传输
    content_length = 0
    try:
        head_req = urlreq.Request(video_url, method="HEAD")
        head_req.add_header("User-Agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15")
        head_req.add_header("Referer", "https://www.tiktok.com/")
        head_resp = opener.open(head_req, timeout=15)
        content_length = int(head_resp.headers.get("Content-Length", 0))
    except Exception:
        pass

    def generate():
        try:
            dl_resp = opener.open(urlreq.Request(video_url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
                "Referer": "https://www.tiktok.com/",
            }), timeout=120)
            while True:
                chunk = dl_resp.read(65536)
                if not chunk:
                    break
                yield chunk
        except Exception:
            pass

    safe_title = title.replace('"', "'").replace('\n', ' ')[:80]
    filename = f"{safe_title}.mp4"
    encoded_fn = urlreq.quote(filename.encode("utf-8"))

    return app.response_class(
        generate(),
        mimetype="video/mp4",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_fn}",
            "Content-Length": str(content_length),
            "Cache-Control": "no-cache",
        },
    )


@app.route("/api/history/export")
def api_export_history():
    """导出当前 IP 的下载历史为 CSV"""
    history = load_history(_get_client_ip())
    if not history:
        return jsonify({"error": "暂无下载记录"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["下载时间", "视频标题", "视频链接", "文件路径"])
    for item in sorted(history.values(), key=lambda x: x.get("time", ""), reverse=True):
        writer.writerow([item["time"], item["title"], item["url"], item["filepath"]])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"tiktok_download_{time.strftime('%Y%m%d_%H%M%S')}.csv",
    )


@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    """清空当前 IP 的下载历史"""
    count = clear_ip_history(_get_client_ip())
    return jsonify({"message": f"已清空 {count} 条下载记录", "count": count})


@app.route("/api/open-dir", methods=["POST"])
def api_open_dir():
    """在 Windows 资源管理器中打开本地文件夹"""
    import os
    data = request.get_json()
    dir_param = data.get("dir", "")
    if not dir_param:
        return jsonify({"error": "请提供文件夹路径"}), 400
    target = Path(dir_param)
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))
        return jsonify({"message": f"已打开 {target}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_local_ip() -> str:
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "无法获取"


if __name__ == "__main__":
    from hypercorn.config import Config
    from hypercorn.asyncio import serve as hc_serve
    import asyncio

    config = Config()
    config.bind = ["0.0.0.0:5000"]
    config.certfile = "certs/cert.pem"
    config.keyfile = "certs/key.pem"
    config.worker_class = "asyncio"
    config.accesslog = "-"

    local_ip = _get_local_ip()
    print(f"\n  {'='*50}")
    print(f"  🎬 短视频批量下载器 v2.0 (统一流式版)")
    print(f"  🔒 https://127.0.0.1:5000")
    print(f"  📱 https://{local_ip}:5000")
    print(f"  💡 所有设备统一：浏览器选目录 → 流式直传 → 本机保存")
    print(f"  {'='*50}\n")
    asyncio.run(hc_serve(app, config))
