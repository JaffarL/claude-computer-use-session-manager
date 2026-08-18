[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Patterns = @(
    @{ Name = "Anthropic API Key"; Regex = "sk-ant-[A-Za-z0-9_-]{20,}" },
    @{ Name = "GitHub classic token"; Regex = "ghp_[A-Za-z0-9]{30,}" },
    @{ Name = "GitHub fine-grained token"; Regex = "github_pat_[A-Za-z0-9_]{30,}" },
    @{ Name = "AWS access key"; Regex = "AKIA[0-9A-Z]{16}" },
    @{ Name = "Private key"; Regex = "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----" }
)

$TrackedFiles = @(& git -c core.quotepath=false ls-files)
if ($LASTEXITCODE -ne 0) { throw "无法读取 Git 跟踪文件。" }

$Findings = [System.Collections.Generic.List[string]]::new()
foreach ($RelativePath in $TrackedFiles) {
    $FullPath = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) { continue }

    $FileInfo = Get-Item -LiteralPath $FullPath
    if ($FileInfo.Length -gt 5MB) {
        $Findings.Add("超大文件：$RelativePath ($([math]::Round($FileInfo.Length / 1MB, 2)) MiB)")
    }

    if ($FileInfo.Extension -in @(".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf")) { continue }
    $Content = Get-Content -LiteralPath $FullPath -Raw -ErrorAction SilentlyContinue
    foreach ($Pattern in $Patterns) {
        if ($Content -match $Pattern.Regex) {
            $Findings.Add("疑似 $($Pattern.Name)：$RelativePath")
        }
    }
}

$TrackedEnvironmentFiles = @($TrackedFiles | Where-Object { $_ -match "(^|/)\.env($|\.)" -and $_ -notmatch "\.example$" })
foreach ($EnvironmentFile in $TrackedEnvironmentFiles) {
    $Findings.Add("不应提交的环境文件：$EnvironmentFile")
}

$History = (& git log --all --format= --patch --no-ext-diff) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "无法读取 Git 历史。" }
foreach ($Pattern in $Patterns) {
    if ($History -match $Pattern.Regex) {
        $Findings.Add("Git 历史中疑似存在 $($Pattern.Name)")
    }
}

$ObjectLines = @(& git rev-list --objects --all)
$ObjectDetails = @($ObjectLines | & git cat-file --batch-check="%(objecttype) %(objectname) %(objectsize) %(rest)")
foreach ($ObjectDetail in $ObjectDetails) {
    if ($ObjectDetail -match "^blob\s+[0-9a-f]+\s+(\d+)\s+(.+)$") {
        $ObjectSize = [long]$Matches[1]
        $ObjectPath = $Matches[2]
        if ($ObjectSize -gt 5MB) {
            $Findings.Add("Git 历史超大对象：$ObjectPath ($([math]::Round($ObjectSize / 1MB, 2)) MiB)")
        }
    }
}

if ($Findings.Count -gt 0) {
    $Findings | ForEach-Object { Write-Error $_ }
    throw "安全检查发现 $($Findings.Count) 个问题。"
}

Write-Host "安全检查通过：工作树与 Git 历史未发现常见密钥、私钥、受跟踪 .env 或超过 5 MiB 的文件。" -ForegroundColor Green
