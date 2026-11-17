@echo off
cd /d "%~dp0"
title ELN - Self Check
set "PY=python"
if defined ELN_PYTHON set "PY=%ELN_PYTHON%"
if not exist "%PY%" set "PY=python"
"%PY%" selfcheck.py
echo.
pause
