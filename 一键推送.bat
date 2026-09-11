@echo off
chcp 65001 >nul
title AUTO-BUAATOOLS 一键推送到 GitHub
echo ========================================================
echo   正在准备推送到 GitHub: nixianren666/AUTO-BUAATOOLS
echo ========================================================
echo.
set "GIT_EXEC_PATH=C:\Users\cjt16\AppData\Roaming\MobaXterm\slash\mx86_64b\usr\git\git-core"
set "PATH=C:\Users\cjt16\AppData\Roaming\MobaXterm\slash\mx86_64b\bin;%GIT_EXEC_PATH%;%PATH%"
cd /d "%~dp0"
echo 提示：GitHub 已于 2021 年起强制要求使用 Personal Access Token (以 ghp_ 开头) 替代普通密码。
echo.
git push -u origin main
echo.
if %errorlevel% equ 0 (
    echo ========================================================
    echo   推送成功！全部源码、文档、安装包与绿色版已上线！
    echo ========================================================
) else (
    echo 推送过程中遇到问题，请检查 Token 权限或网络。
)
pause

