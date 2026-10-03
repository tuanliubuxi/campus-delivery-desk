@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Import a prepared image archive and start production without pulling or building images.
rem Usage: run-offline.bat [path-to-docker-images.tar]
cd /d "%~dp0"

where docker >nul 2>nul || (echo [ERROR] Docker CLI was not found.& exit /b 1)
docker info >nul 2>nul || (echo [ERROR] Docker Engine is not running.& exit /b 1)
if not exist ".env" (echo [ERROR] .env was not found.& exit /b 1)
findstr /c:"DJANGO_SECRET_KEY=replace-with-a-long-random-secret" ".env" >nul && (
  echo [ERROR] Refusing to start with the example DJANGO_SECRET_KEY.
  exit /b 1
)

set "CDD_IMAGE_ARCHIVE=%~1"
if not defined CDD_IMAGE_ARCHIVE (
  call :CDD_SELECT_IMAGE
  if errorlevel 1 exit /b 1
)
if not exist "%CDD_IMAGE_ARCHIVE%" (echo [ERROR] Docker archive not found: %CDD_IMAGE_ARCHIVE%& exit /b 1)

echo [INFO] Importing application and Caddy images...
docker image load -i "%CDD_IMAGE_ARCHIVE%"
if errorlevel 1 exit /b 1

docker compose config --quiet
if errorlevel 1 exit /b 1

echo [INFO] Applying database migrations...
docker compose run --rm --no-deps --pull never web python manage.py migrate
if errorlevel 1 exit /b 1
echo [INFO] Seeding initial configuration...
docker compose run --rm --no-deps --pull never web python manage.py seed_initial_config
if errorlevel 1 exit /b 1

docker compose run --rm --no-deps --pull never web python manage.py shell -c "from apps.accounts.models import User; from apps.common.enums import UserRole; raise SystemExit(0 if User.objects.filter(role=UserRole.ADMIN).exists() else 42)"
set "CDD_ADMIN_CHECK=%ERRORLEVEL%"
if "%CDD_ADMIN_CHECK%"=="42" (
  echo [INFO] No administrator exists. Create the first administrator now.
  docker compose run --rm --no-deps --pull never web python manage.py create_app_admin
  if errorlevel 1 exit /b 1
) else if not "%CDD_ADMIN_CHECK%"=="0" (
  echo [ERROR] Could not check the administrator state.
  exit /b 1
)

echo [INFO] Starting services without downloads or builds...
docker compose up -d --no-build --pull never
if errorlevel 1 (
  echo [ERROR] Service startup failed. Cleaning up partially started containers...
  docker compose down --remove-orphans
  exit /b 1
)
docker compose ps
echo [OK] Offline production services started.
exit /b 0

:CDD_SELECT_IMAGE
set "CDD_MATCHES=0"
for %%F in ("tags\*-docker-linux-*.tar" "..\*-docker-linux-*.tar" "*-docker-linux-*.tar") do if exist "%%~F" call :CDD_ADD_CANDIDATE "%%~fF"
if "!CDD_MATCHES!"=="0" (
  echo [ERROR] No Docker archive was found in the project, tags, or parent directory.
  exit /b 1
)

echo [INFO] Available Docker archives:
for /L %%I in (1,1,!CDD_MATCHES!) do echo   [%%I] !CDD_CANDIDATE[%%I]!
if "!CDD_MATCHES!"=="1" (
  set "CDD_IMAGE_ARCHIVE=!CDD_CANDIDATE[1]!"
  echo [INFO] Automatically selected the only available archive.
  exit /b 0
)

:CDD_SELECT_PROMPT
set "CDD_CHOICE="
set /p "CDD_CHOICE=Select a Docker archive [1-!CDD_MATCHES!] or 0 to cancel: "
if "!CDD_CHOICE!"=="0" exit /b 1
set "CDD_IMAGE_ARCHIVE="
for /L %%I in (1,1,!CDD_MATCHES!) do if "!CDD_CHOICE!"=="%%I" set "CDD_IMAGE_ARCHIVE=!CDD_CANDIDATE[%%I]!"
if not defined CDD_IMAGE_ARCHIVE (
  echo [ERROR] Invalid selection.
  goto CDD_SELECT_PROMPT
)
exit /b 0

:CDD_ADD_CANDIDATE
set "CDD_NEW_CANDIDATE=%~1"
if !CDD_MATCHES! GTR 0 for /L %%I in (1,1,!CDD_MATCHES!) do if /i "!CDD_CANDIDATE[%%I]!"=="!CDD_NEW_CANDIDATE!" exit /b 0
set /a CDD_MATCHES+=1
set "CDD_CANDIDATE[!CDD_MATCHES!]=!CDD_NEW_CANDIDATE!"
exit /b 0
