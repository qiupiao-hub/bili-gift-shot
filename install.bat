@echo off
chcp 65001 >nul
cd /d "%~dp0"
title B站送礼自动截图 - 安装依赖
echo ==========================================
echo   B站送礼自动截图 - 安装依赖
echo ==========================================
echo.

rem ---- 找一个带 tkinter 的 Python（界面要用它） ----
set "PYEXE="
call :try py -3.11
call :try py -3.12
call :try py -3.13
call :try python
for /d %%D in ("%APPDATA%\uv\python\cpython-*") do call :try "%%~fD\python.exe"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try "%%~fD\python.exe"

if not defined PYEXE (
  echo [错误] 没找到带 tkinter 的 Python（图形界面要用它）。
  echo        请装 Python 3.10 以上，安装时勾选 "tcl/tk and IDLE" 和 "Add python.exe to PATH"。
  echo        装好后重新双击本文件。
  pause
  exit /b 1
)
echo 使用解释器：%PYEXE%
%PYEXE% -c "import sys; print('Python', sys.version.split()[0])"
goto :venv

:try
if defined PYEXE goto :eof
%* -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%*"
goto :eof

:venv
rem ---- 旧虚拟环境里没 tkinter 就重建 ----
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
  if errorlevel 1 (
    echo 旧的虚拟环境里没有 tkinter，正在重建 .venv ...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建虚拟环境 .venv ...
  %PYEXE% -m venv .venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败
    pause
    exit /b 1
  )
)

echo 正在升级 pip ...
".venv\Scripts\python.exe" -m pip install -U pip -q
echo 正在安装依赖（第一次要几分钟，请耐心等）...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [错误] 依赖安装失败，把上面的报错复制给懂的人看
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo [错误] 依赖装完了，但虚拟环境里还是没有 tkinter，请换一个完整版的 Python 重装。
  pause
  exit /b 1
)

echo.
echo ==========================================
echo   装好了。以后双击「启动.bat」就能打开界面。
echo   第一次打开时：
echo   1. 填直播间号（地址栏 live.bilibili.com/ 后面那串数字）
echo   2. 截图窗口选「自动找直播姬的直播间窗口」
echo   3. 设礼物金额门槛，点「开始监听」
echo ==========================================
if not defined BILI_NO_PAUSE pause
