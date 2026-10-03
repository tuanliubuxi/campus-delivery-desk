@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Root mode selects a versioned runtime ZIP and extracts it under deployments\.
rem Runtime mode imports the Docker tar next to this script and starts production.
rem Usage: run-offline.bat [runtime.zip^|docker-images.tar]
cd /d "%~dp0"
set "CDD_LAUNCH_ROOT=%CD%"

where docker >nul 2>nul || (echo [ERROR] Docker CLI was not found.& exit /b 1)
docker info >nul 2>nul || (echo [ERROR] Docker Engine is not running.& exit /b 1)

set "CDD_HOST_ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "CDD_HOST_ARCH=arm64"
set "CDD_IMAGE_ARCHIVE="
set "CDD_RUNTIME_ARCHIVE="
set "CDD_ARGUMENT=%~1"
if defined CDD_ARGUMENT (
  if /i "%~x1"==".zip" (
    set "CDD_RUNTIME_ARCHIVE=%~f1"
  ) else (
    set "CDD_IMAGE_ARCHIVE=%~f1"
  )
) else (
  rem A runtime bundle always contains a local Docker tar, so prefer it in that mode.
  call :CDD_RESET_CANDIDATES
  for %%F in ("*-docker-linux-%CDD_HOST_ARCH%.tar") do if exist "%%~F" call :CDD_ADD_CANDIDATE "%%~fF"
  if !CDD_MATCHES! GTR 0 (
    set "CDD_SELECTION_LABEL=Docker archives"
    call :CDD_SELECT_CANDIDATE
    if errorlevel 1 exit /b 1
    set "CDD_IMAGE_ARCHIVE=!CDD_SELECTED!"
  ) else (
    rem Root mode reads the new per-release tags layout and the previous flat layout.
    call :CDD_RESET_CANDIDATES
    if exist "tags" for /r "tags" %%F in (*-offline-runtime-%CDD_HOST_ARCH%.zip) do call :CDD_ADD_CANDIDATE "%%~fF"
    if !CDD_MATCHES! GTR 0 (
      set "CDD_SELECTION_LABEL=offline runtime bundles for %CDD_HOST_ARCH%"
      call :CDD_SELECT_CANDIDATE
      if errorlevel 1 exit /b 1
      set "CDD_RUNTIME_ARCHIVE=!CDD_SELECTED!"
    ) else (
      rem Legacy standalone Docker tars remain usable when no runtime bundle exists.
      call :CDD_RESET_CANDIDATES
      if exist "tags" for /r "tags" %%F in (*-docker-linux-%CDD_HOST_ARCH%.tar) do call :CDD_ADD_CANDIDATE "%%~fF"
      for %%F in ("..\*-docker-linux-%CDD_HOST_ARCH%.tar") do if exist "%%~F" call :CDD_ADD_CANDIDATE "%%~fF"
      if "!CDD_MATCHES!"=="0" (
        echo [ERROR] No %CDD_HOST_ARCH% offline runtime bundle or Docker archive was found.
        exit /b 1
      )
      set "CDD_SELECTION_LABEL=legacy Docker archives for %CDD_HOST_ARCH%"
      call :CDD_SELECT_CANDIDATE
      if errorlevel 1 exit /b 1
      set "CDD_IMAGE_ARCHIVE=!CDD_SELECTED!"
    )
  )
)

if defined CDD_RUNTIME_ARCHIVE goto CDD_DEPLOY_RUNTIME
goto CDD_RUN_IMAGE

:CDD_DEPLOY_RUNTIME
if not exist "%CDD_RUNTIME_ARCHIVE%" (echo [ERROR] Runtime bundle not found: %CDD_RUNTIME_ARCHIVE%& exit /b 1)
if not exist ".env" (echo [ERROR] Root .env was not found. It is the stable configuration shared by deployments.& exit /b 1)
findstr /c:"DJANGO_SECRET_KEY=replace-with-a-long-random-secret" ".env" >nul && (
  echo [ERROR] Refusing to deploy with the example root DJANGO_SECRET_KEY.
  exit /b 1
)

set "CDD_DEPLOYMENTS=%CDD_LAUNCH_ROOT%\deployments"
for %%F in ("%CDD_RUNTIME_ARCHIVE%") do set "CDD_DEPLOYMENT_NAME=%%~nF"
set "CDD_DEPLOYMENT_DIR=%CDD_DEPLOYMENTS%\%CDD_DEPLOYMENT_NAME%"
if not exist "%CDD_DEPLOYMENTS%" mkdir "%CDD_DEPLOYMENTS%" || exit /b 1
if not exist "%CDD_DEPLOYMENT_DIR%" (
  echo [INFO] Extracting %CDD_RUNTIME_ARCHIVE%
  echo [INFO] Deployment directory: %CDD_DEPLOYMENT_DIR%
  set "CDD_ARCHIVE_TO_EXPAND=%CDD_RUNTIME_ARCHIVE%"
  powershell -NoProfile -Command "Expand-Archive -LiteralPath $env:CDD_ARCHIVE_TO_EXPAND -DestinationPath $env:CDD_DEPLOYMENTS"
  if errorlevel 1 exit /b 1
) else (
  echo [INFO] Reusing existing deployment directory: %CDD_DEPLOYMENT_DIR%
)
if not exist "%CDD_DEPLOYMENT_DIR%\run-offline.bat" (
  echo [ERROR] The runtime bundle did not contain the expected deployment directory.
  exit /b 1
)
for %%D in (db media backups tmp logs) do if not exist "%CDD_LAUNCH_ROOT%\data\%%D" mkdir "%CDD_LAUNCH_ROOT%\data\%%D" || exit /b 1

pushd "%CDD_DEPLOYMENT_DIR%" || exit /b 1
set "CDD_DATA_PATH=..\..\data"
set "CDD_ENV_FILE=..\..\.env"
call run-offline.bat
set "CDD_DEPLOY_RESULT=!ERRORLEVEL!"
popd
exit /b !CDD_DEPLOY_RESULT!

:CDD_RUN_IMAGE
if not exist "%CDD_IMAGE_ARCHIVE%" (echo [ERROR] Docker archive not found: %CDD_IMAGE_ARCHIVE%& exit /b 1)
if not defined CDD_ENV_FILE set "CDD_ENV_FILE=.env"
if not defined CDD_DATA_PATH set "CDD_DATA_PATH=./data"
if not exist "%CDD_ENV_FILE%" (echo [ERROR] Environment file not found: %CDD_ENV_FILE%& exit /b 1)
findstr /c:"DJANGO_SECRET_KEY=replace-with-a-long-random-secret" "%CDD_ENV_FILE%" >nul && (
  echo [ERROR] Refusing to start with the example DJANGO_SECRET_KEY.
  exit /b 1
)

echo [INFO] Importing application and Caddy images...
docker image load -i "%CDD_IMAGE_ARCHIVE%"
if errorlevel 1 exit /b 1

docker compose --env-file "%CDD_ENV_FILE%" config --quiet
if errorlevel 1 exit /b 1

echo [INFO] Applying database migrations...
docker compose --env-file "%CDD_ENV_FILE%" run --rm --no-deps --pull never web python manage.py migrate
if errorlevel 1 exit /b 1
echo [INFO] Seeding initial configuration...
docker compose --env-file "%CDD_ENV_FILE%" run --rm --no-deps --pull never web python manage.py seed_initial_config
if errorlevel 1 exit /b 1

docker compose --env-file "%CDD_ENV_FILE%" run --rm --no-deps --pull never web python manage.py shell -c "from apps.accounts.models import User; from apps.common.enums import UserRole; raise SystemExit(0 if User.objects.filter(role=UserRole.ADMIN).exists() else 42)"
set "CDD_ADMIN_CHECK=%ERRORLEVEL%"
if "%CDD_ADMIN_CHECK%"=="42" (
  echo [INFO] No administrator exists. Create the first administrator now.
  docker compose --env-file "%CDD_ENV_FILE%" run --rm --no-deps --pull never web python manage.py create_app_admin
  if errorlevel 1 exit /b 1
) else if not "%CDD_ADMIN_CHECK%"=="0" (
  echo [ERROR] Could not check the administrator state.
  exit /b 1
)

echo [INFO] Starting services without downloads or builds...
docker compose --env-file "%CDD_ENV_FILE%" up -d --no-build --pull never
if errorlevel 1 (
  echo [ERROR] Service startup failed. Cleaning up partially started containers...
  docker compose --env-file "%CDD_ENV_FILE%" down --remove-orphans
  exit /b 1
)
docker compose --env-file "%CDD_ENV_FILE%" ps
echo [OK] Offline production services started.
exit /b 0

:CDD_RESET_CANDIDATES
set "CDD_MATCHES=0"
set "CDD_SELECTED="
exit /b 0

:CDD_SELECT_CANDIDATE
echo [INFO] Available %CDD_SELECTION_LABEL%:
for /L %%I in (1,1,!CDD_MATCHES!) do echo   [%%I] !CDD_CANDIDATE[%%I]!
if "!CDD_MATCHES!"=="1" (
  set "CDD_SELECTED=!CDD_CANDIDATE[1]!"
  echo [INFO] Automatically selected the only available candidate.
  exit /b 0
)
:CDD_SELECT_PROMPT
set "CDD_CHOICE="
set /p "CDD_CHOICE=Select [1-!CDD_MATCHES!] or 0 to cancel: "
if "!CDD_CHOICE!"=="0" exit /b 1
set "CDD_SELECTED="
for /L %%I in (1,1,!CDD_MATCHES!) do if "!CDD_CHOICE!"=="%%I" set "CDD_SELECTED=!CDD_CANDIDATE[%%I]!"
if not defined CDD_SELECTED (
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
