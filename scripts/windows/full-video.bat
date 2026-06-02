@echo off
setlocal EnableExtensions
title Hearthlight - Full Video (CPU)
cd /d "%~dp0\..\.."

echo Hearthlight full video (CPU). First build may take 30-60+ minutes.
echo Requires: Docker Desktop running. Clone repo first (see README.md).
echo Repo: %CD%
echo.

docker version >nul 2>&1 || (echo ERROR: Start Docker Desktop. & goto :fail)
docker compose version >nul 2>&1 || (echo ERROR: Install Docker Desktop. & goto :fail)
if not exist ".env" if exist "example.env" copy /Y example.env .env >nul
if not exist "shared\configs\config.yaml" if exist "shared\configs\example_config.yaml" copy /Y shared\configs\example_config.yaml shared\configs\config.yaml >nul

echo [1/6] Start database (Postgres must be up before init)...
docker compose up -d db || goto :fail
call :wait_for_db || goto :fail

echo [2/6] Build images...
docker compose build rabbitmq webapp ingestor association anomaly || goto :fail

echo [3/6] Initialize database (run before webapp / workers)...
docker compose run --rm reset_db || goto :fail

echo [4/6] Start stack...
docker compose up -d db rabbitmq webapp reverse_proxy ingestor association anomaly || goto :fail

echo [5/6] Status...
docker compose ps
curl.exe -s http://localhost:8000/readyz
echo.
echo Browser: Settings - Sources - upload MP4 - Save - Monitor Run - Start
start http://localhost:3000
pause
exit /b 0

:wait_for_db
echo Waiting for Postgres to be ready...
for /L %%i in (1,1,60) do (
  docker compose exec -T db pg_isready -U postgres -d hearthlight >nul 2>&1 && exit /b 0
  timeout /t 2 /nobreak >nul
)
echo ERROR: Database did not become ready in time.
exit /b 1

:fail
echo Failed. If schema errors: docker compose run --rm reset_db
echo Logs: docker compose logs --tail=120 ingestor
echo Help: scripts\windows\README.md (WSL2 if Docker will not start)
pause
exit /b 1
