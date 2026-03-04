@echo off
REM AH股推荐系统启动脚本 (Windows)
REM ====================================

setlocal enableextensions
set "ROOT=%~dp0"

REM 可选：--no-pause 用于脚本化运行
set "NO_PAUSE="
if /i "%~1"=="--no-pause" set "NO_PAUSE=1"

echo 启动AH股每日推荐系统...

set "PYTHONUTF8=1"

REM 1. 检查Python
set "PY=python"
if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"

"%PY%" --version >nul 2>&1
if errorlevel 1 (
	echo 错误: 未找到Python，请先安装Python 3.10+
	if not defined NO_PAUSE pause
	exit /b 1
)

REM 2. 启动服务（不安装依赖；直接运行）
echo [1/2] 启动后端服务...
cd /d "%ROOT%backend"
start "AH股推荐系统" "%PY%" main.py

REM 4. 等待启动
timeout /t 3 /nobreak >nul

REM 3. 打开浏览器
echo [2/2] 打开浏览器...
start http://localhost:8000

echo.
echo 系统已启动!
echo API文档: http://localhost:8000/docs
echo Web界面: http://localhost:8000
if not defined NO_PAUSE pause

endlocal
