"""
TikTok 视频批量下载器 - Flask Web 应用
"""

import csv
import io
import os
import threading
import time
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from downloader import download_video, get_progress, extract_job_id
from history import check_duplicates, record_download, load_history, all_history, clear_ip_history


def _get_client_ip() -> str:
    """获取客户端真实 IP"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "static"
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".ts"}  # 支持的视频格式


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(str(STATIC_DIR), filename)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    """健康检查"""
    try:
        import yt_dlp
        ytdlp_ok = True
    except ImportError:
        ytdlp_ok = False
    return jsonify({
        "status": "ok",
        "version": "1.3",
        "yt_dlp": ytdlp_ok,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/download", methods=["POST"])
def api_download():
    """接收下载请求，异步执行"""
    data = request.get_json()
    urls_input = data.get("urls", "")
    save_dir = data.get("save_dir", "")
    use_proxy = data.get("use_proxy", True)
    client_ip = _get_client_ip()

    # 按行分割，过滤空行
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]

    if not urls:
        return jsonify({"error": "请至少输入一个有效的 TikTok 视频链接"}), 400

    # 验证必填的保存目录
    if not save_dir:
        return jsonify({"error": "请填写保存目录路径"}), 400

    target_dir = Path(save_dir)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"无法创建目录: {e}"}), 400

    jobs = []
    for url in urls:
        job_id = extract_job_id(url)
        jobs.append({"job_id": job_id, "url": url, "status": "queued"})

    # 并发下载（最多 3 个同时进行）
    proxy = "http://127.0.0.1:7897" if use_proxy else None

    def run_downloads():
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(download_video, url, str(target_dir), proxy): url for url in urls}
            for future in as_completed(futures):
                result = future.result()
                if result["status"] == "done":
                    record_download(
                        client_ip,
                        futures[future],
                        result["job_id"],
                        result["title"],
                        result["filepath"],
                    )

    thread = threading.Thread(target=run_downloads, daemon=True)
    thread.start()

    return jsonify({
        "message": f"已提交 {len(urls)} 个下载任务",
        "save_dir": str(target_dir),
        "jobs": jobs,
    })


@app.route("/api/download/check", methods=["POST"])
def api_check_duplicates():
    """检查链接是否已下载过（文件仍存在磁盘才算重复）"""
    data = request.get_json()
    urls_input = data.get("urls", "")
    save_dir = data.get("save_dir", "")
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]

    if not urls:
        return jsonify({"duplicates": [], "new": [], "total_history": 0})

    result = check_duplicates(_get_client_ip(), urls, save_dir)
    return jsonify(result)


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
    video_url = video_info.get("wmplay") or video_info.get("play")
    title = video_info.get("title", "video")

    if not video_url:
        return jsonify({"error": "未找到视频下载链接"}), 500

    # Step 2: 流式传输视频到客户端（不写入服务器磁盘）
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


@app.route("/api/pick-dir")
def api_pick_dir():
    """打开 Windows 原生文件夹选择对话框，返回选中路径"""
    import subprocess

    # 使用 Shell.Application COM 对象，不依赖窗口句柄
    ps_script = """
$shell = New-Object -ComObject Shell.Application
$folder = $shell.BrowseForFolder(0, "选择视频保存目录", 0, 0)
if ($folder) { $folder.Self.Path } else { "" }
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=60,
        )
        folder = result.stdout.strip()
        if folder:
            return jsonify({"folder": folder})
        return jsonify({"folder": ""})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/open-dir", methods=["POST"])
def api_open_dir():
    """在 Windows 资源管理器中打开下载目录"""
    data = request.get_json()
    dir_param = data.get("dir", "")
    target = Path(dir_param) if dir_param else DOWNLOADS_DIR
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))
        return jsonify({"message": f"已打开 {target}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/progress")
def api_progress():
    """查询下载进度"""
    return jsonify(get_progress())


@app.route("/api/progress/<job_id>")
def api_progress_one(job_id):
    """查询单个任务进度"""
    return jsonify(get_progress(job_id))


@app.route("/api/video/<job_id>")
def api_serve_video(job_id):
    """提供视频文件下载/播放（直接从磁盘查找所有视频格式）"""
    filename = request.args.get("name", "")
    save_dir = request.args.get("dir", "")
    search_dir = Path(save_dir) if save_dir else DOWNLOADS_DIR

    # MIME 映射
    mime_map = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
                ".mov": "video/quicktime", ".flv": "video/x-flv", ".ts": "video/mp2t"}

    # 先按完整文件名查找
    if filename:
        path = search_dir / filename
        if path.exists() and path.suffix.lower() in VIDEO_EXTS:
            mime = mime_map.get(path.suffix.lower(), "video/mp4")
            return send_file(path, mimetype=mime, as_attachment=False)

    # 回退：按 job_id 模糊匹配
    for ext in VIDEO_EXTS:
        for f in search_dir.glob(f"*{job_id}*{ext}"):
            mime = mime_map.get(ext, "video/mp4")
            return send_file(f, mimetype=mime, as_attachment=False)

    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/file")
def api_file_info():
    """获取已下载文件列表，支持指定目录"""
    dir_param = request.args.get("dir", "")
    if not dir_param:
        return jsonify({"files": [], "dir": "未设置"})
    search_dir = Path(dir_param)

    files = []
    if search_dir.exists():
        all_videos = []
        for ext in VIDEO_EXTS:
            all_videos.extend(search_dir.glob(f"*{ext}"))
        for f in sorted(all_videos, key=lambda x: x.stat().st_mtime, reverse=True):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
            })
    return jsonify({"files": files, "dir": str(search_dir)})


@app.route("/api/file/delete", methods=["POST"])
def api_delete_file():
    """删除指定文件"""
    data = request.get_json()
    filename = data.get("filename", "")
    dir_param = data.get("dir", "")

    if not filename:
        return jsonify({"error": "请指定要删除的文件"}), 400

    search_dir = Path(dir_param) if dir_param else DOWNLOADS_DIR
    filepath = search_dir / filename

    # 安全检查：只允许删除视频文件
    if filepath.suffix.lower() not in VIDEO_EXTS:
        return jsonify({"error": f"不支持的视频格式: {filepath.suffix}"}), 400

    if not filepath.exists():
        return jsonify({"error": "文件不存在"}), 404

    try:
        filepath.unlink()
        return jsonify({"message": f"已删除 {filename}"})
    except Exception as e:
        return jsonify({"error": f"删除失败: {e}"}), 500


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
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    local_ip = _get_local_ip()

    # HTTP → HTTPS 重定向服务
    def run_http_redirect():
        from http.server import HTTPServer, BaseHTTPRequestHandler
        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                host = self.headers.get("Host", f"{local_ip}:5000").split(":")[0]
                self.send_response(301)
                self.send_header("Location", f"https://{host}:5000{self.path}")
                self.end_headers()
            def do_HEAD(self):
                self.do_GET()
            def do_POST(self):
                host = self.headers.get("Host", f"{local_ip}:5000").split(":")[0]
                self.send_response(307)
                self.send_header("Location", f"https://{host}:5000{self.path}")
                self.end_headers()
            def log_message(self, *args): pass
        httpd = HTTPServer(("0.0.0.0", 5080), RedirectHandler)
        httpd.serve_forever()

    threading.Thread(target=run_http_redirect, daemon=True).start()

    print(f"\n  {'='*50}")
    print(f"  🎬 短视频批量下载器 v1.3")
    print(f"  🔒 HTTPS: https://127.0.0.1:5000")
    print(f"  🔄 HTTP:  http://{local_ip}:5080 → 自动跳转 HTTPS")
    print(f"  📱 远程: https://{local_ip}:5000")
    print(f"  ⚠️ 远程首次需信任证书（高级/继续访问）")
    print(f"  {'='*50}\n")
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False,
        ssl_context=("certs/cert.pem", "certs/key.pem"),
    )
