@echo off
REM Smoke-check Settings APIs (works when .ps1 scripts are blocked by execution policy).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_settings_api.ps1" %*
exit /b %ERRORLEVEL%
