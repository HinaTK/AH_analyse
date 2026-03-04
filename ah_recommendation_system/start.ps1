$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "启动AH股每日推荐系统..." -ForegroundColor Cyan

# Prefer local venv if present
$Py = "python"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
	$Py = $VenvPy
}

& $Py --version | Out-Null

Push-Location (Join-Path $Root "backend")

Write-Host "[1/2] 启动后端服务（不安装依赖；直接运行）..." -ForegroundColor Cyan
Start-Process -FilePath $Py -ArgumentList @('.\main.py') -WorkingDirectory (Get-Location) -WindowStyle Normal

Start-Sleep -Seconds 3

Write-Host "[2/2] 打开浏览器..." -ForegroundColor Cyan
Start-Process "http://localhost:8000"

Write-Host "系统已启动!" -ForegroundColor Green
Write-Host "API文档: http://localhost:8000/docs"
Write-Host "Web界面: http://localhost:8000"

Pop-Location
