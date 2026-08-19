[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Ruff = Join-Path $ProjectRoot ".venv\Scripts\ruff.exe"
$Pytest = Join-Path $ProjectRoot ".venv\Scripts\pytest.exe"

foreach ($RequiredFile in @($Python, $Ruff, $Pytest)) {
    if (-not (Test-Path -LiteralPath $RequiredFile)) {
        throw "缺少 $RequiredFile。请先按 README 创建虚拟环境并安装 backend\requirements-dev.txt。"
    }
}

& $Ruff format --check backend
if ($LASTEXITCODE -ne 0) { throw "Ruff 格式检查失败。" }

& $Ruff check backend
if ($LASTEXITCODE -ne 0) { throw "Ruff 静态检查失败。" }

& $Pytest backend\tests -q
if ($LASTEXITCODE -ne 0) { throw "pytest 失败。" }

& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw "Python 依赖一致性检查失败。" }

if (Get-Command node -ErrorAction SilentlyContinue) {
    & node --check backend\app\static\app.js
    if ($LASTEXITCODE -ne 0) { throw "前端 JavaScript 语法检查失败。" }
}
else {
    Write-Warning "未安装 Node.js，跳过可选的 JavaScript 语法检查；项目运行不依赖 Node.js。"
}

& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose 配置检查失败。" }

& docker compose -f compose.yaml -f compose.production.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw "生产 Compose 配置检查失败。" }

Write-Host "全部质量检查通过。" -ForegroundColor Green
