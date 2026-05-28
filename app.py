"""
TikTok 视频批量下载器 - Flask Web 应用
"""

import threading
import time
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from downloader import download_video, get_progress, extract_job_id

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def api_download():
    """接收下载请求，异步执行"""
    data = request.get_json()
    urls_input = data.get("urls", "")

    # 按行分割，过滤空行
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]

    if not urls:
        return jsonify({"error": "请至少输入一个有效的 TikTok 视频链接"}), 400

    jobs = []
    for url in urls:
        job_id = extract_job_id(url)
        jobs.append({"job_id": job_id, "url": url, "status": "queued"})

    # 异步执行下载
    def run_downloads():
        for url in urls:
            download_video(url)

    thread = threading.Thread(target=run_downloads, daemon=True)
    thread.start()

    return jsonify({"message": f"已提交 {len(urls)} 个下载任务", "jobs": jobs})


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
    """提供视频文件下载/播放"""
    progress = get_progress(job_id)
    if not progress or progress.get("status") != "done":
        return jsonify({"error": "视频尚未下载完成"}), 404

    filepath = progress.get("filepath", "")
    path = Path(filepath)
    if not path.exists():
        return jsonify({"error": "文件不存在"}), 404

    return send_file(
        path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=path.name,
    )


@app.route("/api/file")
def api_file_info():
    """获取已下载文件列表"""
    files = []
    for f in sorted(DOWNLOADS_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
        })
    return jsonify({"files": files, "dir": str(DOWNLOADS_DIR)})


if __name__ == "__main__":
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n  {'='*50}")
    print(f"  🎬 TikTok 视频批量下载器 v1.0")
    print(f"  📂 下载目录: {DOWNLOADS_DIR}")
    print(f"  🌐 访问地址: http://127.0.0.1:5000")
    print(f"  💡 提交后自动推送到 GitHub")
    print(f"  {'='*50}\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
