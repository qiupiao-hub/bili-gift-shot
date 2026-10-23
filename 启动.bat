@echo off
chcp 65001 >nul
cd /d "%~dp0"
title B站送礼自动截图

if not exist ".venv\Scripts\pythonw.exe" (
  echo 第一次使用，先安装依赖（只需要一次，几分钟）...
  set "BILI_NO_PAUSE=1"
  call "%~dp0install.bat"
  set "BILI_NO_PAUSE="
)

if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo [错误] 依赖没装好，请先双击 install.bat 看具体报错。
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0gui.py"
exit /b 0
