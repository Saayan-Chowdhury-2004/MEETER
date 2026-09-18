@echo off
rem ============================================================
rem  Meeting Agent - switch OFF
rem
rem  Kills every agent process. The CPU-thread cap and RAM the
rem  agent was using are released automatically - they existed
rem  only inside the agent process.
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    pause
    exit /b 1
)

.venv\Scripts\python.exe tools\agent_ctl.py stop
set EXITCODE=%errorlevel%

if "%EXITCODE%"=="0" (
    ping -n 4 127.0.0.1 >nul
) else (
    pause
)
exit /b %EXITCODE%
