@echo off
setlocal EnableExtensions
title Hearthlight - Full Video (CPU)
cd /d "%~dp0\..\.."

echo Hearthlight full video (CPU). First build may take 30-60+ minutes.
echo Repo: %CD%
echo.

docker version >nul 2>&1 || (echo ERROR: Start Docker Desktop. & goto :fail)
docker compose version >nul 2>&1 || (echo ERROR: Install Docker Desktop. & goto :fail)
if not exist ".env" if exist "example.env" copy /Y example.env .env >nul
if not exist "shared\configs\config.yaml" if exist "shared\configs\example_config.yaml" copy /Y shared\configs\example_config.yaml shared\configs\config.yaml >nul

echo [1/5] Build...
docker compose build rabbitmq webapp ingestor association anomaly || goto :fail
echo [2/5] Start db + rabbitmq...
docker compose up -d db rabbitmq || goto :fail
echo [3/5] Init database...
docker compose run --rm reset_db || goto :fail
echo [4/5] Start stack...
docker compose up -d db rabbitmq webapp reverse_proxy ingestor association anomaly || goto :fail
echo [5/5] Status...
docker compose ps
curl.exe -s http://localhost:8000/readyz
echo.
echo Browser: Settings - Sources - upload MP4 - Save - Monitor Run - Start
start http://localhost:3000
pause
exit /b 0

:fail
echo Failed. Logs: docker compose logs --tail=120 ingestor
echo Help: scripts\windows\README.md
pause
exit /b 1
