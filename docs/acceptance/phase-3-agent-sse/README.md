# 第三阶段验收归档：Agent 适配与 SSE

## 验收信息

- 验收与复验时间：2026-08-18 09:04–09:34（Asia/Shanghai）
- 验收分支：`feat/agent-sse-streaming`
- 分支终点：`55753fd`
- 验收人：Codex
- 验收结论：通过
- 环境：Windows 11、PowerShell、Docker Desktop、FastAPI、PostgreSQL、Redis

范围说明：本阶段已用确定性 Fake Agent 完成真实 Docker、PostgreSQL、Redis 和 SSE 端到端验收。由于没有在环境中配置有效 Anthropic Key，没有发起真实付费模型请求；该冒烟项需在最终交付前补做，但不影响本阶段事件架构和恢复机制的验收结论。

## 验收目标

1. Agent 与 Streamlit UI 解耦，通过统一事件接口输出。
2. 事件先写入 PostgreSQL，再通过 Redis 实时发布。
3. SSE 使用标准 `id`、`event`、`data` 字段。
4. 空闲 SSE 连接定期发送 heartbeat。
5. 客户端连接建立后能实时收到任务事件，而不是任务完成后轮询。
6. 使用 `Last-Event-ID` 重连时不漏发、不重复发送已确认事件。
7. 慢消费者使用有界队列，不能无限占用服务端内存。
8. Agent 失败会写入 `run.failed`，run 变为 `FAILED`，session 回到 `READY`。

## 当时的验收步骤

### 1. 静态检查和自动化测试

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m pytest backend\tests\test_event_stream.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

实际结果：Ruff 全部通过；SSE 专项 6 passed；完整后端 16 passed。

### 2. 重建真实 Docker 环境并执行迁移

```powershell
docker compose up -d --build api
docker compose exec -T api alembic current
docker compose ps
```

实际结果：数据库版本为 `20260818_0003 (head)`；API、PostgreSQL、Redis 全部 healthy。

### 3. 创建验收会话

调用 `POST /api/v1/sessions`，创建：

```text
session_id = 32a7c61f-f812-4c1c-aea1-01b4d11ac2d6
```

### 4. 在任务提交前建立 SSE 长连接

先执行：

```powershell
curl.exe --no-buffer --max-time 25 http://localhost:8000/api/v1/sessions/32a7c61f-f812-4c1c-aea1-01b4d11ac2d6/events?after_id=0
```

连接立即收到：

```text
retry: 2000
```

空闲约 15 秒后收到 `heartbeat`，证明连接未被错误关闭。

### 5. 保持 SSE 打开的同时提交 run

从另一个 PowerShell 请求提交任务：

```text
POST /api/v1/sessions/32a7c61f-f812-4c1c-aea1-01b4d11ac2d6/runs
Idempotency-Key: phase3-live-001
input: 请模拟打开浏览器并检查页面状态
```

生成：

```text
run_id = 68987f21-3652-472d-a5f5-5bf876232cf3
```

原先已打开的 SSE 连接实时收到 ID 1–8，顺序为：

```text
run.started
assistant.delta
assistant.delta
tool.started
tool.result
screenshot.available
assistant.message
run.completed
```

原始内容见 [01-真实SSE事件流.txt](./materials/01-真实SSE事件流.txt)。

### 6. 验证断线续传

使用请求头重连：

```powershell
curl.exe --silent --no-buffer --max-time 2 -H "Last-Event-ID: 3" http://localhost:8000/api/v1/sessions/32a7c61f-f812-4c1c-aea1-01b4d11ac2d6/events
```

实际仅补发 ID 4、5、6、7、8，没有重复 1–3，也没有漏掉后续事件。

### 7. 交叉核对最终持久状态

分别查询 runs、messages 和 events/history，实际得到：

```text
RunStatus: COMPLETED
MessageCount: 2
EventCount: 8
EventIds: 1,2,3,4,5,6,7,8
```

原始内容见 [02-断线续传与接口交叉核验.txt](./materials/02-断线续传与接口交叉核验.txt)。

## 我使用的验收方法和手段

- 确定性 Fake Agent：固定事件类型与顺序，测试不依赖网络、模型随机性或费用。
- 真实事件链路：API 和 worker 使用真实 PostgreSQL 与 Redis，不以单元测试替代 Docker 联调。
- 双终端实时性验证：一个终端先保持 SSE，另一个终端后提交 run，证明事件是运行期间送达。
- 数据库与 Redis 分工验证：事件写库后发布；Redis 负责低延迟扇出，数据库负责重连补发。
- 游标恢复验证：使用标准 `Last-Event-ID`，核对补发 ID 集合必须严格等于 4–8。
- 多接口交叉核验：SSE 事件、event history、run 状态和 message 数量必须相互一致。
- 故障测试：注入抛出 `RuntimeError` 的 Agent，确认 `run.started → run.failed`，且 session 回到 `READY`。
- 回调适配测试：模拟 Anthropic 文本、tool use、tool result 和 screenshot callback，确认转换顺序稳定且不引用 Streamlit。
- 慢消费者保护：每个 SSE 客户端队列设置上限，溢出时发送 `stream.reset` 并要求按最后事件 ID 恢复。
- 代码质量：执行 Ruff 格式检查、lint 和完整 pytest。
- 可视化尝试：曾尝试使用应用内浏览器生成本机页面截图，但浏览器对本地 URL 刷新触发安全限制，因此没有绕过；本阶段改用可复现命令和原始 SSE 文本作为主要证据。

## 验收结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 标准 SSE 字段 | 通过 | 事件包含 `id/event/data` |
| heartbeat | 通过 | 长连接空闲时收到 heartbeat |
| Redis 实时推送 | 通过 | 先连接、后提交任务仍实时收到 8 个事件 |
| PostgreSQL 持久化 | 通过 | history 返回相同 8 个事件 |
| Last-Event-ID 恢复 | 通过 | ID 3 之后只返回 4–8 |
| 最终运行状态 | 通过 | `COMPLETED` |
| 消息历史 | 通过 | 用户和助手共 2 条 |
| Agent 失败恢复 | 通过 | 自动化测试验证 `FAILED` 与 session `READY` |
| 慢客户端内存保护 | 通过 | 有界队列与 `stream.reset` 实现 |
| 代码质量 | 通过 | Ruff 通过，16 tests passed |
| 真实 Anthropic 请求 | 待补充 | 尚未配置有效 API Key，未产生费用 |

结论：第三阶段的代码、数据库事件日志、Redis 实时通道、SSE 恢复协议和失败处理全部通过验收。真实 Anthropic API 冒烟属于最终交付前的外部凭据检查项。

## 为什么这里使用 SSE

任务命令通过 REST 发起，浏览器主要接收服务端单向进度，因此 SSE 比再设计一套业务 WebSocket 更简单。浏览器原生支持自动重连，`Last-Event-ID` 可与数据库事件 ID 配合补发；VNC 桌面画面仍会使用它自身的 WebSocket，两种通道职责不同。

## Git 记录

```text
5bcbc89 feat(events): persist and publish session events
1814fcf feat(agent): stream resumable run progress over SSE
55753fd test(streaming): cover replay live events and failures
```

- 远程分支：`origin/feat/agent-sse-streaming`
- 手动创建 PR：<https://github.com/JaffarL/claude-computer-use-session-manager/pull/new/feat/agent-sse-streaming>

## 素材目录

- [01-真实SSE事件流.txt](./materials/01-真实SSE事件流.txt)：真实长连接收到的 heartbeat 与 8 个事件。
- [02-断线续传与接口交叉核验.txt](./materials/02-断线续传与接口交叉核验.txt)：`Last-Event-ID` 补发以及最终状态。
- [03-自动化测试Docker迁移Git.txt](./materials/03-自动化测试Docker迁移Git.txt)：复验时的质量、容器、迁移和提交信息。
