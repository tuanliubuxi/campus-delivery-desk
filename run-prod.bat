@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Production Windows entry point: validate configuration and orchestrate Compose startup.
rem Production uses the repository's Docker Compose + Caddy topology.
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Docker CLI is not installed or is not on PATH.
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Docker Engine is not running. Start Docker Desktop and retry.
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env was not found. Copy .env.example to .env and replace every example value.
  exit /b 1
)

findstr /c:"DJANGO_SECRET_KEY=replace-with-a-long-random-secret" ".env" >nul
if not errorlevel 1 (
  echo [ERROR] Refusing to start production with the example DJANGO_SECRET_KEY.
  exit /b 1
)

docker compose config --quiet
if errorlevel 1 exit /b %ERRORLEVEL%

if /i "%~1"=="--check" (
  echo [OK] Docker Engine, .env and Compose configuration are ready.
  exit /b 0
)

echo [INFO] Building production images...
docker compose build
if errorlevel 1 exit /b 1

rem Migrations run as a one-off container before long-running services are replaced.
echo [INFO] Applying production database migrations...
docker compose run --rm web python manage.py migrate
if errorlevel 1 exit /b 1

echo [INFO] Starting web, scheduler and Caddy...
docker compose up -d
if errorlevel 1 exit /b 1

docker compose ps
echo [OK] Production services started. Use "docker compose logs -f" to follow logs.
exit /b 0
