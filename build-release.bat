@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Build private project, virtualenv, and Docker archives under tags\.
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

set "CDD_RUNNING="
for /f "delims=" %%C in ('docker compose ps --status running -q 2^>nul') do set "CDD_RUNNING=1"
if defined CDD_RUNNING (
  echo [ERROR] Compose services are running. Stop them before copying SQLite and runtime data.
  exit /b 1
)

if not exist "tags" mkdir "tags"
set "CDD_PROJECT=tags\%CDD_RELEASE%-project-private.zip"
set "CDD_VENV=tags\%CDD_RELEASE%-venv-windows-%CDD_ARCH%.zip"
set "CDD_DOCKER=tags\%CDD_RELEASE%-docker-linux-%CDD_ARCH%.tar"
set "CDD_MANIFEST=tags\%CDD_RELEASE%-manifest.txt"

for %%F in ("%CDD_PROJECT%" "%CDD_VENV%" "%CDD_DOCKER%" "%CDD_MANIFEST%") do if exist "%%~F" (
  echo [ERROR] Refusing to overwrite %%~F
  exit /b 1
)

echo [INFO] Building application image for linux/%CDD_ARCH%...
docker buildx build --platform "linux/%CDD_ARCH%" --load -t campus-delivery-desk-app:local -t "campus-delivery-desk-app:%CDD_RELEASE%" .
if errorlevel 1 exit /b 1

echo [INFO] Preparing Caddy image for linux/%CDD_ARCH%...
docker pull --platform "linux/%CDD_ARCH%" caddy:2
if errorlevel 1 exit /b 1

echo [INFO] Exporting Docker images...
docker image save -o "%CDD_DOCKER%" campus-delivery-desk-app:local "campus-delivery-desk-app:%CDD_RELEASE%" caddy:2
if errorlevel 1 exit /b 1

set "CDD_STAGE=%TEMP%\%CDD_RELEASE%-%RANDOM%-%RANDOM%"
mkdir "%CDD_STAGE%\%CDD_RELEASE%" >nul || exit /b 1
echo [INFO] Staging private project backup...
robocopy "." "%CDD_STAGE%\%CDD_RELEASE%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD ".venv" "tags" ".ruff_cache" ".pytest_cache" "__pycache__" "staticfiles" /XF "*.pyc" "*.pyo"
set "CDD_ROBOCOPY=!ERRORLEVEL!"
if !CDD_ROBOCOPY! GEQ 8 (
  echo [ERROR] Project staging failed with robocopy code !CDD_ROBOCOPY!.
  exit /b 1
)
tar -a -cf "%CDD_PROJECT%" -C "%CDD_STAGE%" "%CDD_RELEASE%"
if errorlevel 1 exit /b 1

if exist ".venv" (
  echo [INFO] Archiving the Windows virtual environment separately...
  tar -a -cf "%CDD_VENV%" -C "%~dp0" ".venv"
  if errorlevel 1 exit /b 1
) else (
  echo [WARN] .venv was not found; no virtualenv archive was created.
  set "CDD_VENV="
)

powershell -NoProfile -Command "$p=[IO.Path]::GetFullPath($env:CDD_STAGE); $t=[IO.Path]::GetFullPath($env:TEMP); if(-not $p.StartsWith($t)){throw 'Unsafe staging path'}; Remove-Item -LiteralPath $p -Recurse -Force"
if errorlevel 1 exit /b 1

for /f %%H in ('git rev-parse HEAD') do set "CDD_COMMIT=%%H"
> "%CDD_MANIFEST%" echo Release: %CDD_RELEASE%
>>"%CDD_MANIFEST%" echo Project version: %CDD_VERSION%
>>"%CDD_MANIFEST%" echo Git commit: %CDD_COMMIT%
>>"%CDD_MANIFEST%" echo Docker platform: linux/%CDD_ARCH%
>>"%CDD_MANIFEST%" echo Created: %DATE% %TIME%
>>"%CDD_MANIFEST%" echo.
powershell -NoProfile -Command "Get-ChildItem -LiteralPath 'tags' -File | Where-Object Name -Like '%CDD_RELEASE%-*' | Where-Object Name -NotLike '*-manifest.txt' | Get-FileHash -Algorithm SHA256 | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLowerInvariant(), $_.Path.Split([IO.Path]::DirectorySeparatorChar)[-1] } | Add-Content -LiteralPath '%CDD_MANIFEST%'"
if errorlevel 1 exit /b 1

echo.
echo [OK] Release artifacts created in tags\:
echo   %CDD_PROJECT%
if defined CDD_VENV echo   %CDD_VENV%
echo   %CDD_DOCKER%
echo   %CDD_MANIFEST%
echo [WARN] The private project archive contains .env and data. Store and transfer it securely.
exit /b 0
