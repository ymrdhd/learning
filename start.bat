@echo off
setlocal
cd /d "%~dp0backend"

rem --- V2.8 launcher: fixed port 8000 + LAN access (phone / tablet on the same Wi-Fi) ---
rem The product home page is "Today" (today.html); index.html stays as free practice.
rem --- V2.8: the version number lives in version.json (read again after the update step below) ---
set "TARGET_VERSION=2.8.0"
set "PORT=8000"

rem --- 1) This PC's LAN IPv4 address (shown as the phone URL) ---
set "LAN_IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "$s=New-Object System.Net.Sockets.UdpClient; try{ $s.Connect('8.8.8.8',53); $s.Client.LocalEndPoint.Address.ToString() }catch{ '' } finally{ $s.Close() }"') do set "LAN_IP=%%i"
if "%LAN_IP%"=="" for /f "delims=" %%i in ('powershell -NoProfile -Command "[System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1 | ForEach-Object { $_.IPAddressToString }"') do set "LAN_IP=%%i"
if "%LAN_IP%"=="" set "LAN_IP=127.0.0.1"

set "APP_URL=http://127.0.0.1:%PORT%/app/today.html"
set "PHONE_URL=http://%LAN_IP%:%PORT%/app/today.html"

rem --- 2) Compare with the GitHub repo (version.json) and auto-update the code ---
rem     Never blocks startup: no network / GitHub unreachable -> print one line and continue.
echo [..] Checking https://github.com/ymrdhd/learning for a newer version...
python update_check.py --apply
echo.

set "TARGET_VERSION="
for /f "delims=" %%v in ('python update_check.py --version') do set "TARGET_VERSION=%%v"
if "%TARGET_VERSION%"=="" set "TARGET_VERSION=2.8.0"

rem --- 3) Fixed port: is it already serving this app, and can the LAN reach it? ---
set "SERVED="
for /f "delims=" %%v in ('powershell -NoProfile -Command "try{ (Invoke-RestMethod -Uri http://127.0.0.1:8000/ -TimeoutSec 2).version }catch{ }"') do set "SERVED=%%v"

set "LANOK="
for /f "delims=" %%o in ('powershell -NoProfile -Command "try{ (Invoke-RestMethod -Uri http://%LAN_IP%:8000/ -TimeoutSec 2).version }catch{ }"') do set "LANOK=%%o"

if not "%SERVED%"=="" if not "%LANOK%"=="" (
    echo [OK] Backend V%LANOK% is already running on port 8000.
    if not "%LANOK%"=="%TARGET_VERSION%" echo [!] That instance is V%LANOK% ^(expected V%TARGET_VERSION%^). Close its window to load the new code.
    echo      This PC : %APP_URL%
    echo      Phone   : %PHONE_URL%
    start "" "%APP_URL%"
    pause
    exit /b 0
)

if not "%SERVED%"=="" (
    echo [!] Port 8000 is already used by an instance that only listens on 127.0.0.1,
    echo     so phones on the same Wi-Fi cannot reach it. Close that window, then run this file again.
    pause
    exit /b 1
)

echo [..] Starting backend in: %CD%
echo      This PC : %APP_URL%
echo      Phone   : %PHONE_URL%   ^(open it on a phone / tablet in the same Wi-Fi^)
echo      Tip     : if the phone cannot open it, allow python through Windows Firewall on Private networks.
echo      Press Ctrl+C to stop.
echo.

rem --- wait for the backend to come up, then open the browser on this PC ---
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process '%APP_URL%'"

python -m uvicorn main:app --host 0.0.0.0 --port %PORT%
pause
