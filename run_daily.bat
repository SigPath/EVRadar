@echo off
rem Skan dzienny dla Harmonogramu zadań Windows: dwuklik albo zaplanowane zadanie.
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\evradar.exe" (
    ".venv\Scripts\evradar.exe" run %*
) else (
    uv run evradar run %*
)

if errorlevel 1 (
    echo.
    echo Skan zakonczyl sie bledem. Sprawdz komunikaty powyzej.
    pause
)
