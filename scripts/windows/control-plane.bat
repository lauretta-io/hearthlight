@echo off
setlocal EnableExtensions
title Hearthlight - Control Plane
cd /d "%~dp0\..\.."

echo Hearthlight control plane (UI + API)
echo Repo: %CD%
echo.

docker version >nul 2>&1 || (echo ERROR: Start Docker Desktop. & goto :fail)
docker compose version >nul 2>&1 || (echo ERROR: Install Docker Desktop. & goto :fail)
if not exist ".env" if exist "example.env" copy /Y example.env .env >nul
if not exist "shared\configs\config.yaml" if exist "shared\configs\example_config.yaml" copy /Y shared\configs\example_config.yaml shared\configs\config.yaml >nul

echo [1/4] Build...
docker compose build rabbitmq webapp || goto :fail
echo [2/4] Start db + rabbitmq...
docker compose up -d db rabbitmq || goto :fail
echo [3/4] Init database...
docker compose run --rm reset_db || goto :fail
echo [4/4] Start webapp...
docker compose up -d db rabbitmq webapp reverse_proxy || goto :fail

docker compose ps
curl.exe -s http://localhost:8000/readyz
echo.
echo Done: http://localhost:3000
start http://localhost:3000
pause
exit /b 0

:fail
echo Failed. See scripts\windows\README.md
pause
exit /b 1
