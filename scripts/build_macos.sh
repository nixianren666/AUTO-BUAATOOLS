#!/usr/bin/env bash
# ==============================================================================
# AUTO-BUAA macOS 本地一键编译打包与 DMG 镜像生成脚本
# 适用架构: Apple Silicon (M1/M2/M3/M4) 与 Intel (x86_64)
# ==============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "======================================================================"
echo "  [*] 正在为 macOS 构建 AUTO-BUAA 原生应用与安装镜像..."
echo "======================================================================"

# 1. 检查 Python 环境
if ! command -v python3 &>/dev/null; then
    echo "[-] 错误: 未检测到 python3，请先安装 Python 3.10+"
    exit 1
fi

# 2. 安装依赖
echo "[+] 检查并安装依赖..."
pip3 install -r requirements.txt pyinstaller pillow pywebview

# 3. 运行全套单元测试
echo "[+] 运行自动化测试套件..."
python3 -m unittest discover -s tests

# 4. 使用 PyInstaller 构建 .app Bundle
echo "[+] 执行 PyInstaller 编译..."
pyinstaller --noconfirm BUAA-Signin-mac.spec

# 5. 执行 Ad-hoc 深度签名（消除 Gatekeeper 报损坏的假阳性阻断）
echo "[+] 执行 Ad-hoc 本地签名..."
codesign --force --deep -s - dist/BUAA-Signin.app || true

# 6. 生成 DMG 挂载安装镜像与便携 Zip 压缩包
echo "[+] 打包 DMG 磁盘镜像..."
ARCH=$(uname -m)
DMG_ROOT="dist/dmg_root"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"

cp -R dist/BUAA-Signin.app "$DMG_ROOT/"
ln -s /Applications "$DMG_ROOT/Applications"

if [ -f "scripts/fix_macos_gatekeeper.sh" ]; then
    cp scripts/fix_macos_gatekeeper.sh "$DMG_ROOT/如果提示应用损坏请点我.sh"
    chmod +x "$DMG_ROOT/如果提示应用损坏请点我.sh"
fi

DMG_NAME="BUAA-Signin-macOS-${ARCH}.dmg"
ZIP_NAME="BUAA-Signin-macOS-${ARCH}.zip"

hdiutil create -volname "BUAA-Signin" -srcfolder "$DMG_ROOT" -ov -format UDZO "dist/${DMG_NAME}"

cd dist
zip -r -y "${ZIP_NAME}" BUAA-Signin.app
cd "$PROJECT_ROOT"

echo "======================================================================"
echo "  [✓] 构建成功！产物已输出至:"
echo "      - DMG 镜像: dist/${DMG_NAME}"
echo "      - Zip 压缩: dist/${ZIP_NAME}"
echo "======================================================================"
