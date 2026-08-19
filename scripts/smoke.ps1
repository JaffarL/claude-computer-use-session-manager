[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Task = "执行发布候选版本冒烟测试",
    [ValidateRange(10, 180)]
    [int]$TimeoutSeconds = 60,
    [switch]$KeepSession
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")
$Session = $null

try {
    $HealthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health/ready" -TimeoutSec 5
    if ($HealthResponse.StatusCode -ne 200) {
        throw "服务未就绪。"
    }

    $SessionBody = @{ title = "PowerShell 冒烟测试"; expires_in_seconds = 600 } | ConvertTo-Json
    $Session = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/sessions" -ContentType "application/json" -Body $SessionBody

    $Vnc = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/vnc-access"
    if (-not $Vnc.expires_at) {
        throw "未获得 noVNC 到期时间。"
    }

    $IdempotencyKey = [guid]::NewGuid().ToString()
    $RunBody = @{ input = $Task } | ConvertTo-Json
    $Run = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/runs" -Headers @{ "Idempotency-Key" = $IdempotencyKey } -ContentType "application/json" -Body $RunBody

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 300
        $Runs = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/runs"
        $CurrentRun = $Runs.items | Where-Object { $_.id -eq $Run.id } | Select-Object -First 1
    } while ($CurrentRun.status -notin @("COMPLETED", "FAILED", "CANCELLED") -and (Get-Date) -lt $Deadline)

    if ($CurrentRun.status -ne "COMPLETED") {
        throw "任务未完成，最终状态：$($CurrentRun.status)"
    }

    $Messages = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/messages"
    $Events = Invoke-RestMethod -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/events/history?after_id=0&limit=1000"

    if ($Messages.items.Count -lt 2 -or $Events.items.Count -lt 2) {
        throw "持久化消息或事件数量不符合预期。"
    }

    [pscustomobject]@{
        session_id = $Session.id
        runtime_id = $Session.runtime_id
        run_id = $Run.id
        run_status = $CurrentRun.status
        message_count = $Messages.items.Count
        event_count = $Events.items.Count
        vnc_token_expires_at = $Vnc.expires_at
    } | Format-List

    Write-Host "冒烟测试通过。输出未包含 noVNC JWT 或 API Key。" -ForegroundColor Green
}
finally {
    if ($Session -and -not $KeepSession) {
        try {
            Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/sessions/$($Session.id)/stop" | Out-Null
            Invoke-WebRequest -UseBasicParsing -Method Delete -Uri "$BaseUrl/api/v1/sessions/$($Session.id)" | Out-Null
            Write-Host "已清理冒烟测试会话及其 sandbox。"
        }
        catch {
            Write-Warning "自动清理失败，请运行 .\scripts\cleanup.ps1 检查残留：$($_.Exception.Message)"
        }
    }
}
