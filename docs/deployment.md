# 部署说明

## 本地发布候选启动

```powershell
Copy-Item .env.example .env
docker compose -f compose.yaml -f compose.production.yaml config
docker compose -f compose.yaml -f compose.production.yaml up -d --build
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

生产 override 包含：

- API 只绑定主机 `127.0.0.1`，由反向代理对外提供入口；
- API 根文件系统只读，仅 `/tmp` 使用限额 tmpfs；
- API `cap_drop=ALL`、`no-new-privileges`；
- API、PostgreSQL、Redis 使用重启策略与优雅停止时间；
- Docker `json-file` 日志限制为 10 MiB × 3；
- PostgreSQL 和 Redis 不映射主机端口。

可用 `API_PORT` 修改本机入口：

```powershell
$env:API_PORT = "18000"
$env:RUNTIME_NAMESPACE = "computer-use-release"
docker compose -f compose.yaml -f compose.production.yaml up -d
```

## 远程主机最低拓扑

```text
Internet
  -> HTTPS 443 reverse proxy / load balancer
      -> FastAPI HTTP + SSE
      -> authenticated noVNC WebSocket proxy
  -> private PostgreSQL
  -> private Redis
  -> isolated runtime-manager / Docker or Kubernetes workers
```

公网只暴露 443。数据库、Redis、Docker socket、VNC 5900 和随机 noVNC 高端口都不应直接暴露。

## 当前模板不能直接解决的远程 noVNC 问题

开发版为每个 sandbox 把 6080 映射到主机 loopback 随机端口，并返回 `127.0.0.1` URL。这只适用于浏览器和 Docker Engine 在同一台机器的演示。

远程部署必须增加同源代理，例如：

```text
https://agent.example.com/runtime/{session_id}/vnc.html
wss://agent.example.com/runtime/{session_id}/websockify
```

代理应在转发前验证用户身份、session 所有权和短期 token，再把流量转到对应 runtime。未实现这层代理前，不要开放随机高端口作为替代方案。

## 密钥

- `.env` 只用于本地；远程环境使用云 Secrets Manager、Docker secret 或编排平台 secret；
- API Key 只注入可信执行组件，不进入前端、数据库、截图或日志；
- 定期轮换密钥，并对模型调用设置额度和告警；
- 默认 `AGENT_PROVIDER=fake`，不会消费 Anthropic Key；仅在显式设置为 `anthropic` 后发起模型请求。

## 数据与备份

- PostgreSQL 是会话、run、消息和事件的事实来源，应做定期备份和恢复演练；
- Redis AOF 只提高实时协调恢复能力，不能替代 PostgreSQL 备份；
- Alembic migration 应在发布前单独执行或由单实例 release job 执行，避免多个 API 副本同时迁移。

## 水平扩展注意事项

REST 与 SSE 控制面本身不依赖进程内业务状态，可以增加副本。同一部署的副本应共享一个 `RUNTIME_NAMESPACE` 和数据库；不同部署共享 Docker Engine 时必须使用不同 namespace。但生产化前仍需把 Docker 调度与 per-session 锁移到独立 runtime-manager，并使用数据库 advisory lock、Redis lock 或队列保证跨实例创建幂等。

## 上线检查

1. TLS/WSS 和认证完成；
2. PostgreSQL、Redis、runtime 网络不暴露公网；
3. Docker socket 不挂载到公网 API；
4. sandbox 出站网络使用 allowlist，并阻断云元数据和内网；
5. 设置 session TTL、用户配额、速率限制与审计；
6. 固定镜像 digest，运行依赖和镜像扫描；
7. 验证备份恢复、滚动升级、优雅停止和回滚。
