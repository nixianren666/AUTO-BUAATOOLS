#!/usr/bin/env bash
# ==============================================================================
# AUTO-BUAA macOS 7×24 小时后台守护服务自动化安装与运维脚本 (launchd)
# 支持: install, start, stop, restart, status, update, logs, uninstall
# ==============================================================================

set -e

LABEL="com.buaa.signin"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_FILE="${PLIST_DIR}/${LABEL}.plist"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="18346"
LOG_OUT="${HOME}/Library/Logs/auto-buaa.log"
LOG_ERR="${HOME}/Library/Logs/auto-buaa-error.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

function print_banner() {
    echo -e "${CYAN}================================================================${NC}"
    echo -e "${CYAN}  🍎 AUTO-BUAA 课程独立签到助手 - macOS 24小时后台服务管理器  ${NC}"
    echo -e "${CYAN}  版本: v1.2.5 | 目录: ${PROJECT_DIR}${NC}"
    echo -e "${CYAN}================================================================${NC}"
}

function get_lan_ip() {
    local ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
    echo "$ip"
}

function action_install() {
    echo -e "${YELLOW}>>> [1/4] 检查 Python 环境...${NC}"
    local py_bin=""
    if command -v python3 &>/dev/null; then
        py_bin=$(command -v python3)
    elif [ -x "/opt/homebrew/bin/python3" ]; then
        py_bin="/opt/homebrew/bin/python3"
    elif [ -x "/usr/local/bin/python3" ]; then
        py_bin="/usr/local/bin/python3"
    else
        echo -e "${RED}错误: 未检测到 python3，请通过 Homebrew 安装: brew install python3${NC}"
        exit 1
    fi

    echo -e "${YELLOW}>>> [2/4] 初始化 Python 虚拟运行环境 (.venv)...${NC}"
    cd "${PROJECT_DIR}"
    if [ ! -d ".venv" ]; then
        "${py_bin}" -m venv .venv
    fi
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo -e "${YELLOW}>>> [3/4] 创建 launchd LaunchAgent 服务描述文件...${NC}"
    mkdir -p "${PLIST_DIR}"
    mkdir -p "${HOME}/Library/Logs"

    cat <<EOF > "${PLIST_FILE}"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/.venv/bin/python</string>
        <string>${PROJECT_DIR}/run.py</string>
        <string>--headless</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_OUT}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_ERR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HEADLESS</key>
        <string>1</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

    echo -e "${YELLOW}>>> [4/4] 加载并启动 LaunchAgent 服务...${NC}"
    launchctl unload "${PLIST_FILE}" 2>/dev/null || true
    launchctl load -w "${PLIST_FILE}"

    sleep 2
    local ip=$(get_lan_ip)
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}  🎉 AUTO-BUAA macOS 后台守护服务已成功安装并启动！${NC}"
    echo -e "${GREEN}  开机自启: 已配置并自动在登录时载入 (LaunchAgent)${NC}"
    echo -e "${GREEN}  WebUI 访问地址: http://${ip}:${PORT} 或 http://localhost:${PORT}${NC}"
    echo -e "${GREEN}  日常管理命令:${NC}"
    echo -e "    - 查看状态: $0 status"
    echo -e "    - 在线更新: $0 update"
    echo -e "    - 查看日志: $0 logs"
    echo -e "    - 停止服务: $0 stop"
    echo -e "${GREEN}================================================================${NC}"
}

function action_start() {
    echo -e "${CYAN}正在启动 ${LABEL} 服务...${NC}"
    launchctl load -w "${PLIST_FILE}" 2>/dev/null || launchctl start "${LABEL}"
    action_status
}

function action_stop() {
    echo -e "${CYAN}正在停止 ${LABEL} 服务...${NC}"
    launchctl unload -w "${PLIST_FILE}" 2>/dev/null || launchctl stop "${LABEL}"
    echo -e "${GREEN}服务已停止。${NC}"
}

function action_restart() {
    echo -e "${CYAN}正在重启 ${LABEL} 服务...${NC}"
    launchctl unload "${PLIST_FILE}" 2>/dev/null || true
    sleep 1
    launchctl load -w "${PLIST_FILE}"
    action_status
}

function action_status() {
    local pid=$(launchctl list | grep "${LABEL}" | awk '{print $1}')
    if [ -n "$pid" ] && [ "$pid" != "-" ]; then
        echo -e "${GREEN}● 服务运行中 [PID: ${pid}]${NC}"
    else
        echo -e "${YELLOW}○ 服务未运行或处于待命状态${NC}"
    fi
    local ip=$(get_lan_ip)
    echo -e "${CYAN}>>> WebUI 访问地址: http://${ip}:${PORT} 或 http://localhost:${PORT}${NC}"
}

function action_logs() {
    tail -f -n 50 "${LOG_OUT}"
}

function action_update() {
    echo -e "${YELLOW}>>> [1/3] 从 GitHub 拉取最新代码 (git pull)...${NC}"
    cd "${PROJECT_DIR}"
    git pull origin main || git pull

    echo -e "${YELLOW}>>> [2/3] 增量安装/升级 Python 依赖库...${NC}"
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo -e "${YELLOW}>>> [3/3] 平滑重启后台服务...${NC}"
    action_restart

    local ip=$(get_lan_ip)
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}  ✅ AUTO-BUAA 已成功更新至最新版本代码并重启！${NC}"
    echo -e "${GREEN}  WebUI 访问地址: http://${ip}:${PORT}${NC}"
    echo -e "${GREEN}================================================================${NC}"
}

function action_uninstall() {
    echo -e "${YELLOW}正在完全卸载 ${LABEL} LaunchAgent 服务...${NC}"
    launchctl unload -w "${PLIST_FILE}" 2>/dev/null || true
    rm -f "${PLIST_FILE}"
    echo -e "${GREEN}服务已彻底卸载。项目源码与配置保留在: ${PROJECT_DIR}${NC}"
}

print_banner
case "$1" in
    install) action_install ;;
    start) action_start ;;
    stop) action_stop ;;
    restart) action_restart ;;
    status) action_status ;;
    logs) action_logs ;;
    update) action_update ;;
    uninstall) action_uninstall ;;
    *)
        echo -e "使用方法: $0 {install|start|stop|restart|status|update|logs|uninstall}"
        echo -e "例如:"
        echo -e "  $0 install   # 一键安装并设置登录开机自启"
        echo -e "  $0 update    # 一键拉取最新代码并热重启"
        echo -e "  $0 status    # 查看当前运行状态与WebUI地址"
        echo -e "  $0 logs      # 实时追踪运行日志"
        exit 1
        ;;
esac
