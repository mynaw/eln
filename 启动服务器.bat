@echo off
cd /d "%~dp0"
title ELN 服务器（关闭此窗口即停止服务）

rem 局域网访问口令由 webapp.py 自己决定，顺序是：
rem   1) 命令行 --token 参数（本行没加）
rem   2) 环境变量 ELN_WEB_TOKEN
rem   3) 程序目录 _local.json 里的 web_token（本机私有，_local.* 已 gitignore）
rem 三者都没有就不校验口令。要固定口令就编辑 _local.json，不用改本文件。

echo ============================================================
echo   ELN 服务器模式
echo.
echo   本机登录：  http://127.0.0.1:8765/login
echo   局域网：    http://本机IP:8765/login（下面会打印实际地址）
echo   账户：      你自己的 ELN 账户（首次使用请先建账户或运行 admin_reset）
echo.
echo   停止服务：  直接关闭这个窗口
echo ============================================================
echo.

python "%~dp0webapp.py" --auth --host 0.0.0.0
pause
