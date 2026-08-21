# 故障排查

## Docker Desktop 显示 Engine stopped

以管理员身份打开 PowerShell：开始菜单搜索“PowerShell” → 右键 →“以管理员身份运行”。检查：

```powershell
wsl --status
wsl --version
wsl --list --verbose
docker info
```

确认 Docker Desktop 设置中启用了 WSL2 backend。更新 WSL 后可执行：

```powershell
wsl --update
wsl --shutdown
```

随后重新打开 Docker Desktop。不要删除 `docker-desktop-data` 分发版，否则可能丢失本地镜像和卷。

## 镜像下载不动

先判断是正在解压还是网络失败：

```powershell
docker pull python:3.11-slim
docker pull python:3.11-slim-bookworm
docker pull postgres:16-alpine
docker pull redis:7.4-alpine
docker system df
```

如果 GitHub noVNC 下载失败，可在浏览器手动下载 `v1.5.0.tar.gz` 用于诊断；正式构建仍应保留 Dockerfile 中固定版本和校验流程。不要随意改成 `latest`。

## `gh auth login` 设备页面不可用

这通常是 GitHub device flow 网络链路不可达，不代表浏览器普通登录失效。可以先在 GitHub 网页手动创建仓库、分支和 PR；Git 提交与本地开发不依赖 GitHub CLI。网络恢复后再执行：

```powershell
gh auth login --web --git-protocol https
```

## 8000 端口占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
docker compose ps
```

结束明确属于本项目的旧容器，或使用生产 override 的 `API_PORT`：

```powershell
$env:API_PORT = "18000"
docker compose -f compose.yaml -f compose.production.yaml up -d
```

## Readiness 返回 503

```powershell
docker compose ps
docker compose logs --tail 200 api postgres redis
Invoke-RestMethod http://127.0.0.1:8000/health/live
```

- live 正常、ready 失败：检查 PostgreSQL、Redis 或 Docker Engine；
- API 重启循环：检查 migration、环境变量和 Docker socket 权限；
- Windows Docker Desktop 下 socket 组通常需要 Compose 中的 `group_add: "0"`。

## noVNC 页面空白或连接 1006

1. session 必须是 `READY` 或 `RUNNING`；
2. URL 默认仅 120 秒有效，点击页面桌面区域的刷新按钮重新签发；
3. 使用 `127.0.0.1`，不要在部分嵌入式浏览器中改成 `localhost`；
4. 查看 sandbox 的 `/tmp/websockify.log`；
5. noVNC 1.5.0 的 token 必须位于 `path=websockify?token=...`，不能只放顶层查询参数。

不要把完整 noVNC URL 粘贴到 issue 或日志，它包含短期 JWT。

## 会话卡在 STOPPING 或 runtime 异常退出

```powershell
docker compose restart api
docker compose logs --tail 200 api
docker ps -a --filter "label=ccu.managed=true"
```

API 启动和周期 reconciler 会恢复 runtime 绑定，并收敛 STOPPING、过期和孤儿容器。如果仍异常，保存日志后执行项目清理脚本。

## 完全重建本地数据

以下命令会永久删除项目 PostgreSQL 和 Redis 数据：

```powershell
.\scripts\cleanup.ps1 -RemoveVolumes -Confirm:$false
.\scripts\dev.ps1
```

验证材料位于 Git 跟踪的 `docs/acceptance`，不会随 Docker 卷删除。

## PowerShell 中文输出乱码

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

仓库文本统一使用 UTF-8；不要为了修复终端显示而批量改写文件编码。
