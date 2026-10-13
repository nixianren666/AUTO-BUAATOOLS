#!/usr/bin/env bash
set -euo pipefail
app_path="${1:-/Applications/BUAA-Signin.app}"
[[ -d "$app_path" && "$(basename "$app_path")" == "BUAA-Signin.app" ]] || { echo "请选择本项目的 BUAA-Signin.app" >&2; exit 1; }
identifier=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app_path/Contents/Info.plist")
[[ "$identifier" == "com.buaa.signin" ]] || { echo "应用身份不符" >&2; exit 1; }
codesign --verify --deep --strict "$app_path"
xattr -rd com.apple.quarantine "$app_path"
echo "仅已清除此应用的下载隔离属性；未改变系统安全设置，也不代表应用已公证。"
