# 第四阶段验收归档：隔离运行时与 noVNC

## 验收信息

- 验收时间：2026-08-18 10:20–10:39（Asia/Shanghai）
- 验收分支：`feat/isolated-runtime-vnc`
- 功能提交：`9dff315`、`0b7796a`、`6547cef`
- 验收人：Codex
- 验收结论：通过；用户已于 2026-08-18 确认
- 环境：Windows 11、PowerShell、Docker Desktop、FastAPI、PostgreSQL、Redis

## 验收目标

1. 构建不含 Streamlit 的独立 Linux 桌面镜像；
2. 每个逻辑 session 创建一个独立 Docker sandbox；
3. Xvfb、Openbox、Firefox、x11vnc、websockify/noVNC 均能实际启动；
4. noVNC WebSocket 使用短期 JWT，且 token 只能访问对应容器；
5. 容器应用 CPU、内存、PID、共享内存和权限限制；
6. 同一 session 的 20 个并发 runtime create 只生成一个容器；
7. 不同 session 的 run 可并行，同一 session 的双提交明确返回 202/409；
8. stop 幂等、delete 回收容器，停止 A 不影响 B；
9. API 重启后根据 label 恢复数据库与原容器的绑定；
10. 过期、孤儿、重复和停止中断的运行时能够由 reconciler 收敛。

## 实际验收步骤

### 1. 构建镜像

```powershell
docker compose build sandbox-image
docker image inspect computer-use-sandbox:local --format "{{.Id}} {{.Size}}"
```

结果：镜像 `computer-use-sandbox:local` 构建成功，实际展开大小 `343882616` bytes，约 344 MB。最初 Debian `novnc` 包会引入大量无关 OpenStack/Python 依赖，验收前已改为 pip 安装 websockify 并直接下载固定版本 noVNC 1.5.0。

### 2. 单容器协议与鉴权冒烟

启动临时 sandbox，等待健康检查后验证：

```text
HTTP=200 content_type=text/html
VALID_TOKEN=b'RFB 003.008\n'
INVALID_TOKEN=rejected (InvalidMessage)
```

这一步同时证明 noVNC 静态页可访问、有效 token 确实连到真实 RFB 服务、无效 token 在 WebSocket 建连阶段被拒绝。临时容器随后已删除。

### 3. Compose 正式集成

```powershell
docker compose up -d --build
Invoke-RestMethod http://localhost:8000/health/ready
```

结果：PostgreSQL、Redis、Docker readiness 均为“正常”，API 健康。

### 4. 两个独立 session 与 VNC 交叉验证

创建 A、B 两个 session 后得到两个容器和两个端口：

```text
A runtime=6e8b74c0a4c0... port=32769
B runtime=f5528b20e0f3... port=32770
```

两个 token 分别连接各自容器时均收到 `RFB 003.008`；把 A token 用在 B 端口时被拒绝。容器内分别打开不同颜色和 session 标识的 Firefox 页面并截图：

- [Session A 截图](./materials/screenshots/01-session-a.png)
- [Session B 截图](./materials/screenshots/02-session-b.png)

### 5. 资源与权限限制

两个容器的真实 Docker HostConfig 均为：

```text
memory=805306368
nano_cpus=1000000000
pids=256
cap_drop=["ALL"]
security=["no-new-privileges:true"]
```

### 6. 并发、竞态和生命周期

- 两个不同 session 同时提交任务：均返回 202；
- A 执行区间：`02:32:59.379824Z`–`02:32:59.665104Z`；
- B 执行区间：`02:32:59.385505Z`–`02:32:59.669177Z`；
- 实际重叠：`279.599 ms`；
- 同一 session 同时提交两次：一个 202、一个 409；
- A 连续 stop 两次：两次均返回 200/`STOPPED`；
- A 停止后其容器为 exited，B 仍为 `READY` 且 healthy；
- A、B delete 均返回 204，受管 sandbox 容器最终为 0。

### 7. API 重启恢复

重启 API 前：

```text
session=5032b453-0efd-4407-bd27-cfa91cf1a6c7
runtime=0ee99af516c49eb955682253118706d5f894be44b7600b97bb416df14fad745d
```

`docker compose restart api` 后重新查询，session 仍为 `READY`，runtime ID 完全相同，容器 healthy，证明没有丢失绑定或重复创建。

### 8. 自动化质量检查

```powershell
.\.venv\Scripts\ruff.exe format --check backend
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\pytest.exe backend\tests -q
git diff --check
```

结果：56 个文件格式正确、Ruff 通过、20 tests passed、diff whitespace 检查通过。

## 我使用的验收方法和手段

- Docker 真实联调：不仅 mock Docker SDK，还实际构建镜像、启动容器并读取 health、进程、端口和 HostConfig；
- 协议级 VNC 验证：用 WebSocket 客户端读取 RFB banner，不以“HTML 能打开”替代桌面可用性；
- 负向安全测试：分别测试无效 token 和跨容器 token，必须在建连阶段失败；
- 可视化隔离：在两个容器内让 Firefox 显示不同颜色和 ID，再由各自 X display 内部截图；
- 时间区间证明并发：比较两条 run 的 `started_at/finished_at`，计算交集而不是凭肉眼判断；
- 竞态测试：同时向同一个 session 发两个请求，核对只有一个 202，另一个稳定为 409；
- 恢复测试：重启真实 API 容器，交叉核对数据库 runtime ID、Docker label 和容器健康；
- 资源检查：直接读取 Docker HostConfig，确认限制确实传给 Engine；
- 回收检查：通过 API stop/delete 后查询 managed label 容器，确保没有遗留；
- 自动测试：Fake Docker 对 20 个并发 create、token 绑定、过期/孤儿清理和停止恢复做确定性覆盖。

## 验收结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 精简 sandbox 镜像 | 通过 | 344 MB，固定 noVNC 1.5.0 |
| 桌面进程健康 | 通过 | Xvfb/Openbox/Firefox/x11vnc/websockify |
| 一会话一容器 | 通过 | A/B 不同 runtime ID、端口和画面 |
| VNC 有效 token | 通过 | 收到 `RFB 003.008` |
| 无效/跨会话 token | 通过 | WebSocket 建连被拒绝 |
| 资源和权限限制 | 通过 | Docker HostConfig 实值 |
| 20 并发 create 幂等 | 通过 | 自动测试仅 `run_count == 1` |
| 跨会话并行 | 通过 | 279.599 ms 时间重叠 |
| 同会话竞态 | 通过 | 202 + 409 |
| stop/delete | 通过 | stop 幂等、delete 204、无残留容器 |
| 停止 A 不影响 B | 通过 | A exited，B READY/healthy |
| API 重启恢复 | 通过 | 重启前后 runtime ID 相同 |
| TTL/孤儿/停止恢复 | 通过 | reconciler 自动测试 |
| 代码质量 | 通过 | Ruff、20 tests、diff check |

## 当前边界

- 该阶段使用确定性 Fake Agent 验证 run 并发，尚未消耗真实 Anthropic API Key；
- 当前 noVNC URL 默认绑定主机 loopback 随机端口，适合本机演示；远程生产需补同源 HTTPS WebSocket 代理；
- API 挂载 Docker socket 是可信本地控制面方案，不是安全的多租户生产权限模型；
- 前端将在第五阶段实现，届时用户可直接在同一页面创建 session、查看 SSE 和嵌入 noVNC。

## 素材目录

- [01-镜像构建与环境.txt](./materials/01-镜像构建与环境.txt)
- [02-VNC与隔离鉴权.txt](./materials/02-VNC与隔离鉴权.txt)
- [03-并发生命周期与恢复.txt](./materials/03-并发生命周期与恢复.txt)
- [04-自动化质量检查.txt](./materials/04-自动化质量检查.txt)
- [截图 SHA256](./materials/screenshots/SHA256SUMS.txt)
