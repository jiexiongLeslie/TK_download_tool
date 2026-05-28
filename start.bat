@echo off
chcp 65001 >nul
title 短视频批量下载器

cd /d "%~dp0"

echo.
echo   ==================================================
echo   🎬 短视频批量下载器 v1.3
echo   ==================================================
echo.
echo   正在启动服务...

:: 启动 Flask (HTTPS)
start /B python app.py > nul 2>&1

:: 等待服务就绪
echo   等待服务就绪...
timeout /t 3 /nobreak > nul

:: 打开浏览器
echo   正在打开浏览器...
start https://127.0.0.1:5000

echo.
echo   ✅ 服务已启动! (HTTPS)
echo   🔒 本机访问: https://127.0.0.1:5000
echo   📱 远程访问: https://^<你的IP^>:5000
echo   ⚠️ 首次需信任自签名证书
echo.
echo   关闭此窗口将停止服务。
echo.
pause
