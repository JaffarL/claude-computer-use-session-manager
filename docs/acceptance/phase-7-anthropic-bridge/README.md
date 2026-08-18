# 第七阶段验收归档：真实 Anthropic 工具桥

## 验收信息

- 验收时间：2026-08-18 22:20–22:41（Asia/Shanghai）
- 验收分支：`docs/release-candidate`
- 验收人：Codex
- 当前结论：无费用实现验收通过；真实模型计费端到端验收等待用户明确确认

## 本阶段目标

1. 保留 Fake Agent 作为零费用默认路径；
2. 增加可选的真实 Anthropic Computer Use runner；
3. 把模型的 `computer`、`bash` 调用严格绑定到当前 session 的 Docker runtime；
4. 支持用户环境中的 `ANTHROPIC_AUTH_TOKEN`、兼容 Base URL 和明确模型 ID；
5. 在不产生模型费用的前提下验证 SDK 请求、事件转换、Docker exec、截图和配置选择；
6. 把第一次真实计费测试设计为必须显式开启的人工验收。

## 实际实现

- `AGENT_PROVIDER=fake|anthropic` 控制执行模式，默认 `fake`；
- `AnthropicAgentRunner` 使用异步 SDK 执行 `computer_20251124` 工具循环；
- 模型请求只在 API 容器内进行，Key 不进入 sandbox；
- `runtime_id` 从当前 run 对应的数据库 session 获取，远程工具只对该容器执行；
- computer 工具支持截图、鼠标、键盘、点击、拖动、滚动、等待、按键保持和 zoom；
- bash 工具使用 argv 安全的 Docker exec，在非 root sandbox 用户下执行并设置超时；
- 工具结果和截图信号通过原有持久化事件队列进入 PostgreSQL、Redis 和 SSE；
- 单任务设置最大 token 和工具循环轮数，避免无限调用。

## 本次验收步骤

### 1. 自动化与静态检查

```powershell
.\scripts\test.ps1
.\scripts\security-check.ps1
```

结果：Ruff、依赖、JavaScript、Compose、安全扫描通过；`27 passed`。

### 2. Anthropic SDK 请求结构验证

使用真实 `anthropic==0.122.0` SDK 和 `httpx.MockTransport`，不访问外部 API：

- 请求地址：`/v1/messages?beta=true`；
- beta header：`computer-use-2025-11-24`；
- 工具：`computer_20251124`、`bash_20250124`；
- 模拟响应成功反序列化。

### 3. 主机到真实 sandbox 工具桥

创建一次性 session，并对其真实容器执行：

- 获取 PNG 截图：20,911 bytes；
- 移动鼠标到 `[100, 100]` 并再次截图；
- 裁剪 zoom 区域并得到 4,719 bytes PNG；
- 在 sandbox 内执行 `printf sandbox-ok`；
- 完成后删除该一次性 session 与 sandbox。

### 4. API 容器到真实 sandbox 工具桥

重建 API 镜像后，从实际 API 容器、实际 Docker socket 和实际非 root 运行环境执行截图：

```text
API_CONTAINER_TOOL_TEST=PASS png_bytes=21003
```

完成后删除一次性 session 与 sandbox。

### 5. 配置与回归冒烟

```text
REAL_RUNNER_SELECTION= AnthropicAgentRunner
anthropic_sdk= 0.122.0
readiness=200
冒烟测试通过
```

实际常驻 API 仍保持 `agent_provider=fake`，因此上述验收没有产生模型费用。

## 我使用的验收方法和手段

- 静态边界核对：确认 run 使用数据库中的 session `runtime_id`，不是前端或模型提供的容器 ID；
- 真实 Docker 黑盒测试：实际创建 sandbox，通过 Docker exec 捕获 Xvfb 屏幕并校验 PNG 文件头；
- 双位置验证：分别从 Windows 主机和最终 API 容器调用工具，排除只在开发主机可用的假阳性；
- SDK 协议验证：真实 SDK 配合内存 MockTransport，验证 URL、beta header、工具 schema 和响应解析；
- 事件顺序测试：伪造一轮 tool use 与最终文本，确认 tool started/result/screenshot/message 顺序；
- 失败与资源控制：坐标越界不执行命令，bash 有 120 秒硬超时，Agent 有最大循环轮数；
- 安全扫描：确认 Key 未进入 Git、日志、截图、数据库和 sandbox 环境。

## 验收结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Fake/Anthropic 模式选择 | 通过 | `REAL_RUNNER_SELECTION` |
| SDK Computer Use 请求格式 | 通过 | MockTransport 测试 |
| session → runtime 定向 | 通过 | runner 单元测试与真实 Docker 测试 |
| PNG 截图 | 通过 | 20,911 / 21,003 bytes |
| zoom 增强动作 | 通过 | 4,719 bytes PNG |
| 鼠标与 bash | 通过 | `REMOTE_TOOL_TEST=PASS` |
| API 容器 Docker 权限 | 通过 | `API_CONTAINER_TOOL_TEST=PASS` |
| 自动化质量 | 通过 | 27 tests、Ruff、Compose、pip check |
| 密钥安全 | 通过 | security-check |
| 真实计费模型任务 | 待确认 | 需要用户明确同意后执行 |

## 人工复验

真实模型测试步骤见 [Anthropic 手工验收](../../anthropic-manual-test.md)。执行前必须确认 API 额度、允许产生费用，并保证 sandbox 中没有个人账号或敏感信息。

## 原始材料

- [自动化与 SDK](./materials/01-自动化与SDK.txt)
- [真实 sandbox 工具桥](./materials/02-真实sandbox工具桥.txt)
- [容器配置与冒烟](./materials/03-容器配置与冒烟.txt)
