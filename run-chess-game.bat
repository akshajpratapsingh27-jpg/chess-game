@echo off
setlocal
cd /d "%~dp0"

where g++ >nul 2>nul
if errorlevel 1 (
    echo G++ was not found. Install MinGW/G++ and add it to PATH.
    pause
    exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
    echo Node.js was not found. Install Node.js and add it to PATH.
    pause
    exit /b 1
)

echo Building Vice chess engine...
g++ -std=c++17 *.cpp -O2 -Wall -Wextra -Werror -o vice12_smp.exe
if errorlevel 1 (
    echo Engine build failed.
    pause
    exit /b 1
)

echo.
echo Chess game server starting.
echo Open http://127.0.0.1:3000 in your browser.
echo Keep this window open while playing. Press Ctrl+C to stop the server.
echo.
node chess-server.js
