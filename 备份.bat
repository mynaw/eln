@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ELN 备份

set "PY=python"

echo 备份到 _backups\data 与 _backups\bundle ...
echo.
"%PY%" "tools\backup.py" --commit %*

echo.
pause
