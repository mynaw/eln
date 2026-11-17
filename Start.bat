@echo off
cd /d "%~dp0"
title ELN - Electronic Lab Notebook
rem 用 PATH 里的 Python；pythonw 优先（不弹控制台）
rem 想指定解释器：set ELN_PYTHON / ELN_PYTHONW
if defined ELN_PYTHONW (set "PYW=%ELN_PYTHONW%") else (set "PYW=pythonw")
if defined ELN_PYTHON  (set "PY=%ELN_PYTHON%")   else (set "PY=python")
where python >nul 2>&1 || goto nopython
start "" "%PYW%" "%~dp0gui.py" %*
exit /b 0
start "" "%PYW%" "%~dp0gui.py" %*
exit /b 0

:nopython
echo.
echo   Python not found. Install Python 3.10+ (Add to PATH), then:
echo       pip install rdkit pillow
echo.
pause
exit /b 1
