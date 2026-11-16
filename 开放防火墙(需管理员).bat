@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 开放 ELN 网页端口（需要管理员）

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [!] 需要管理员权限。
    echo       请右键这个文件 -^> "以管理员身份运行"
    echo.
    pause
    exit /b 1
)

echo 正在添加防火墙规则（仅“专用网络”，不开放公用网络）...
netsh advfirewall firewall delete rule name="ELN 网页 8765" >nul 2>&1
netsh advfirewall firewall delete rule name="ELN Python 程序" >nul 2>&1

netsh advfirewall firewall add rule name="ELN 网页 8765" dir=in action=allow protocol=TCP localport=8765 profile=private
rem Python 的安装位置因机器而异，这里按 PATH 动态取
for /f "delims=" %%i in ('where python') do set "PY=%%i"
for /f "delims=" %%i in ('where pythonw') do set "PYW=%%i"
if defined PY netsh advfirewall firewall add rule name="ELN Python 程序" dir=in action=allow program="%PY%" profile=private
if defined PYW netsh advfirewall firewall add rule name="ELN Python 程序" dir=in action=allow program="%PYW%" profile=private

echo.
echo 当前规则：
netsh advfirewall firewall show rule name="ELN 网页 8765" | findstr /C:"规则名称" /C:"已启用" /C:"方向" /C:"操作" /C:"配置文件"
echo.
echo 本机 IP（手机要用 192.168.x.x 那个）：
ipconfig | findstr /C:"IPv4"
echo.
echo 完成。若手机仍连不上：
echo   1) 确认手机和电脑在同一个 Wi-Fi（同一网段 192.168.1.x）
echo   2) 路由器若开了“AP 隔离/访客网络”，设备之间互相访问会被禁止
echo   3) 桌面端点“浏览器”选“是”时弹窗里的完整地址要带上 ?t=口令
echo.
pause
