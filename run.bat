@echo off
REM ============================================================================
REM  Peeker - one-click launcher
REM
REM    run.bat              start backend + frontend, then open the dashboard
REM    run.bat stop         stop both servers
REM    run.bat restart      stop first, then start again on fresh random ports
REM    run.bat status       show which ports are live and whether they answer
REM    run.bat logs         tail the backend + frontend logs
REM    run.bat help         this list
REM
REM  Ports are drawn at random from 21000-45000 - never the usual
REM  3000/3001/5173/8000/8080 - and each one is proven bindable before use.
REM  Pin them with PEEKER_BE_PORT / PEEKER_FE_PORT when you want stable URLs.
REM
REM  Implementation notes, each one learned the hard way:
REM    * no "|" inside the inline PowerShell - cmd parses it as its own pipe
REM      when it sits inside for /f backquotes, so ports are collected with
REM      foreach instead of a pipeline.
REM    * no "timeout /t" - it refuses to run when stdin is redirected, and
REM      "ping -n 2" is the reliable one-second sleep in that case.
REM    * every "for /f" that reads a file needs usebackq - without it cmd
REM      iterates the quoted string itself, not the file, so the ports file
REM      would silently read as empty.
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "ROOT=%CD%"
REM CD never keeps the trailing separator, so every path below needs its own.
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "LOGDIR=%ROOT%\logs"
set "STATE=%LOGDIR%\run-ports.txt"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

set "PYEXE=%BACKEND%\.venv\Scripts\python.exe"
set "NEXTBIN=%FRONTEND%\node_modules\next\dist\bin\next"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"

set "CMD=%~1"
if not defined CMD set "CMD=start"

if /i "%CMD%"=="start"    goto :do_start
if /i "%CMD%"=="stop"     goto :do_stop
if /i "%CMD%"=="restart"  goto :do_restart
if /i "%CMD%"=="status"   goto :do_status
if /i "%CMD%"=="logs"     goto :do_logs
if /i "%CMD%"=="help"     goto :do_help
if /i "%CMD%"=="/?"       goto :do_help
if /i "%CMD%"=="-h"       goto :do_help
echo Unknown command: %CMD%
goto :do_help

:do_help
echo.
echo   Peeker launcher
echo   ---------------
echo     run.bat            start both servers and open the dashboard
echo     run.bat stop       stop both servers
echo     run.bat restart    restart on freshly picked ports
echo     run.bat status     show current ports and health
echo     run.bat logs       tail both logs in new windows
echo     run.bat help       show this list
echo.
echo   Log folder: %LOGDIR%
echo.
goto :eof

REM ---------------------------------------------------------------------------
REM  pick_port -> PICKED    random free TCP port in 21000-45000
REM  foreach, not a pipeline: cmd would eat a "|" inside for /f backquotes.
REM ---------------------------------------------------------------------------
:pick_port
set "PICKED="
for /f "usebackq delims=" %%A in (`%PS% "$busy=@(); foreach($c in @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)){ $busy+=$c.LocalPort }; $r=[Random]::new(); for($i=0; $i -lt 900; $i++){ $p=$r.Next(21000,45000); if($busy -contains $p){ continue }; $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); try{ $l.Server.ExclusiveAddressUse=$true; $l.Start(); $l.Stop(); Write-Output $p; break }catch{} }"`) do set "PICKED=%%A"
goto :eof

REM ---------------------------------------------------------------------------
REM  probe <url> -> READY=1 when the endpoint answers 200, else READY=0
REM  $ProgressPreference matters: Invoke-WebRequest draws a "Reading web response"
REM  progress bar that lands in the for /f capture and hides the real value.
REM ---------------------------------------------------------------------------
:probe
set "READY=0"
for /f "usebackq delims=" %%A in (`%PS% "$ProgressPreference='SilentlyContinue'; try{ $r=Invoke-WebRequest -UseBasicParsing -Uri '%~1' -TimeoutSec 4; if($r.StatusCode -eq 200){ Write-Output 1 } }catch{}"`) do set "READY=%%A"
goto :eof

REM ---------------------------------------------------------------------------
REM  kill_port <port> -> stops the whole process tree holding that port
REM  Guarded: called with no argument the PowerShell would bind an empty
REM  -LocalPort and throw, so an undefined port is simply a no-op.
REM ---------------------------------------------------------------------------
:kill_port
if "%~1"=="" goto :eof
for /f "usebackq delims=" %%A in (`%PS% "foreach($c in @(Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue)){ & taskkill.exe /PID $c.OwningProcess /T /F | Out-Null; Write-Output ('stopped pid ' + $c.OwningProcess) }"`) do echo   %%A on port %~1
goto :eof
REM ---------------------------------------------------------------------------
REM  do_start
REM ---------------------------------------------------------------------------
:do_start
echo.
if not exist "%PYEXE%" (
    echo   ERROR: virtualenv backend belum ada.
    echo          Jalankan sekali:
    echo            python -m venv backend\.venv
    echo            backend\.venv\Scripts\pip install -r backend\requirements.txt
    goto :bail
)
if not exist "%NEXTBIN%" (
    echo   ERROR: dependensi frontend belum terpasang.
    echo          Jalankan sekali:
    echo            cd frontend
    echo            npm install
    goto :bail
)
set "NODEEXE="
for /f "usebackq delims=" %%A in (`where node 2^>nul`) do if not defined NODEEXE set "NODEEXE=%%A"
if not defined NODEEXE (
    echo   ERROR: Node.js tidak ditemukan di PATH.
    goto :bail
)

REM --- pick the two ports -----------------------------------------------------
set "BEPORT=%PEEKER_BE_PORT%"
set "FEPORT=%PEEKER_FE_PORT%"
if not defined BEPORT (
    call :pick_port
    if not defined PICKED (
        echo   ERROR: tidak menemukan port backend kosong di 21000-45000.
        goto :bail
    )
    set "BEPORT=!PICKED!"
)
if not defined FEPORT (
    call :pick_port
    if not defined PICKED (
        echo   ERROR: tidak menemukan port frontend kosong di 21000-45000.
        goto :bail
    )
    set "FEPORT=!PICKED!"
)
if "%BEPORT%"=="%FEPORT%" (
    call :pick_port
    if not defined PICKED (
        echo   ERROR: tidak menemukan port frontend kedua yang kosong.
        goto :bail
    )
    set "FEPORT=!PICKED!"
)

REM Anything still squatting on those exact ports would make uvicorn/Next die.
call :kill_port %BEPORT%
call :kill_port %FEPORT%

REM lib/api.ts keeps the relative "/backend" path, so the browser stays on one
REM origin and the host-scoped session cookie keeps working on any port.
REM NEXT_PUBLIC_API_URL is cleared on purpose: BACKEND_ORIGIN only tells
REM next.config.mjs where to forward that proxy, so the client code is untouched.
set "BACKEND_ORIGIN=http://127.0.0.1:%BEPORT%"
set "NEXT_PUBLIC_API_URL="

set "BEPROCID="
set "FEPROCID="
echo   backend  port %BEPORT%   (API docs: /docs)
REM The pid goes to a file, not through for /f: a redirected child inherits the
REM for /f pipe, so the capture would wait forever for an EOF that never comes.
%PS% "(Start-Process -FilePath '%PYEXE%' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','%BEPORT%' -WorkingDirectory '%BACKEND%' -RedirectStandardOutput '%LOGDIR%\backend.out.log' -RedirectStandardError '%LOGDIR%\backend.err.log' -PassThru).Id | Set-Content -LiteralPath '%LOGDIR%\backend.pid'"
set /p BEPROCID=<"%LOGDIR%\backend.pid"

set /a "N=0"
:wait_be
call :probe "http://127.0.0.1:%BEPORT%/health"
if "!READY!"=="1" goto :be_ok
set /a "N+=1"
if !N! geq 45 (
    echo   ERROR: backend tidak merespons /health dalam 45 detik.
    echo          lihat %LOGDIR%\backend.err.log
    goto :bail
)
ping -n 2 127.0.0.1 >nul
goto :wait_be
:be_ok
echo   backend  siap, pid !BEPROCID!.
echo.

echo   frontend port %FEPORT%
%PS% "(Start-Process -FilePath '%NODEEXE%' -ArgumentList 'node_modules\next\dist\bin\next','dev','-p','%FEPORT%','-H','127.0.0.1' -WorkingDirectory '%FRONTEND%' -RedirectStandardOutput '%LOGDIR%\frontend.out.log' -RedirectStandardError '%LOGDIR%\frontend.err.log' -PassThru).Id | Set-Content -LiteralPath '%LOGDIR%\frontend.pid'"
set /p FEPROCID=<"%LOGDIR%\frontend.pid"

set /a "N=0"
:wait_fe
call :probe "http://127.0.0.1:%FEPORT%/"
if "!READY!"=="1" goto :fe_ok
set /a "N+=1"
if !N! geq 120 (
    echo   ERROR: frontend tidak merespons dalam 120 detik.
    echo          lihat %LOGDIR%\frontend.err.log
    goto :bail
)
ping -n 2 127.0.0.1 >nul
goto :wait_fe
:fe_ok
echo   frontend siap, pid !FEPROCID!.
echo.

(
    echo BEPORT=%BEPORT%
    echo FEPORT=%FEPORT%
) > "%STATE%"

start "" "http://127.0.0.1:%FEPORT%"
echo   Dashboard dibuka di browser: http://127.0.0.1:%FEPORT%
echo   API docs                 : http://127.0.0.1:%BEPORT%/docs
echo   Log                      : %LOGDIR%
echo.
echo   Cara menutup:  run.bat stop
echo.
pause
goto :eof

:bail
echo.
pause
goto :eof

REM ---------------------------------------------------------------------------
REM  do_stop
REM ---------------------------------------------------------------------------
:do_stop
echo.
set "BEPORT="
set "FEPORT="
if exist "%STATE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%STATE%") do (
        if /i "%%A"=="BEPORT" set "BEPORT=%%B"
        if /i "%%A"=="FEPORT" set "FEPORT=%%B"
    )
)
REM Recorded ports first; 8000/3001 as a fallback for hand-started servers.
call :kill_port %BEPORT%
call :kill_port %FEPORT%
if not defined BEPORT call :kill_port 8000
if not defined FEPORT call :kill_port 3001
if exist "%STATE%" del /q "%STATE%" >nul 2>&1
echo   Selesai. Server Peeker dihentikan.
echo.
goto :eof

REM ---------------------------------------------------------------------------
REM  do_restart
REM ---------------------------------------------------------------------------
:do_restart
call :do_stop
goto :do_start

REM ---------------------------------------------------------------------------
REM  do_status
REM ---------------------------------------------------------------------------
:do_status
echo.
set "BEPORT="
set "FEPORT="
if exist "%STATE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%STATE%") do (
        if /i "%%A"=="BEPORT" set "BEPORT=%%B"
        if /i "%%A"=="FEPORT" set "FEPORT=%%B"
    )
)
if not defined BEPORT (
    echo   Tidak ada instance Peeker yang dicatat.
    echo   Jalankan run.bat untuk memulai.
    goto :eof
)
call :probe "http://127.0.0.1:%BEPORT%/health"
echo   backend  port %BEPORT%  ready=!READY!
call :probe "http://127.0.0.1:%FEPORT%/"
echo   frontend port %FEPORT%  ready=!READY!
echo.
echo   Dashboard : http://127.0.0.1:%FEPORT%
echo   API docs  : http://127.0.0.1:%BEPORT%/docs
echo.
goto :eof

REM ---------------------------------------------------------------------------
REM  do_logs
REM ---------------------------------------------------------------------------
:do_logs
start "Peeker Backend Log" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGDIR%\backend.out.log','%LOGDIR%\backend.err.log' -Wait -Tail 30"
start "Peeker Frontend Log" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGDIR%\frontend.out.log','%LOGDIR%\frontend.err.log' -Wait -Tail 30"
echo   Dua jendela log terbuka. Tutup dengan Ctrl+C atau tutup jendelanya.
goto :eof
