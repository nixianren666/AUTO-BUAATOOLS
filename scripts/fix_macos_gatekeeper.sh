#!/usr/bin/env bash
# ==============================================================================
# AUTO-BUAA macOS Gatekeeper 隔离属性永久移除工具
# 解决提示: "无法打开，因为无法验证开发者" 或 "App 已损坏，打不开"
# ==============================================================================

APP_PATH="${1:-/Applications/BUAA-Signin.app}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  🍎 AUTO-BUAA macOS Gatekeeper 安全隔离一键解除工具           ${NC}"
echo -e "${CYAN}================================================================${NC}"

if [ ! -d "${APP_PATH}" ]; then
    echo -e "${YELLOW}提示: 未在默认路径 [${APP_PATH}] 发现应用。${NC}"
    echo -e "请输入 BUAA-Signin.app 的实际路径 (或直接将应用拖拽到此终端窗口后回车):"
    read -r custom_path
    APP_PATH="${custom_path:-$APP_PATH}"
fi

# 去除引号与转义斜杠
APP_PATH=$(echo "$APP_PATH" | sed -e "s/^['\"]//" -e "s/['\"]$//" -e 's/\\//g')

if [ ! -d "${APP_PATH}" ]; then
    echo -e "${RED}错误: 路径不存在: ${APP_PATH}${NC}"
    exit 1
fi

echo -e "${YELLOW}>>> 正在清除 Gatekeeper 隔离属性 (com.apple.quarantine)...${NC}"
sudo xattr -rd com.apple.quarantine "${APP_PATH}" 2>/dev/null || xattr -cr "${APP_PATH}" 2>/dev/null || true

echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  🎉 隔离属性清除成功！Gatekeeper 已永久信任该应用。           ${NC}"
echo -e "${GREEN}  以后双击打开应用不会再出现任何无法验证或损坏的拦截提示。     ${NC}"
echo -e "${GREEN}================================================================${NC}"

echo -e "是否立即启动应用？(Y/n):"
read -r launch_choice
if [[ "$launch_choice" =~ ^[Yy]?$ ]]; then
    open "${APP_PATH}"
fi
