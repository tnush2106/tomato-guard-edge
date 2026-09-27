@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Khong tim thay moi truong .venv cua du an.
    echo Hay cai Python 3.12 va tao lai .venv truoc khi chay.
    echo.
    pause
    exit /b 1
)

set "PYTHON_BIN=.venv\Scripts\python.exe"

%PYTHON_BIN% test_image.py
if errorlevel 1 (
    echo.
    echo Khong the chay nhan dien. Kiem tra Python va cac thu vien trong requirements.txt.
)
echo.
pause
