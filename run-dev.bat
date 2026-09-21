@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Local Windows entry point: validate prerequisites, migrate SQLite, then serve Django.
rem Always run from the repository root, including when launched by double-click.
cd /d "%~dp0"

set "CDD_PYTHON=.venv\Scripts\python.exe"
if not exist "%CDD_PYTHON%" (
  echo [ERROR] Python virtual environment was not found.
  echo Create it with: python -m venv .venv
  echo Then install dependencies with: .venv\Scripts\python.exe -m pip install -e ".[dev]"
  exit /b 1
)

if not exist "data\db" mkdir "data\db"
if not exist "data\media" mkdir "data\media"
if not exist "data\backups" mkdir "data\backups"
if not exist "data\tmp" mkdir "data\tmp"
if not exist "data\logs" mkdir "data\logs"

set "DJANGO_SETTINGS_MODULE=config.settings.dev"

if /i "%~1"=="--check" (
  echo [INFO] Checking the development environment...
  "%CDD_PYTHON%" manage.py check
  exit /b !ERRORLEVEL!
)

echo [INFO] Applying development database migrations...
"%CDD_PYTHON%" manage.py migrate
if errorlevel 1 exit /b 1

echo [INFO] Starting Django development server at http://127.0.0.1:8000/
"%CDD_PYTHON%" manage.py runserver 0.0.0.0:8000
exit /b %ERRORLEVEL%
