[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [string]$RuntimeNamespace = "computer-use-session-manager",
    [switch]$RemoveVolumes,
    [switch]$RemoveImages
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$ManagedContainers = @(& docker ps -a `
    --filter "label=com.jaffar.computer-use.managed=true" `
    --filter "label=com.jaffar.computer-use.namespace=$RuntimeNamespace" `
    --format "{{.ID}}")
$ManagedContainers = @($ManagedContainers | Where-Object { $_ })
if ($ManagedContainers.Count -gt 0 -and $PSCmdlet.ShouldProcess("$($ManagedContainers.Count) 个项目 sandbox 容器", "强制删除")) {
    & docker rm --force @ManagedContainers | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "sandbox 容器清理失败。" }
}

$DownArguments = @("compose", "down", "--remove-orphans")
if ($RemoveVolumes) {
    $DownArguments += "--volumes"
}
if ($PSCmdlet.ShouldProcess("computer-use-session-manager Compose 项目", "停止并清理")) {
    & docker @DownArguments
    if ($LASTEXITCODE -ne 0) { throw "Compose 清理失败。" }
}

if ($RemoveImages -and $PSCmdlet.ShouldProcess("项目本地镜像", "删除")) {
    $ProjectImages = @("computer-use-session-manager-api:latest", "computer-use-sandbox:local")
    foreach ($Image in $ProjectImages) {
        & docker image inspect $Image *> $null
        if ($LASTEXITCODE -eq 0) {
            & docker image rm $Image | Out-Null
        }
    }
}

Write-Host "清理完成。RemoveVolumes=$RemoveVolumes，RemoveImages=$RemoveImages" -ForegroundColor Green
