@echo off
setlocal
echo ============================================
echo   Building Kota Kow (KotaKow.exe) Portable
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo Generating Windows application icon...
python scripts\generate_icon.py

echo Building single portable KotaKow.exe...
pyinstaller --noconfirm --clean ^
    --onefile --noconsole ^
    --name KotaKow ^
    --icon=assets\kotakow.ico ^
    --collect-data certifi ^
    --collect-all _sounddevice_data ^
    --hidden-import sounddevice ^
    --hidden-import _sounddevice_data ^
    main.py

echo.
if exist "dist\KotaKow.exe" (
    echo Build succeeded! Portable executable ready at:
    echo   %CD%\dist\KotaKow.exe
) else (
    echo Build failed. Check the output above.
)
pause
