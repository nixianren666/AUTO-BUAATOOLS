#!/usr/bin/env bash
# ==============================================================================
# AUTO-BUAA Linux 7×24 小时后台守护服务自动化安装与运维脚本
# 支持: install, start, stop, restart, status, update, logs, uninstall
# ==============================================================================

set -e

SERVICE_NAME="auto-buaa"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="18346"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

function print_banner() {
    echo -e "${CYAN}================================================================${NC}"
    echo -e "${CYAN}  🚀 AUTO-BUAA 课程独立签到助手 - Linux 24小时后台服务管理器  ${NC}"
    echo -e "${CYAN}  版本: v1.2.2 | 目录: ${PROJECT_DIR}${NC}"
    echo -e "${CYAN}================================================================${NC}"
}

function check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}错误: 该操作需要 root 权限，请使用 sudo 执行该脚本: sudo $0 $1${NC}"
        exit 1
    fi
}

function get_local_ip() {
    local ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$ip" ]; then
        ip="127.0.0.1"
    fi
    echo "$ip"
}

function action_install() {
    check_root
    echo -e "${YELLOW}>>> [1/4] 检查系统基础环境...${NC}"
    if ! command -v python3 &>/dev/null; then
        echo -e "${RED}错误: 未检测到 python3，请先安装: sudo apt install -y python3 python3-pip python3-venv (或 yum/dnf)${NC}"
        exit 1
    fi

    echo -e "${YELLOW}>>> [2/4] 初始化 Python 虚拟运行环境 (.venv)...${NC}"
    cd "${PROJECT_DIR}"
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo -e "${YELLOW}>>> [3/4] 生成 systemd 系统服务单元 (${SERVICE_FILE})...${NC}"
    cat <<EOF > "${SERVICE_FILE}"
[Unit]
Description=AUTO-BUAA Course Signin Pro Web Service (24/7 Daemon)
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SUDO_USER:-root}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/run.py --headless --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
Environment=HEADLESS=1
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    echo -e "${YELLOW}>>> [4/4] 注册并启动开机自启服务...${NC}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"

    sleep 2
    local ip=$(get_local_ip)
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}  🎉 AUTO-BUAA 后台守护服务已成功安装并启动！${NC}"
    echo -e "${GREEN}  开机自启: 已配置并自动启用 (systemd enable)${NC}"
    echo -e "${GREEN}  WebUI 访问地址: http://${ip}:${PORT} 或 http://localhost:${PORT}${NC}"
    echo -e "${GREEN}  日常管理命令:${NC}"
    echo -e "    - 查看状态: sudo $0 status"
    echo -e "    - 在线更新: sudo $0 update"
    echo -e "    - 查看日志: sudo $0 logs"
    echo -e "    - 停止服务: sudo $0 stop"
    echo -e "${GREEN}================================================================${NC}"
}

function action_start() {
    check_root
    echo -e "${CYAN}正在启动 ${SERVICE_NAME} 服务...${NC}"
    systemctl start "${SERVICE_NAME}"
    action_status
}

function action_stop() {
    check_root
    echo -e "${CYAN}正在停止 ${SERVICE_NAME} 服务...${NC}"
    systemctl stop "${SERVICE_NAME}"
    echo -e "${GREEN}服务已安全停止。${NC}"
}

function action_restart() {
    check_root
    echo -e "${CYAN}正在重启 ${SERVICE_NAME} 服务...${NC}"
    systemctl restart "${SERVICE_NAME}"
    action_status
}

function action_status() {
    systemctl status "${SERVICE_NAME}" --no-pager || true
    local ip=$(get_local_ip)
    echo -e "\n${CYAN}>>> WebUI 访问地址: http://${ip}:${PORT}${NC}"
}

function action_logs() {
    journalctl -u "${SERVICE_NAME}" -f -n 50
}

function action_update() {
    check_root
    echo -e "${YELLOW}>>> [1/3] 从 GitHub 拉取最新代码 (git pull)...${NC}"
    cd "${PROJECT_DIR}"
    git pull origin main || git pull

    echo -e "${YELLOW}>>> [2/3] 增量安装/升级 Python 依赖库...${NC}"
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo -e "${YELLOW}>>> [3/3] 平滑重启后台守护服务...${NC}"
    systemctl restart "${SERVICE_NAME}"
    sleep 2

    local ip=$(get_local_ip)
    echo -e "${GREEN}================================================================${NC}"
    echo -e "${GREEN}  ✅ AUTO-BUAA 已成功更新至最新版本代码并平滑重启！${NC}"
    echo -e "${GREEN}  WebUI 访问地址: http://${ip}:${PORT}${NC}"
    echo -e "${GREEN}================================================================${NC}"
}

function action_uninstall() {
    check_root
    echo -e "${YELLOW}正在完全卸载 ${SERVICE_NAME} 服务...${NC}"
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    rm -f "${SERVICE_FILE}"
    systemctl daemon-reload
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
        echo -e "  sudo $0 install   # 一键安装并设置开机自启"
        echo -e "  sudo $0 update    # 一键拉取最新代码并热重启"
        echo -e "  sudo $0 status    # 查看当前运行状态与WebUI地址"
        echo -e "  sudo $0 logs      # 实时追踪运行日志"
        exit 1
        ;;
esac
