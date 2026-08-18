# 第七阶段验收归档：真实 Anthropic 工具桥

## 验收信息

- 验收时间：2026-08-18 22:20–23:12（Asia/Shanghai）
- 验收分支：`docs/release-candidate`
- 验收人：Codex
- 当前结论：真实模型计费端到端验收通过

## 本阶段目标

1. 保留 Fake Agent 作为零费用默认路径；
2. 增加可选的真实 Anthropic Computer Use runner；
3. 把模型的 `computer`、`bash` 调用严格绑定到当前 session 的 Docker runtime；
4. 支持用户环境中的 `ANTHROPIC_AUTH_TOKEN`、兼容 Base URL 和明确模型 ID；
5. 在不产生模型费用的前提下验证 SDK 请求、事件转换、Docker exec、截图和配置选择；
6. 在用户明确授权后执行真实计费端到端验收，并保存可独立复核的事件、进程和画面证据。

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

上述步骤完成后，用户明确授权了真实计费测试。

### 6. 真实计费端到端验收

第一次调用发现兼容 Base URL 把原生 `tool_use` 转成了文本形式的工具标签。程序没有执行模型伪造的“工具结果”，验收按失败记录。随后增加受限兼容解析：只接受已注册的 `computer`、`bash` 工具，忽略模型声称的输出，结果必须来自当前 session 的 Docker sandbox。

修复后新建独立验收会话，并提交“打开 Firefox、访问 `https://example.com`、确认标题”的任务：

```text
session_id=b0940f13-51ce-4089-b57f-d161b3aaf56c
run_id=30c4443f-1511-4c5a-9056-492a31637f7b
run_status=COMPLETED
events=29
tool.started=9
tool.result=9
screenshot.available=7
firefox_process=305 firefox-esr https://example.com
final_title=Example Domain
```

沙箱原始截图显示 Firefox 地址栏为 `example.com`，窗口标题和页面主标题均为 `Example Domain`。截图见 [真实计费任务画面](./artifacts/real-paid-example-domain.png)。

重启后内置浏览器一度无法连接本机 `8000` 端口，因此本轮没有把前端界面复核冒充为通过；第五阶段已单独完成过界面层验收。本轮结论来自 API 持久化结果、事件流、Docker 进程和沙箱原始画面四类一致证据。

## 我使用的验收方法和手段

- 静态边界核对：确认 run 使用数据库中的 session `runtime_id`，不是前端或模型提供的容器 ID；
- 真实 Docker 黑盒测试：实际创建 sandbox，通过 Docker exec 捕获 Xvfb 屏幕并校验 PNG 文件头；
- 双位置验证：分别从 Windows 主机和最终 API 容器调用工具，排除只在开发主机可用的假阳性；
- SDK 协议验证：真实 SDK 配合内存 MockTransport，验证 URL、beta header、工具 schema 和响应解析；
- 事件顺序测试：伪造一轮 tool use 与最终文本，确认 tool started/result/screenshot/message 顺序；
- 失败与资源控制：坐标越界不执行命令，bash 有 120 秒硬超时，Agent 有最大循环轮数；
- 安全扫描：确认 Key 未进入 Git、日志、截图、数据库和 sandbox 环境。
- 反伪造核对：只有实际工具执行产生的事件和画面才算证据，模型文字不能单独作为通过依据。

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
| 自动化质量 | 通过 | 28 tests、Ruff、Compose、pip check |
| 密钥安全 | 通过 | security-check |
| 真实计费模型任务 | 通过 | 29 events、9 次工具调用、7 张截图、Firefox 进程与原始画面 |

## 人工复验

真实模型复验步骤见 [Anthropic 手工验收](../../anthropic-manual-test.md)。再次执行前仍须确认 API 额度、允许产生费用，并保证 sandbox 中没有个人账号或敏感信息。

## 原始材料

- [自动化与 SDK](./materials/01-自动化与SDK.txt)
- [真实 sandbox 工具桥](./materials/02-真实sandbox工具桥.txt)
- [容器配置与冒烟](./materials/03-容器配置与冒烟.txt)
- [真实计费端到端](./materials/04-真实计费端到端.txt)
- [真实计费任务画面](./artifacts/real-paid-example-domain.png)
