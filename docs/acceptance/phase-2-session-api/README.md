# 第二阶段验收归档：会话和历史 API

## 验收信息

- 验收时间：2026-08-18 08:38–08:45（Asia/Shanghai）
- 验收分支：`feat/session-api-persistence`
- 分支终点：`c20776f`
- 用户结论：通过
- 环境：Windows 11、PowerShell、Docker Desktop、FastAPI、PostgreSQL、Redis

## 验收目标

1. 创建、查询、列表、停止和删除会话均符合 API 契约。
2. run 和 message 会落入数据库，查询顺序稳定。
3. 相同会话使用相同 `Idempotency-Key` 时只生成一个 run。
4. 同一会话已有活跃 run 时，再提交新 run 返回 `409 Conflict`。
5. `stop` 可以重复调用，且不会产生额外状态变化。
6. API 容器重启后，历史消息仍可查询。
7. PostgreSQL 和 Redis readiness 均正常。

## 当时的验收步骤

### 1. 检查服务与接口文档

1. 执行 `docker compose ps`，确认 API、PostgreSQL、Redis 为 healthy。
2. 打开 `http://localhost:8000/docs`，确认会话、run、message、stop、delete 等接口已注册。
3. 打开 `/health/live` 和 `/health/ready`，确认均返回成功。

对应素材：`01-swagger-docs.png`、`02-health-live.png`、`03-health-ready.png`。

### 2. 创建会话

通过 Swagger 调用 `POST /api/v1/sessions`：

```json
{
  "title": "远程验收会话",
  "expires_in_seconds": 3600
}
```

确认返回 HTTP 201、状态为 `READY`，并获得会话 ID：

```text
fcc23bf2-4b33-49eb-9073-38e3d9c108f7
```

对应素材：`04-session-created.png`。

### 3. 创建任务并验证幂等

向下列接口连续提交两次相同幂等键：

```text
POST /api/v1/sessions/fcc23bf2-4b33-49eb-9073-38e3d9c108f7/runs
Idempotency-Key: remote-acceptance-001
```

请求内容：

```json
{"input":"打开示例网站"}
```

确认两次响应中的 run ID 相同：

```text
e154bd37-3296-453c-a1b5-5b2e97543616
```

第二次响应还必须包含：

```text
idempotency-replayed: true
```

对应素材：`05-run-created.png`、`06-idempotency-replayed.png`。

### 4. 查询持久化消息

调用：

```text
GET /api/v1/sessions/fcc23bf2-4b33-49eb-9073-38e3d9c108f7/messages
```

确认第一条记录为 `USER`，内容是“打开示例网站”，`sequence` 为 1。

对应素材：`07-message-history.png`。

### 5. 验证停止操作幂等

连续两次调用：

```text
POST /api/v1/sessions/fcc23bf2-4b33-49eb-9073-38e3d9c108f7/stop
```

确认两次都成功，会话状态为 `STOPPED`，第二次不会重复增加版本号；关联活跃 run 变为 `CANCELLED`。

对应素材：`08-stop-idempotent.png`。

### 6. 验证重启后的数据库持久化

1. 重启 API 容器，PostgreSQL 数据卷保持不变。
2. API 恢复 healthy 后，再次查询 `/messages`。
3. 确认同一条消息、会话 ID、run ID 和序号仍存在。

对应素材：`09-history-after-restart.png`。

## 我使用的验收方法和手段

- 自动化：使用 `pytest`、FastAPI ASGI 客户端、临时 SQLite 文件和真实 SQLAlchemy 仓储验证接口；SQLite 显式开启外键约束，避免测试绕过数据库关系。
- 依赖隔离：通过 `FakeRuntimeProvider` 验证控制面，不依赖真实桌面容器，也不会调用 Anthropic API。
- 真实环境：使用 Docker Compose 中的 PostgreSQL 和 Redis 检查 readiness、迁移和重启持久化。
- 可视化接口检查：在 Swagger UI 中实际执行请求，并保存返回码、响应体与响应头截图。
- 一致性检查：使用相同幂等键连续请求，核对 run ID 和 `Idempotency-Replayed` 响应头。
- 状态机检查：覆盖 `READY → RUNNING → STOPPED`、run 取消、重复停止和活跃任务冲突。
- Git 检查：确认第二阶段由 4 个可解释的独立提交组成，并已推送远程分支。

## 验收结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| API、PostgreSQL、Redis 健康 | 通过 | 02、03 截图 |
| 创建会话 | 通过 | HTTP 201，04 截图 |
| 创建 run | 通过 | HTTP 202，05 截图 |
| 幂等重放 | 通过 | 相同 run ID 与响应头，06 截图 |
| 消息持久化 | 通过 | 07 截图 |
| 停止幂等 | 通过 | 08 截图 |
| API 重启后历史仍在 | 通过 | 09 截图 |
| 自动化测试 | 通过 | 当时完整后端测试为 10 passed |

结论：第二阶段通过，可以作为后续 Agent/SSE 阶段的稳定基线。

## Git 记录

```text
7088d58 feat(db): persist runs and chat messages
ba58f3e feat(api): add session lifecycle and history endpoints
ae67a61 test(api): cover persistence conflicts and idempotency
c20776f fix(db): flush run before dependent message
```

- 远程分支：`origin/feat/session-api-persistence`
- 手动创建 PR：<https://github.com/JaffarL/claude-computer-use-session-manager/pull/new/feat/session-api-persistence>

## 素材目录

原始截图位于 [materials/screenshots](./materials/screenshots/)，文件名按验收顺序编号。截图是从原本仅保存在本机、被 Git 排除的 `artifacts/acceptance/` 原样复制而来；本目录内的副本作为长期归档。
