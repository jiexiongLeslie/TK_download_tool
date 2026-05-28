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
from history import check_duplicates, record_download, load_history

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
STATIC_DIR = BASE_DIR / "static"


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(str(STATIC_DIR), filename)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def api_download():
    """接收下载请求，异步执行"""
    data = request.get_json()
    urls_input = data.get("urls", "")
    save_dir = data.get("save_dir", "")

    # 按行分割，过滤空行
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]

    if not urls:
        return jsonify({"error": "请至少输入一个有效的 TikTok 视频链接"}), 400

    # 验证并创建保存目录
    if save_dir:
        target_dir = Path(save_dir)
    else:
        target_dir = DOWNLOADS_DIR

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"无法创建目录: {e}"}), 400

    jobs = []
    for url in urls:
        job_id = extract_job_id(url)
        jobs.append({"job_id": job_id, "url": url, "status": "queued"})

    # 异步执行下载
    def run_downloads():
        for url in urls:
            result = download_video(url, save_dir=str(target_dir))
            # 记录到下载历史
            if result["status"] == "done":
                record_download(url, result["job_id"], result["title"], result["filepath"])

    thread = threading.Thread(target=run_downloads, daemon=True)
    thread.start()

    return jsonify({
        "message": f"已提交 {len(urls)} 个下载任务",
        "save_dir": str(target_dir),
        "jobs": jobs,
    })


@app.route("/api/download/check", methods=["POST"])
def api_check_duplicates():
    """检查链接是否已下载过"""
    data = request.get_json()
    urls_input = data.get("urls", "")
    urls = [u.strip() for u in urls_input.split("\n") if u.strip()]

    if not urls:
        return jsonify({"duplicates": [], "new": [], "total_history": 0})

    result = check_duplicates(urls)
    return jsonify(result)


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
    """获取已下载文件列表，支持指定目录"""
    dir_param = request.args.get("dir", "")
    if dir_param:
        search_dir = Path(dir_param)
    else:
        search_dir = DOWNLOADS_DIR

    files = []
    if search_dir.exists():
        for f in sorted(search_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
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

    # 安全检查：只允许删除 .mp4 文件
    if filepath.suffix.lower() != ".mp4":
        return jsonify({"error": "仅支持删除 .mp4 文件"}), 400

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
    print(f"\n  {'='*50}")
    print(f"  🎬 TikTok 视频批量下载器 v1.0")
    print(f"  📂 下载目录: {DOWNLOADS_DIR}")
    print(f"  🌐 本机访问: http://127.0.0.1:5000")
    print(f"  📱 局域网访问: http://{local_ip}:5000")
    print(f"  💡 提交后自动推送到 GitHub")
    print(f"  {'='*50}\n")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
