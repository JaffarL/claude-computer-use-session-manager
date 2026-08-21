# 并发与隔离证据

本页汇总第四阶段的真实 Docker 验证数据；完整命令、截图和自动化输出见 [第四阶段记录](acceptance/phase-4-isolated-runtime/README.md)。

## 跨会话并行

两个独立 session 同时提交任务：

```text
A started_at=2026-08-18T02:32:59.379824Z
A finished_at=2026-08-18T02:32:59.665104Z
B started_at=2026-08-18T02:32:59.385505Z
B finished_at=2026-08-18T02:32:59.669177Z
overlap=279.599 ms
```

两条运行区间实际重叠，证明控制面没有使用全局互斥把所有 session 串行化。

## 同会话竞态

向同一 READY session 并发发送两次不同任务：

```text
response_statuses=[202, 409]
active_run_count=1
```

数据库状态转换与行锁保证只有一个 run 进入执行，另一个明确返回冲突，不会静默重复执行。

相同 `Idempotency-Key` 的重复请求走另一条语义：返回既有 run，并带 `Idempotency-Replayed: true`。

## Runtime 创建幂等

Fake Docker 单元测试对同一 session 并发调用 20 次 runtime create：

```text
provider_create_calls=20
docker_container_runs=1
unique_runtime_ids=1
```

进程内 session 锁负责单实例协调；Docker 稳定容器名和名称唯一性为多控制面实例竞争兜底。

## 桌面与令牌隔离

验证过程创建 A、B 两个 sandbox：

```text
A runtime=6e8b74c0a4c0... host_port=32769
B runtime=f5528b20e0f3... host_port=32770
```

- A、B token 各自连接时均收到 `RFB 003.008`；
- A token 用于 B 端口时在 WebSocket 建连阶段被拒绝；
- 两个容器内 Firefox 显示不同 session 标识和颜色；
- 停止 A 后，B 保持 READY/healthy；
- 删除两者后 managed sandbox 数量为 0。

截图：

- [Session A](acceptance/phase-4-isolated-runtime/materials/screenshots/01-session-a.png)
- [Session B](acceptance/phase-4-isolated-runtime/materials/screenshots/02-session-b.png)

## 恢复与收敛

API 重启前后同一 session 的 runtime ID 保持不变；启动 reconciler 通过 Docker label 恢复绑定，并清理过期、孤儿和重复容器。API 在 `STOPPING` 中断时，重启后会继续停止并收敛到 `STOPPED`。
