# 上游代码溯源

本项目以 Anthropic 官方 Computer Use 演示项目为基线，用 FastAPI 控制面替换实验性的 Streamlit 交互层，并把原先单容器内执行的模型工具循环改造成面向每个 session sandbox 的远程工具桥。

## 导入信息

- 上游仓库：<https://github.com/anthropics/claude-quickstarts>
- 上游目录：`computer-use-demo`
- 固定提交：`f37f1685e256d61b2982b8ae69c857b51efe11bf`
- 上游提交说明：`Add adaptive thinking support to the computer-use demo (#411)`
- 导入日期：2026-08-17
- 本地基线提交：`chore: import pinned Anthropic computer-use baseline`

## 许可与修改原则

原始 MIT License 保留在仓库根目录。后续修改遵循以下原则：

1. agent loop 和 computer/bash/edit 工具尽可能保持为可识别的上游代码；
2. 与 FastAPI、持久化、事件流和运行时隔离有关的新代码放入独立模块；
3. 对上游代码的实质修改在对应里程碑 PR 中解释原因；
4. 升级上游版本必须使用独立 PR，并记录新旧 commit SHA 和兼容性测试结果。

## 已知上游限制

上游 README 明确说明原演示的组件分离较弱，agent loop 运行在被控制的容器中，而且一次只能支持一个会话。当前项目的主要工程目标就是通过控制面、持久化和每会话独立运行时解决这些限制。
