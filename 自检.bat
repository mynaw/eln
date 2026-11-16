@echo off
cd /d "%~dp0"
title ELN - Self Check
set "PY=python"
if not exist "%PY%" set "PY=python"
"%PY%" selfcheck.py
echo.
pause
