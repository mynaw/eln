@echo off
setlocal
cd /d "%~dp0"
set "LOG=%~dp0firewall_log.txt"
> "%LOG%" echo ===== restore_firewall %DATE% %TIME% =====

net session >nul 2>&1
if errorlevel 1 goto notadmin
>> "%LOG%" echo [ok] running as administrator

>> "%LOG%" echo [run] remove all ELN rules
powershell -NoProfile -Command "Remove-NetFirewallRule -DisplayName 'ELN*' -ErrorAction SilentlyContinue" >> "%LOG%" 2>&1

>> "%LOG%" echo [check] remaining ELN rules (should be empty)
powershell -NoProfile -Command "Get-NetFirewallRule -DisplayName 'ELN*' | Format-Table DisplayName,Enabled,Direction,Action -AutoSize" >> "%LOG%" 2>&1

echo.
echo ---- log: %LOG% ----
type "%LOG%"
echo.
echo ELN firewall rules removed. Port 8765 is blocked for inbound again.
echo Run open_firewall_as_admin.bat to allow it again.
echo.
pause
exit /b 0

:notadmin
>> "%LOG%" echo [err] not elevated
echo.
echo This script needs Administrator rights.
echo Right-click the .bat file and choose "Run as administrator".
echo.
pause
exit /b 1
