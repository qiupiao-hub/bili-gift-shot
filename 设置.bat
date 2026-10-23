@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 还没装依赖，先双击 install.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 gift_shot.py --setup
pause
