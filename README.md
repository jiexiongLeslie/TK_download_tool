# 🎬 TK Download Tool

TikTok 视频批量下载器 — 粘贴链接，一键批量下载到本地。

## ✨ 特性

- 🔗 批量粘贴多个 TikTok 视频链接，每行一个
- ⚡ 3 并发下载，速度提升 3 倍
- 🚫 无水印下载（通过 tikwm.com API）
- 📁 自定义保存目录 + 记忆上次路径
- 📋 下载历史记录，重复链接弹窗确认
- 🔄 网络失败自动重试 2 次
- 📱 局域网跨设备访问（手机/平板也能用）
- 🌓 暗色主题 UI + 自定义 Favicon

## 🚀 快速开始

### 环境要求

- Python 3.9+
- 需要代理访问 TikTok（默认 `127.0.0.1:7897`）

### 安装

```bash
git clone https://github.com/jiexiongLeslie/TK_download_tool.git
cd TK_download_tool
pip install -r requirements.txt
```

### 启动

```bash
python app.py
```

浏览器打开 `http://127.0.0.1:5000`

### 命令行单次下载

```bash
python run_download.py "https://www.tiktok.com/@xxx/video/xxx"
```

## 📖 使用说明

```
1. 粘贴视频链接（每行一个）
2. 设置保存目录（可选，留空则用 downloads/）
3. 点击「开始下载」
4. 查看实时进度
5. 下载完成，文件列表中可下载/删除
```

## 🏗 项目结构

```
TK_download_tool/
├── app.py              # Flask Web 应用
├── downloader.py       # 核心下载模块（tikwm API + yt-dlp 备选）
├── history.py          # 下载历史管理
├── run_download.py     # 命令行单次下载脚本
├── requirements.txt    # Python 依赖
├── static/
│   └── favicon.svg     # 网站图标
└── templates/
    └── index.html      # Web 前端界面
```

## ⚙️ 配置

| 配置项 | 文件 | 说明 |
|--------|------|------|
| 代理地址 | `downloader.py:21` | 默认 `127.0.0.1:7897` |
| 并发数 | `app.py:64` | 默认 3 |
| 重试次数 | `downloader.py:20` | 默认 2 次 |
| 历史上限 | `history.py:8` | 默认 500 条 |

## 🔗 技术方案

| 方案 | 说明 | 状态 |
|------|------|------|
| tikwm.com API | 无需登录，无水印下载 | ✅ 主方案 |
| yt-dlp | 需登录认证，作为备选 | ⚠️ 备选 |

## 📝 License

MIT
