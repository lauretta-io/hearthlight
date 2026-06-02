@echo off
setlocal EnableExtensions
title Hearthlight - Full Video (CPU)
cd /d "%~dp0\..\.."

call :show_steps

call :require_docker
if errorlevel 1 goto :fail

call :ensure_config
if errorlevel 1 goto :fail

echo [1/5] Building services (first time may take a long while)...
docker compose build rabbitmq webapp ingestor association anomaly
if errorlevel 1 goto :fail

echo.
echo [2/5] Starting database and RabbitMQ...
docker compose up -d db rabbitmq
if errorlevel 1 goto :fail

echo.
echo [3/5] Initializing database...
docker compose run --rm reset_db
if errorlevel 1 goto :fail

echo.
echo [4/5] Starting full stack...
docker compose up -d db rabbitmq webapp reverse_proxy ingestor association anomaly
if errorlevel 1 goto :fail

echo.
echo [5/5] Checking status...
docker compose ps
echo.
curl.exe -s http://localhost:8000/readyz
echo.
echo  Next steps in the browser:
echo    1. Open http://localhost:3000
echo    2. Settings - Sources - upload a short MP4 - Save
echo    3. Monitor Run - Start
echo.
start http://localhost:3000
goto :done

:show_steps
echo.
echo  ============================================================
echo   HEARTHLIGHT - FULL VIDEO TEST (CPU)
echo  ============================================================
echo   Repo: %CD%
echo.
echo   BEFORE THIS SCRIPT:
echo     1. Docker Desktop is running
echo     2. You cloned the repo with submodules (see README.md)
echo.
echo   THIS SCRIPT WILL:
echo     [1/5] Build rabbitmq, webapp, ingestor, association, anomaly
echo     [2/5] Start database + RabbitMQ
echo     [3/5] Initialize database
echo     [4/5] Start full stack
echo     [5/5] Show status + open browser
echo.
echo   FIRST BUILD: often 30-60+ minutes. Use a short MP4 for testing.
echo.
echo   AFTER THIS SCRIPT (in the browser):
echo     1. Settings - Sources - upload short MP4 - Save
echo     2. Monitor Run - Start
echo     3. Wait several minutes on CPU
echo.
echo   Online guide: github.com/lauretta-io/hearthlight/tree/main/scripts/windows
echo  ============================================================
echo.
exit /b 0

:require_docker
docker version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker is not running. Start Docker Desktop, then run this file again.
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker compose is not available. Install Docker Desktop.
  exit /b 1
)
exit /b 0

:ensure_config
if not exist ".env" (
  if exist "example.env" (
    echo Creating .env from example.env...
    copy /Y example.env .env >nul
  ) else (
    echo ERROR: Missing .env and example.env
    exit /b 1
  )
)
if not exist "shared\configs\config.yaml" (
  if exist "shared\configs\example_config.yaml" (
    echo Creating config.yaml from example...
    copy /Y shared\configs\example_config.yaml shared\configs\config.yaml >nul
  ) else (
    echo ERROR: Missing shared\configs\config.yaml
    exit /b 1
  )
)
exit /b 0

:fail
echo.
echo  Something failed. Scroll up for the error message.
echo  Logs: docker compose logs --tail=120 ingestor
echo  Help: scripts\windows\README.txt
echo.
pause
exit /b 1

:done
echo  Press any key to close this window.
pause >nul
exit /b 0
