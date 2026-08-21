# 安全边界与部署说明

## 当前原型已经做的保护

- 一会话一容器，桌面、浏览器 profile 和文件系统互相隔离；
- sandbox 使用非 root 用户运行，并设置 `cap_drop=ALL`、`no-new-privileges`、CPU、内存、PID 和共享内存限制；
- `5900/tcp` 不映射到主机，noVNC 的 `6080/tcp` 默认只绑定 `127.0.0.1` 随机端口；
- 每个容器使用不同的 VNC 签名密钥，访问 token 默认 120 秒过期；
- RuntimeProvider 只查询和清理由项目 managed label 标记的容器；
- API Key 仅从环境变量读取，不写入数据库、前端、截图或 Git。

## 必须诚实披露的边界

当前实现面向受信任的本地开发和演示环境。面向不可信多租户场景时，需要增加更强的隔离与访问控制。容器隔离与虚拟机隔离的安全边界不同；浏览器内容可能包含 prompt injection；Firefox 和系统软件仍需持续更新。不要在演示桌面登录个人账号，也不要给 agent 访问支付、邮箱、代码签名或生产凭据。

API 容器在本地开发中挂载了 `/var/run/docker.sock`。能访问 Docker socket 的进程实质上拥有很高的主机控制能力，因此控制面本身必须被视为可信组件。Docker Desktop 当前 socket 的组是 GID 0，所以 Compose 为 API 增加了该附加组；这只是 Windows Docker Desktop 本地开发适配，不应原样作为生产权限设计。

当前 noVNC 地址通过主机 loopback 随机端口提供，满足本机演示和自动化验证。远程浏览器不能使用返回 URL 中的 `localhost`；生产部署应由同源 HTTPS 入口代理静态 noVNC 页面与 WebSocket，不能把一组随机高端口直接暴露到公网。

## 生产化前还需要补齐

1. 把 Docker 调度拆成独立、最小权限的 runtime-manager，或迁移到 Kubernetes API 与专用 ServiceAccount；
2. 对外只暴露 TLS 443，使用认证后的同源 WebSocket 代理，不直接挂载 Docker socket 到公网 API；
3. 增加用户认证、session 所有权校验、审计、速率限制和并发配额；
4. 默认关闭或 allowlist sandbox 出站网络，并隔离云元数据地址和内网；
5. 使用 secrets manager 注入 API Key，设置自动轮换和日志脱敏；
6. 使用更强的隔离层（例如 gVisor、Kata Containers 或独立虚拟机）承载不可信任务；
7. 固定并持续扫描基础镜像和 Python 依赖，建立补丁与回滚流程。

## 参考资料

- [Docker Engine security](https://docs.docker.com/engine/security/)
- [Docker SDK for Python：Containers](https://docker-py.readthedocs.io/en/stable/containers.html)
- [websockify token plugins](https://github.com/novnc/websockify)
