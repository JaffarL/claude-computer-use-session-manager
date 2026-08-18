# PowerShell API 示例

以下命令均在项目启动后执行，默认地址为 `http://127.0.0.1:8000`。

## 健康检查

```powershell
$baseUrl = "http://127.0.0.1:8000"
Invoke-RestMethod "$baseUrl/health/live"
Invoke-RestMethod "$baseUrl/health/ready"
```

## 创建与查询会话

```powershell
$createBody = @{
    title = "API 示例会话"
    expires_in_seconds = 1800
} | ConvertTo-Json

$sessionResult = Invoke-RestMethod `
    -Method Post `
    -Uri "$baseUrl/api/v1/sessions" `
    -ContentType "application/json" `
    -Body $createBody

$sessionId = $sessionResult.id
Invoke-RestMethod "$baseUrl/api/v1/sessions/$sessionId"
Invoke-RestMethod "$baseUrl/api/v1/sessions?offset=0&limit=20"
```

## 先打开 SSE，再提交任务

在第一个 PowerShell 窗口运行：

```powershell
curl.exe --no-buffer "$baseUrl/api/v1/sessions/$sessionId/events?after_id=0"
```

在第二个窗口运行：

```powershell
$runBody = @{ input = "演示 SSE、消息持久化和幂等提交" } | ConvertTo-Json
$idempotencyKey = [guid]::NewGuid().ToString()

$runResult = Invoke-RestMethod `
    -Method Post `
    -Uri "$baseUrl/api/v1/sessions/$sessionId/runs" `
    -Headers @{ "Idempotency-Key" = $idempotencyKey } `
    -ContentType "application/json" `
    -Body $runBody
```

再次使用完全相同的 `$idempotencyKey`，应返回同一个 run，响应头包含 `Idempotency-Replayed: true`。

## 事件断线补发

假设客户端最后确认的数据库事件 ID 是 3：

```powershell
curl.exe --no-buffer --max-time 3 `
    -H "Last-Event-ID: 3" `
    "$baseUrl/api/v1/sessions/$sessionId/events"
```

服务端只补发 ID 大于 3 的事件；heartbeat 不带业务 ID。

## 查询持久化结果

```powershell
Invoke-RestMethod "$baseUrl/api/v1/sessions/$sessionId/runs"
Invoke-RestMethod "$baseUrl/api/v1/sessions/$sessionId/messages"
Invoke-RestMethod "$baseUrl/api/v1/sessions/$sessionId/events/history?after_id=0&limit=1000"
```

## 签发 noVNC 地址

```powershell
$vncAccess = Invoke-RestMethod `
    -Method Post `
    -Uri "$baseUrl/api/v1/sessions/$sessionId/vnc-access"

$vncAccess.expires_at
Start-Process $vncAccess.url
```

URL 内含短期 JWT，不要把完整 URL 复制到日志、截图、PR 或聊天中。

## 停止和删除

```powershell
Invoke-RestMethod -Method Post "$baseUrl/api/v1/sessions/$sessionId/stop"

Invoke-WebRequest `
    -UseBasicParsing `
    -Method Delete `
    -Uri "$baseUrl/api/v1/sessions/$sessionId"
```

停止是幂等操作；删除会销毁 sandbox 并软删除数据库记录。

## 常见错误语义

| HTTP | 含义 |
| --- | --- |
| 404 | session 不存在或已经删除 |
| 409 | 当前状态不允许操作，例如同会话已有运行中的任务 |
| 422 | 请求字段或 UUID 格式不符合约束 |
| 503 | PostgreSQL、Redis、Docker 或 sandbox runtime 暂不可用 |
