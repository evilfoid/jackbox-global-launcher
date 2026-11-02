@echo off
rem Builds (first run only) and starts the local Jackbox server on 192.168.0.202
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

tasklist /fi "imagename eq jonahbox.exe" | find /i "jonahbox.exe" >nul
if not errorlevel 1 (
    echo The server is already running in another window - you don't need to start it again.
    echo To restart it, close the other server window first.
    pause
    exit /b 0
)

if not exist "certs\192.168.0.202.pem" (
    echo Creating a locally trusted HTTPS certificate...
    mkcert -install
    if not exist certs mkdir certs
    mkcert -cert-file certs\192.168.0.202.pem -key-file certs\192.168.0.202-key.pem 192.168.0.202 localhost 127.0.0.1
)

rem Rebuilds only when the source changed; a no-op build takes a second or two.
rem Without Rust installed, just runs the server that's already built.
where cargo >nul 2>&1
if not errorlevel 1 (
    echo Checking server build ^(a rebuild after code changes takes several minutes^)...
    cargo build --release
    if errorlevel 1 if not exist "target\release\jonahbox.exe" (pause & exit /b 1)
) else if not exist "target\release\jonahbox.exe" (
    echo Rust isn't installed, so the server can't be built. Install it from https://rustup.rs
    pause
    exit /b 1
)

for %%f in (target\release\*.exe) do set "SERVER=%%f"
"%SERVER%"
pause
