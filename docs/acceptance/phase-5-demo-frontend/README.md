# 第五阶段验收归档：基础演示前端

## 验收信息

- 验收时间：2026-08-18 10:58–11:09（Asia/Shanghai）
- 验收分支：`feat/demo-frontend`
- 功能提交：`4727bb9`、`bfd1844`
- 验收人：Codex
- 当前结论：Codex 自动验收通过，等待用户阶段确认
- 环境：Windows 11、PowerShell、Docker Desktop、Codex In-app Browser

## 本阶段交付

1. FastAPI 在 `/` 提供与 API 同源的原生 HTML/CSS/JS 单页控制台；
2. 页面支持会话列表、创建、选择、刷新、停止和删除入口；
3. 页面支持任务提交、持久化聊天历史、SSE 实时事件时间线与自动重连；
4. 页面内嵌每会话独立 noVNC 桌面，并显示短期令牌到期时间；
5. READY、RUNNING、STOPPED、EXPIRED 等状态联动按钮权限和空状态文案；
6. 采用响应式布局，在 1280、1024 和 700 CSS 像素宽度完成浏览器验收；
7. 新增同源静态资源测试，完整后端测试增至 22 项。

## 真实浏览器验收步骤

### 1. 同源页面与依赖健康

访问 `http://127.0.0.1:8000/`，确认页面、CSS 和 JavaScript 均返回 200；页面底部健康状态显示“服务与运行时正常”。

### 2. 从页面创建真实隔离会话

点击“新建隔离会话”，创建“第五阶段 UI 验收”。结果：

```text
session=5bc862e7-0df0-4138-ab3b-2941aa26b630
runtime=670e3aa6...
status=READY
noVNC host port=32773
```

页面自动选择新会话，SSE 显示已连接，noVNC iframe 显示该 Docker sandbox 的真实 Xterm 桌面。

### 3. 从页面提交任务并观察实时流

提交：

```text
通过前端提交任务并验证 SSE 实时更新
```

结果：页面收到数据库事件 ID 49–56，包括 `run.started`、两条 `assistant.delta`、`tool.started`、`tool.result`、`screenshot.available`、`assistant.message` 和 `run.completed`；同时出现 USER/AI 两条持久化消息。

[查看任务、SSE 与真实 noVNC 截图](./materials/screenshots/01-live-task-sse-vnc.png)

### 4. 刷新恢复

浏览器整页重载后再次核对：当前会话、两条消息、八条事件、SSE 连接和 noVNC 桌面均自动恢复，没有依赖浏览器内存保存业务状态。

### 5. 停止联动与容器回收

点击“停止”后核对：

- 会话状态变为 `STOPPED`；
- 输入框、运行任务、停止和桌面刷新按钮禁用；
- 当前 SSE 连接关闭，桌面 iframe 清空；
- 页面明确提示停止状态下不能提交任务；
- Docker 中 `ccu.managed=true` 的 sandbox 容器数量为 0。

[查看停止状态截图](./materials/screenshots/02-session-stopped.png)

### 6. 响应式布局

使用浏览器 viewport 能力分别检查 1024×720 和 700×900。1024 宽度切换为单列内容区，700 宽度将侧栏移到页面顶部，按钮、会话列表和内容仍可访问。

[查看 700×900 布局截图](./materials/screenshots/03-mobile-layout.png)

## 开发中发现并修复的问题

1. In-app Browser 对 `localhost` 的子资源访问出现空响应，开发模式 public host 改为明确的 `127.0.0.1`；
2. noVNC 1.5.0 不会把顶层 `token` 查询参数传给 WebSocket，导致 websockify 报 `Token not present`；现将 JWT 放入 noVNC 的 `path=websockify?token=...` 参数，真实桌面连接通过；
3. 停止无消息会话后空状态曾仍显示“桌面已经就绪”；现按 session 状态渲染，并在停止后立即刷新消息区域；
4. 停止动作完成后新增“SSE 已断开”反馈，避免把已关闭的连接显示为在线。

## 我使用的验收方法和手段

- 真实浏览器操作：用页面完成创建、提交、刷新和停止，不通过接口代替核心 UI 路径；
- 语义 DOM 快照：核对按钮状态、会话状态、消息、事件 ID、noVNC 内部连接文本和无障碍名称；
- 可视截图：在核心路径、停止状态和移动断点保存像素级证据；
- 持久化交叉核对：浏览器重载后核对 PostgreSQL 恢复的消息和事件；
- Docker 交叉核对：停止后直接按 managed label 查询容器，确认运行时已回收；
- 协议诊断：读取 noVNC 浏览器错误与 websockify 日志，定位 token 未进入 WebSocket path 的根因；
- 自动化检查：Ruff、pytest、Node 语法检查、Compose 配置检查和 Git whitespace 检查。

## 自动化验收结果

```text
ruff format --check backend   57 files already formatted
ruff check backend            All checks passed
pytest backend/tests -q       22 passed in 2.57s
node --check app.js           passed
docker compose config --quiet passed
git diff --check              passed
```

## 复验步骤

```powershell
docker compose up -d --build
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Start-Process http://127.0.0.1:8000/
```

网页复验顺序：新建隔离会话 → 输入任务 → 运行任务 → 查看 SSE 时间线和桌面 → 刷新页面核对历史 → 停止会话。

自动化复验：

```powershell
.\.venv\Scripts\ruff.exe format --check backend
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\pytest.exe backend\tests -q
node --check backend\app\static\app.js
docker compose config --quiet
git diff --check
```

## 当前边界

- 本阶段用确定性 Fake Agent 演示完整前端事件路径，未消耗 Anthropic API Key；
- noVNC URL 使用主机 loopback 随机端口，适合本机笔试演示，远程生产需同源 HTTPS/WSS 代理；
- 页面暂未实现登录、租户权限和审计 UI，这些属于生产化扩展；
- “删除”已有确认弹窗和后端测试；本次真实浏览器验收没有确认执行删除，避免无必要地销毁归档会话记录。

## 素材目录

- [01-真实浏览器主流程.txt](./materials/01-真实浏览器主流程.txt)
- [02-停止与响应式回归.txt](./materials/02-停止与响应式回归.txt)
- [03-自动化质量检查.txt](./materials/03-自动化质量检查.txt)
- [截图 SHA256](./materials/screenshots/SHA256SUMS.txt)
