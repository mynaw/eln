@echo off
cd /d "%~dp0"
title ELN 备份

set "PY=python"
if defined ELN_PYTHON set "PY=%ELN_PYTHON%"
if not exist "%PY%" set "PY=python"

echo 备份到 _backups\data 与 _backups\bundle ...
echo.
"%PY%" "tools\backup.py" --commit %*

echo.
pause
