# 真实 Anthropic Computer Use 手工验证

这套步骤会产生模型费用，只在完成自动化测试并确认额度后执行。不要在 sandbox 中登录个人账号，也不要输入邮箱、支付、生产系统或其他敏感凭据。

## 1. 确认无费用前置检查

```powershell
Set-Location E:\ai_learning\look_for_job\kunxuan
.\scripts\test.ps1
.\scripts\security-check.ps1
docker compose ps
```

预期：测试全部通过，API/PostgreSQL/Redis 均为 healthy。

## 2. 在本地 `.env` 启用真实模式

只修改被 Git 忽略的 `.env`，不要把真实 Key 写进受跟踪文件：

```text
AGENT_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_MAX_TOKENS=1024
ANTHROPIC_MAX_ITERATIONS=12
```

`ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL` 可以继续使用 Windows 用户环境变量。启动 Compose 的 PowerShell 必须能读取这些变量。

## 3. 重建并检查模式

```powershell
docker compose up -d --build --force-recreate api
docker compose ps
docker compose exec -T api python -c "from app.core.config import Settings; s=Settings(); print(s.agent_provider, s.anthropic_model, bool(s.anthropic_api_key))"
```

预期最后一行类似：

```text
anthropic claude-sonnet-4-6 True
```

该命令只输出凭据是否存在，不显示 Key。

## 4. 浏览器端到端任务

1. 打开 <http://127.0.0.1:8000/>；
2. 新建会话“真实 Anthropic 验证”；
3. 等待状态变为 `READY`，确认 noVNC 桌面可见；
4. 提交任务：

```text
请打开 Firefox，访问 https://example.com，确认页面标题，然后告诉我标题。不要登录任何网站，也不要下载文件。
```

5. 同时观察 noVNC、聊天区和 SSE 时间线。

通过标准：

- noVNC 中能看到 Firefox 被真实打开并导航到 `example.com`；
- 事件依次包含 `run.started`、`tool.started`、`tool.result`、`screenshot.available`、`assistant.message` 和 `run.completed`；
- 最终回复能够说明页面标题；
- run 完成后会话回到 `READY`；
- 刷新页面后消息与事件仍然存在。

## 5. 隔离与停止

1. 再创建会话 B，确认 A/B 的桌面和历史互不串联；
2. 在一个长任务执行中点击“停止”，确认 run 变为 `CANCELLED`，sandbox 停止；
3. 确认另一个会话仍可正常使用。

## 6. 测试后切回零费用模式

把 `.env` 改回：

```text
AGENT_PROVIDER=fake
```

然后执行：

```powershell
docker compose up -d --force-recreate api
```

不要使用 `cleanup.ps1 -RemoveVolumes`，除非明确希望永久删除全部本地会话、消息和事件。
