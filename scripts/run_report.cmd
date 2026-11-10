@echo off
setlocal
REM Task Scheduler entry point: collects 12 live PerfMon samples 5 seconds apart.
REM Use an absolute Python path in place of 'py -3' if Task Scheduler cannot find it.
set "PROJECT_DIR=%~dp0.."
py -3 "%PROJECT_DIR%\perfmon_report.py" --interval 5 --samples 12 --output "%PROJECT_DIR%\reports"
exit /b %ERRORLEVEL%
