@echo off
cd /d "%~dp0\..\vendor\ketcher-app"
title 构建 Ketcher 编辑器

rem 优先用系统里的 node；没有就退回 WorkBuddy 自带的那份（仅本机路径）
where npm >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\nodejs\npm.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
where npm >nul 2>&1
if errorlevel 1 (
  echo.
  echo 找不到 npm。请先安装 Node.js 18+ 再运行本脚本。
  echo Ketcher 只是可选的增强编辑器，不装也不影响 ELN 其它功能。
  pause
  exit /b 1
)

if not exist node_modules (
  echo 首次构建，安装依赖（约 200 MB，第一次要几分钟）...
  call npm install --no-audit --no-fund
  if errorlevel 1 goto fail
)

echo 打包中...
call npm run build
if errorlevel 1 goto fail

echo.
echo 构建完成：vendor\ketcher-app\dist
echo 回到 ELN 画板点「用 Ketcher 编辑」即可，之后不需要联网。
pause
exit /b 0

:fail
echo.
echo 构建失败，往上翻看报错。
pause
exit /b 1
