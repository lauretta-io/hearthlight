@echo off
setlocal EnableExtensions
title Hearthlight - Control Plane
cd /d "%~dp0\..\.."

echo.
echo  Hearthlight - Control Plane (UI + API only)
echo  ==========================================
echo  Repo: %CD%
echo.

call :require_docker
if errorlevel 1 goto :fail

call :ensure_config
if errorlevel 1 goto :fail

echo [1/4] Building rabbitmq and webapp (first time may take a while)...
docker compose build rabbitmq webapp
if errorlevel 1 goto :fail

echo.
echo [2/4] Starting database and RabbitMQ...
docker compose up -d db rabbitmq
if errorlevel 1 goto :fail

echo.
echo [3/4] Initializing database...
docker compose run --rm reset_db
if errorlevel 1 goto :fail

echo.
echo [4/4] Starting webapp and dashboard...
docker compose up -d db rabbitmq webapp reverse_proxy
if errorlevel 1 goto :fail

echo.
echo  Done. Checking status...
docker compose ps
echo.
curl.exe -s http://localhost:8000/readyz
echo.
echo  Open the dashboard: http://localhost:3000
start http://localhost:3000
echo.
goto :done

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
echo  See scripts\windows\README.txt and docs\containers.md
echo.
pause
exit /b 1

:done
echo  Press any key to close this window.
pause >nul
exit /b 0
