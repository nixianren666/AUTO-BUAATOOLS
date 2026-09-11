@echo off
chcp 65001 >nul
title BUAA 课程独立签到助手
echo ========================================================
echo   正在启动 BUAA 课程独立签到助手 (轻量现代化桌面版)...
echo ========================================================
cd /d "%~dp0"
python run.py
if %errorlevel% neq 0 (
    echo.
    echo 启动遇到问题，正在检查依赖...
    python -m pip install -r requirements.txt
    python run.py
)
pause
