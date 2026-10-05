@echo off
rem ==============================================================
rem  AI Learning System - fix LAN access for phones / tablets
rem  Run this file when the phone / tablet cannot open the app.
rem  Just double-click it: the script asks for administrator rights by itself.
rem
rem  It does three things:
rem    1) delete the inbound BLOCK rules named "Python"
rem       (on this machine only Block rules exist, and Block wins over Allow)
rem    2) allow inbound python.exe + TCP port 8000
rem    3) set the active network profile to Private, then print the phone URL
rem
rem  Rollback: netsh advfirewall firewall delete rule name="AI-Learning-Python"
rem            netsh advfirewall firewall delete rule name="AI-Learning-8000"
rem  Tighter:  change profile=any to profile=private in the two add rule lines
rem ==============================================================
setlocal
chcp 65001 >nul

rem --- 自提权 ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [..] Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  [1/4] Remove inbound BLOCK rules for python (they win over allow)
echo ============================================================
netsh advfirewall firewall delete rule name="Python" dir=in
netsh advfirewall firewall delete rule name="Python" dir=out
echo.

echo ============================================================
echo  [2/4] Allow inbound: python.exe + TCP 8000
echo ============================================================
netsh advfirewall firewall add rule name="AI-Learning-Python" dir=in action=allow program="C:\python313\python.exe" enable=yes profile=any
netsh advfirewall firewall add rule name="AI-Learning-8000" dir=in action=allow protocol=TCP localport=8000 enable=yes profile=any
echo.

echo ============================================================
echo  [3/4] Set the active network to Private (if it is not)
echo ============================================================
powershell -NoProfile -Command "try { $list = Get-NetConnectionProfile } catch { $list = @() }; if (-not $list) { Write-Host '  (could not read network profile - set it by hand: Settings > Network > WLAN > Private network)' } else { foreach ($p in $list) { if ($p.NetworkCategory -ne 'Private') { try { Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private; Write-Host ('  set Private: ' + $p.Name) } catch { Write-Host ('  skipped   : ' + $p.Name + ' - set it by hand') } } else { Write-Host ('  already Private: ' + $p.Name) } } }"
echo.

echo ============================================================
echo  [4/4] Your phone URL
echo ============================================================
powershell -NoProfile -Command "$s = New-Object System.Net.Sockets.UdpClient; try { $s.Connect('8.8.8.8', 53); $ip = $s.Client.LocalEndPoint.Address.ToString() } catch { $ip = '127.0.0.1' } finally { $s.Close() }; Write-Host ''; Write-Host ('  Phone  : http://' + $ip + ':8000/app/today.html'); Write-Host ('  This PC: http://127.0.0.1:8000/app/today.html'); Write-Host ''; try { $r = Invoke-RestMethod -Uri ('http://' + $ip + ':8000/') -TimeoutSec 3; Write-Host ('  LAN self-test: OK (backend V' + $r.version + ')') } catch { Write-Host '  LAN self-test: FAILED - start the backend first (start.bat)' }"

echo.
echo Done. On the phone: connect to the SAME Wi-Fi and open the Phone URL above.
echo If it still fails: check the router for "AP isolation" / guest network, and make sure the phone is not on a guest SSID.
echo.
pause
