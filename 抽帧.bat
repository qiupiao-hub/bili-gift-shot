@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 还没装依赖，先双击 install.bat
  pause
  exit /b 1
)
if "%~1"=="" (
  echo 用法（把录制文件拖到本文件上即可）：
  echo   extract.bat "D:\Videos\直播姬录制.mp4"
  echo   extract.bat "D:\Videos\直播姬录制.mp4" --rec-start "2026-10-23 23:00:00" --offset 2
  echo 只想看看时间算得对不对，加 --dry-run
  pause
  exit /b 1
)
".venv\Scripts\python.exe" extract_frames.py --csv shots\gifts.csv --video "%~1" %2 %3 %4 %5 %6 %7 %8
pause
