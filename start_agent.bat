@echo off
rem ============================================================
rem  Meeting Agent - switch ON
rem
rem    start_agent.bat        -> MEETING mode: OCR capped to 2 CPU
rem                              threads (light, runs beside your meeting)
rem    start_agent.bat full   -> FULL mode: OCR may use all CPU threads
rem
rem  The cap lives inside the agent process only. stop_agent.bat
rem  releases everything.
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe tools\agent_ctl.py start %*
set EXITCODE=%errorlevel%

rem keep the window open briefly so the user sees the result
if "%EXITCODE%"=="0" (
    ping -n 4 127.0.0.1 >nul
) else (
    pause
)
exit /b %EXITCODE%
