#!/usr/bin/env bash
# AUTO-BUAA Linux 终端启动脚本
set -e

cd "$(dirname "$0")"

echo "================================================================"
echo "  🚀 正在启动 AUTO-BUAA 课程独立签到助手 Pro (Linux Web 服务)"
echo "================================================================"

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未检测到 python3，请先安装 Python 3.10+ (如: sudo apt install python3 python3-pip)"
    exit 1
fi

# 检查或安装依赖
if [ ! -d ".venv" ]; then
    echo ">>> 首次运行，正在初始化 Python 虚拟环境..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

echo ">>> 正在监听 0.0.0.0:18346，随时按 Ctrl+C 可停止..."
exec .venv/bin/python run.py --headless --host 0.0.0.0 --port 18346 "$@"
