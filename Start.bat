@echo off
cd /d "%~dp0"
title ELN - Electronic Lab Notebook
rem 用 PATH 里的 Python；pythonw 优先（不弹控制台）
set "PYW=pythonw"
set "PY=python"
where pythonw >nul 2>&1 || set "PYW=python"
where python  >nul 2>&1 || goto nopython
start "" "%PYW%" "%~dp0gui.py" %*
exit /b 0

:nopython
echo.
echo   Python not found. Install Python 3.10+ (Add to PATH), then:
echo       pip install rdkit pillow
echo.
pause
exit /b 1
