@echo off
setlocal
title PBL Team 16 Dashboard (pbl-team-16)

cd /d "%~dp0"

echo ========================================================
echo   Starting PBL Team 16 Dashboard (pbl-team-16)...
echo   Directory: %CD%
echo ========================================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    goto :launch
)

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
    goto :launch
)

where streamlit >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    goto :launch
)

echo Virtual environment not found. Setting up .venv and installing dependencies...
python -m venv .venv
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not create Python virtual environment.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

:launch
echo Launching Team 16 Dashboard on port 8502...
python -m streamlit run app.py --server.port 8502

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Team 16 Dashboard exited with an error.
    pause
)
endlocal
