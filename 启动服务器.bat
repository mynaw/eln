@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ELN 服务器（关闭此窗口即停止服务）

echo ============================================================
echo   ELN 服务器模式
echo.
echo   本机登录：  http://127.0.0.1:8765/login
echo   局域网：    http://本机IP:8765/login（下面会打印实际地址）
echo   账户：      你自己的 ELN 账户（wgf 已是管理员）
echo.
echo   停止服务：  直接关闭这个窗口
echo ============================================================
echo.

python "%~dp0webapp.py" --auth --host 0.0.0.0
pause
