from __future__ import annotations

from typing import Any

from anthropic import APIError, AsyncAnthropic

from app.agents.anthropic_callbacks import AnthropicCallbackAdapter
from app.agents.base import AgentEventSink
from app.agents.remote_tools import (
    DockerSandboxExecutor,
    RemoteBashTool,
    RemoteComputerTool,
    RemoteToolCollection,
    ToolResult,
)

SYSTEM_PROMPT = """You control an isolated Linux desktop assigned to exactly one user session.
Use the computer tool for visible GUI interaction and screenshots. Use bash only inside this
isolated sandbox. Firefox ESR is installed; you can launch it with `firefox-esr` from bash or
through the desktop. The display is 1024x768 on DISPLAY=:1. Never claim an action succeeded
until you have verified it with a screenshot or command output."""


class AnthropicAgentRunner:
    """Run the Anthropic computer-use loop against one session sandbox."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        max_tokens: int = 4096,
        max_iterations: int = 30,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Anthropic API Key 不能为空。")
        if not model.strip():
            raise ValueError("ANTHROPIC_MODEL 不能为空。")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") if base_url else None
        self._model = model
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations

    async def run(
        self,
        user_input: str,
        event_sink: AgentEventSink,
        *,
        runtime_id: str | None = None,
    ) -> str:
        if not runtime_id:
            raise RuntimeError("会话尚未绑定可操作的 sandbox。")

        sandbox = DockerSandboxExecutor(runtime_id)
        tools = RemoteToolCollection(
            RemoteComputerTool(sandbox),
            RemoteBashTool(sandbox),
        )
        adapter = AnthropicCallbackAdapter(event_sink)
        client_kwargs: dict[str, Any] = {"api_key": self._api_key, "max_retries": 2}
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = AsyncAnthropic(**client_kwargs)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": user_input}]}
        ]
        await adapter.start()

        try:
            for _ in range(self._max_iterations):
                try:
                    response = await client.beta.messages.create(
                        model=self._model,
                        max_tokens=self._max_tokens,
                        system=SYSTEM_PROMPT,
                        messages=messages,
                        tools=tools.to_params(),
                        betas=["computer-use-2025-11-24"],
                    )
                except APIError as exc:
                    adapter.api_response_callback(None, None, exc)
                    raise RuntimeError("Anthropic API 调用失败。") from exc

                blocks = [block.model_dump(mode="json") for block in response.content]
                messages.append({"role": "assistant", "content": blocks})
                tool_results: list[dict[str, Any]] = []
                final_text: list[str] = []

                for block in blocks:
                    adapter.output_callback(block)
                    if block.get("type") == "text" and block.get("text"):
                        final_text.append(str(block["text"]))
                    if block.get("type") != "tool_use":
                        continue
                    result = await tools.run(
                        str(block.get("name", "")),
                        dict(block.get("input") or {}),
                    )
                    tool_use_id = str(block.get("id", ""))
                    adapter.tool_output_callback(result, tool_use_id)
                    tool_results.append(self._tool_result_block(result, tool_use_id))

                if not tool_results:
                    return "\n".join(final_text).strip() or "任务已完成。"
                messages.append({"role": "user", "content": tool_results})

            raise RuntimeError("Anthropic Agent 超过最大工具调用轮数。")
        finally:
            await adapter.close()
            await client.close()
            await sandbox.close()

    @staticmethod
    def _tool_result_block(result: ToolResult, tool_use_id: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        text = result.error or result.output
        if result.system:
            text = f"<system>{result.system}</system>\n{text or ''}"
        if text:
            content.append({"type": "text", "text": text})
        if result.base64_image:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": result.base64_image,
                    },
                }
            )
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": bool(result.error),
        }
