# 第六阶段验证记录：发布候选质量与文档

## 验证信息

- 验证时间：2026-08-18 11:18–11:48（Asia/Shanghai）
- 分支：`docs/release-candidate`
- 功能提交：`d3547c9`、`9e9164a`、`282b858`
- 结果：通过
- 环境：Windows 11、Windows PowerShell、Docker Desktop/WSL2

## 本阶段交付

1. 用项目专用中文 README 替换上游导向 README，补齐架构、启动、测试、配置、API、生产模板、安全和已知边界；
2. 新增 `dev.ps1`、`test.ps1`、`smoke.ps1`、`cleanup.ps1` 和 `security-check.ps1`；
3. 新增生产 Compose override：loopback 端口、只读 API 根文件系统、tmpfs、capability 限制、日志轮转、自动重启和优雅停止；
4. 新增 API 示例、并发证据、部署和故障排查文档；
5. CI 增加依赖一致性、JavaScript、开发/生产 Compose 和密钥/大文件检查；
6. Runtime 增加命名空间，允许同一 Docker Engine 上的不同控制面互不清理对方 sandbox；
7. 完成无缓存构建、独立空数据卷启动、生产约束检查、双控制面并发冒烟、优雅停止和全量安全检查。

## 空环境复现

使用独立项目名、端口和 runtime namespace：

```powershell
$env:API_PORT = "18000"
$env:RUNTIME_NAMESPACE = "ccu-release-clean"
docker compose -p ccu-release-clean `
  -f compose.yaml -f compose.production.yaml build --no-cache
docker compose -p ccu-release-clean `
  -f compose.yaml -f compose.production.yaml up -d
```

结果：

- API 镜像从空构建层安装全部固定 Python 依赖；
- sandbox 重新下载约 201 MB Debian 包、Firefox/X11 依赖和 noVNC 1.5.0，构建成功；
- 新 PostgreSQL/Redis 卷从零执行三条 Alembic migration；
- `http://127.0.0.1:18000/health/ready` 返回 200；
- API 根文件系统 `ReadonlyRootfs=True`；
- `CapDrop=ALL`、`no-new-privileges=true`；
- restart policy 为 `unless-stopped`；
- json-file 日志轮转为 `10m × 3`。

## 双控制面并发冒烟

最初两套控制面会把对方 sandbox 视为孤儿。修复后，8000 使用默认 namespace，18000 使用 `ccu-release-clean`，同时执行 `smoke.ps1`：

| 环境 | Session | Runtime | Run | 结果 |
| --- | --- | --- | --- | --- |
| 8000 | `18a18b59…` | `619f9aea…` | `9c9f6488…` | COMPLETED、2 messages、8 events |
| 18000 | `1f1dd7f0…` | `8b8e7484…` | `7cae055e…` | COMPLETED、2 messages、8 events |

两套任务并发通过，双方 reconciler 没有交叉删除容器。冒烟脚本均自动 stop/delete，不输出 VNC JWT 或 API Key。

## 临时环境清理

验证后仅删除 `ccu-release-clean` 的容器、网络、`postgres-data`/`redis-data` 两个临时卷和临时 API 镜像。该临时数据只含自动冒烟记录；当前 8000 环境和正式项目卷保留且 readiness=200。

清理后：

```text
TEMP_VOLUMES_AFTER=0
TEMP_CONTAINERS_AFTER=0
CURRENT_READY=200
```

## 自动化与安全结果

```text
PowerShell parser       5 scripts passed
Ruff format             57 files already formatted
Ruff check              passed
pytest                  23 passed in 2.56s
pip check               no broken requirements
node --check            passed
development Compose     passed
production Compose      passed
Markdown local links    16 files passed
Git diff whitespace     passed
security check          工作树与全部 Git 历史通过
API graceful stop       1.423 seconds
API restart readiness   passed
```

安全脚本检查当前受跟踪文件和全部 Git patch 历史中的常见 Anthropic/GitHub/AWS Key、私钥、错误提交的 `.env`，并检查当前文件和历史 blob 是否超过 5 MiB。

## 验证方法

- 从空构建层安装依赖并验证 README 启动步骤；
- 独立 Compose 项目验证：使用新数据库卷执行 migration 和启动；
- HostConfig 实值核对：直接读取只读根文件系统、capabilities、security opt、restart 和日志配置；
- 双控制面对抗测试：两套 API 同时创建 sandbox，主动暴露全局 label 冲突；
- 命名空间回归：新增单元测试和真实双环境并发冒烟；
- PowerShell 5.1 实机测试：发现中文 JSON charset 误判，改用 readiness HTTP 状态；
- 破坏性清理限定：清理前核对临时卷名称前缀，清理后确认数量为 0；
- Git 历史安全扫描覆盖当前工作树、历史内容和历史大对象；
- 优雅关闭：真实停止 API 并计时，再启动并核对 readiness。

## 复验命令

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\dev.ps1
.\scripts\test.ps1
.\scripts\security-check.ps1
.\scripts\smoke.ps1
```

生产配置：

```powershell
docker compose -f compose.yaml -f compose.production.yaml config
```

## 素材目录

- [01-无缓存构建与生产约束.txt](./materials/01-无缓存构建与生产约束.txt)
- [02-双命名空间冒烟.txt](./materials/02-双命名空间冒烟.txt)
- [03-质量安全与清理.txt](./materials/03-质量安全与清理.txt)
