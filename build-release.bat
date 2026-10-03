@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Build a private project backup and a self-contained Docker runtime archive under tags\.
rem Usage: build-release.bat [amd64^|arm64] [release-name]
cd /d "%~dp0"

set "CDD_ARCH=%~1"
if not defined CDD_ARCH set "CDD_ARCH=amd64"
if /i not "%CDD_ARCH%"=="amd64" if /i not "%CDD_ARCH%"=="arm64" (
  echo [ERROR] Architecture must be amd64 or arm64.
  exit /b 1
)

where docker >nul 2>nul || (echo [ERROR] Docker CLI was not found.& exit /b 1)
where tar >nul 2>nul || (echo [ERROR] tar.exe was not found.& exit /b 1)
where robocopy >nul 2>nul || (echo [ERROR] robocopy was not found.& exit /b 1)
docker info >nul 2>nul || (echo [ERROR] Docker Engine is not running.& exit /b 1)

for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "$match=Select-String -LiteralPath 'pyproject.toml' -Pattern '^version = '; $match[0].Line.Split([char]34)[1]"`) do set "CDD_VERSION=%%V"
if not defined CDD_VERSION (
  echo [ERROR] Could not read the project version from pyproject.toml.
  exit /b 1
)
for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "CDD_DATE=%%D"

set "CDD_RELEASE=%~2"
if not defined CDD_RELEASE set "CDD_RELEASE=campus-delivery-desk-v%CDD_VERSION%-%CDD_DATE%"
echo(%CDD_RELEASE%| findstr /r /x "[A-Za-z0-9][A-Za-z0-9._-]*" >nul || (
  echo [ERROR] Release name may contain only letters, numbers, dot, underscore, and hyphen.
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env was not found. The private project archive must contain deployable configuration.
  exit /b 1
)
findstr /c:"DJANGO_SECRET_KEY=replace-with-a-long-random-secret" ".env" >nul && (
  echo [ERROR] Refusing to package the example DJANGO_SECRET_KEY.
  exit /b 1
)

git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
  echo [ERROR] Commit tracked changes before creating a versioned release archive.
  exit /b 1
)
for /f %%H in ('git rev-parse HEAD') do set "CDD_COMMIT=%%H"
set "CDD_HOST_ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "CDD_HOST_ARCH=arm64"

set "CDD_RUNNING="
for /f "delims=" %%C in ('docker compose ps --status running -q 2^>nul') do set "CDD_RUNNING=1"
if defined CDD_RUNNING (
  echo [ERROR] Compose services are running. Stop them before copying SQLite and runtime data.
  exit /b 1
)

if not exist "tags" mkdir "tags"
set "CDD_PROJECT=tags\%CDD_RELEASE%-project-private-windows-%CDD_HOST_ARCH%.zip"
set "CDD_RUNTIME=tags\%CDD_RELEASE%-offline-runtime-%CDD_ARCH%.zip"
set "CDD_MANIFEST=tags\%CDD_RELEASE%-manifest-%CDD_ARCH%.txt"
set "CDD_DOCKER_NAME=%CDD_RELEASE%-docker-linux-%CDD_ARCH%.tar"

for %%F in ("%CDD_RUNTIME%" "%CDD_MANIFEST%") do if exist "%%~F" (
  echo [ERROR] Refusing to overwrite %%~F
  exit /b 1
)
set "CDD_REUSE_PROJECT="
if exist "%CDD_PROJECT%" (
  for %%M in ("tags\%CDD_RELEASE%-manifest-*.txt") do if exist "%%~M" findstr /x /c:"Git commit: %CDD_COMMIT%" "%%~M" >nul && set "CDD_REUSE_PROJECT=1"
  if not defined CDD_REUSE_PROJECT (
    echo [ERROR] Existing project backup has no manifest for Git commit %CDD_COMMIT%.
    echo Use a new release name or remove the incomplete/stale project backup.
    exit /b 1
  )
)

set "CDD_STAGE=%TEMP%\%CDD_RELEASE%-%CDD_ARCH%-%RANDOM%-%RANDOM%"
mkdir "%CDD_STAGE%" >nul || exit /b 1
set "CDD_DOCKER=%CDD_STAGE%\%CDD_DOCKER_NAME%"

echo [INFO] Building application image for linux/%CDD_ARCH%...
docker buildx build --platform "linux/%CDD_ARCH%" --load -t campus-delivery-desk-app:local -t "campus-delivery-desk-app:%CDD_RELEASE%" .
if errorlevel 1 exit /b 1

echo [INFO] Preparing Caddy image for linux/%CDD_ARCH%...
docker pull --platform "linux/%CDD_ARCH%" caddy:2
if errorlevel 1 exit /b 1

echo [INFO] Exporting Docker images...
docker image save -o "%CDD_DOCKER%" campus-delivery-desk-app:local "campus-delivery-desk-app:%CDD_RELEASE%" caddy:2
if errorlevel 1 exit /b 1

if not defined CDD_REUSE_PROJECT (
  mkdir "%CDD_STAGE%\%CDD_RELEASE%" >nul || exit /b 1
  echo [INFO] Staging private project backup, including the host virtual environment...
  robocopy "." "%CDD_STAGE%\%CDD_RELEASE%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD "tags" ".ruff_cache" ".pytest_cache" "__pycache__" "staticfiles" /XF "*.pyc" "*.pyo"
  set "CDD_ROBOCOPY=!ERRORLEVEL!"
  if !CDD_ROBOCOPY! GEQ 8 (
    echo [ERROR] Project staging failed with robocopy code !CDD_ROBOCOPY!.
    exit /b 1
  )
  tar -a -cf "%CDD_PROJECT%" -C "%CDD_STAGE%" "%CDD_RELEASE%"
  if errorlevel 1 exit /b 1
) else (
  echo [INFO] Reusing the project backup already verified for this Git commit.
)

set "CDD_RUNTIME_DIR=%CDD_STAGE%\%CDD_RELEASE%-offline-runtime-%CDD_ARCH%"
mkdir "%CDD_RUNTIME_DIR%" >nul || exit /b 1
echo [INFO] Staging the self-contained offline runtime bundle...
for %%F in (run-offline.bat run-offline.sh docker-compose.yml Caddyfile .env .env.example README.md LICENSE) do copy /Y "%%F" "%CDD_RUNTIME_DIR%\%%F" >nul || exit /b 1
copy /Y "%CDD_DOCKER%" "%CDD_RUNTIME_DIR%\%CDD_DOCKER_NAME%" >nul || exit /b 1
robocopy "data" "%CDD_RUNTIME_DIR%\data" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
set "CDD_ROBOCOPY=!ERRORLEVEL!"
if !CDD_ROBOCOPY! GEQ 8 (
  echo [ERROR] Runtime data staging failed with robocopy code !CDD_ROBOCOPY!.
  exit /b 1
)
tar -a -cf "%CDD_RUNTIME%" -C "%CDD_STAGE%" "%CDD_RELEASE%-offline-runtime-%CDD_ARCH%"
if errorlevel 1 exit /b 1

powershell -NoProfile -Command "$p=[IO.Path]::GetFullPath($env:CDD_STAGE); $t=[IO.Path]::GetFullPath($env:TEMP); if(-not $p.StartsWith($t)){throw 'Unsafe staging path'}; Remove-Item -LiteralPath $p -Recurse -Force"
if errorlevel 1 exit /b 1

powershell -NoProfile -Command "$lines=@('Release: %CDD_RELEASE%','Project version: %CDD_VERSION%','Git commit: %CDD_COMMIT%','Docker platform: linux/%CDD_ARCH%',('Created: '+(Get-Date -Format o)),''); $lines | Set-Content -LiteralPath '%CDD_MANIFEST%' -Encoding utf8; Get-FileHash -Algorithm SHA256 -LiteralPath '%CDD_PROJECT%','%CDD_RUNTIME%' | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLowerInvariant(), $_.Path.Split([IO.Path]::DirectorySeparatorChar)[-1] } | Add-Content -LiteralPath '%CDD_MANIFEST%' -Encoding utf8"
if errorlevel 1 exit /b 1

echo.
echo [OK] Release artifacts created in tags\:
echo   %CDD_PROJECT%
echo   %CDD_RUNTIME%
echo   %CDD_MANIFEST%
echo [WARN] The private project archive contains .env and data. Store and transfer it securely.
exit /b 0
