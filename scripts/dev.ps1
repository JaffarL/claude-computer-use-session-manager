[CmdletBinding()]
param(
    [switch]$NoBuild,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 docker 命令。请先安装并启动 Docker Desktop。"
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine 当前不可用。请确认 Docker Desktop 显示 Engine running。"
}

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "已从 .env.example 创建 .env。Fake Agent 无需 API Key；真实 Claude 测试前再填写密钥。" -ForegroundColor Yellow
}

$ComposeArguments = @("compose", "up", "-d")
if (-not $NoBuild) {
    $ComposeArguments += "--build"
}

& docker @ComposeArguments
if ($LASTEXITCODE -ne 0) {
    throw "docker compose 启动失败。请执行 docker compose logs api 查看原因。"
}

$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    try {
        $HealthResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 3
        if ($HealthResponse.StatusCode -eq 200) {
            Write-Host "服务已就绪：http://127.0.0.1:8000/" -ForegroundColor Green
            return
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $Deadline)

& docker compose ps
throw "等待服务就绪超时（$TimeoutSeconds 秒）。请执行 docker compose logs api postgres redis。"
