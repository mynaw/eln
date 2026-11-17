@echo off
setlocal
cd /d "%~dp0"
set "LOG=%~dp0firewall_log.txt"
> "%LOG%" echo ===== open_firewall %DATE% %TIME% =====

net session >nul 2>&1
if errorlevel 1 goto notadmin
>> "%LOG%" echo [ok] running as administrator

>> "%LOG%" echo [run] remove old ELN rules
powershell -NoProfile -Command "Remove-NetFirewallRule -DisplayName 'ELN*' -ErrorAction SilentlyContinue" >> "%LOG%" 2>&1

>> "%LOG%" echo [run] add inbound rule: TCP 8765
netsh advfirewall firewall add rule name="ELN 8765" dir=in action=allow protocol=TCP localport=8765 profile=private >> "%LOG%" 2>&1

set "PY=python"
set "PYW=pythonw"
if not exist "%PY%" for /f "delims=" %%i in ('where python') do set "PY=%%i"
if not exist "%PYW%" for /f "delims=" %%i in ('where pythonw') do set "PYW=%%i"
>> "%LOG%" echo [py] %PY%
>> "%LOG%" echo [py] %PYW%

>> "%LOG%" echo [run] add inbound rule: python.exe / pythonw.exe
netsh advfirewall firewall add rule name="ELN Python" dir=in action=allow program="%PY%" profile=private >> "%LOG%" 2>&1
netsh advfirewall firewall add rule name="ELN Python" dir=in action=allow program="%PYW%" profile=private >> "%LOG%" 2>&1

>> "%LOG%" echo [check] current ELN rules
powershell -NoProfile -Command "Get-NetFirewallRule -DisplayName 'ELN*' | Format-Table DisplayName,Enabled,Direction,Action,Profile -AutoSize" >> "%LOG%" 2>&1

>> "%LOG%" echo [check] local IPv4
ipconfig | findstr /C:"IPv4" >> "%LOG%" 2>&1

echo.
echo ---- log: %LOG% ----
type "%LOG%"
echo.
echo Port 8765 and Python are now allowed on PRIVATE networks only.
echo Open this address on your phone (same Wi-Fi):
echo    http://服务器IP:8765/login
echo If the page still does not open, the campus network blocks device-to-device traffic.
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
