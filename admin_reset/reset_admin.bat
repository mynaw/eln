@echo off
rem ELN admin account reset: sets admin to Eln / ZZU@2026
setlocal
set "PY=python"
if defined ELN_PYTHON set "PY=%ELN_PYTHON%"
"%PY%" "%~dp0reset_admin.py"
endlocal
