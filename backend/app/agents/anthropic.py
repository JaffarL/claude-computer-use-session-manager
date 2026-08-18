from __future__ import annotations

import html
import json
import re
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
until you have verified it with a screenshot or command output. Always use native tool_use
blocks and wait for real tool results. Never fabricate tool output or a screenshot result."""

FUNCTION_CALLS_PATTERN = re.compile(
    r"<function_calls>(.*?)</function_calls>",
    re.IGNORECASE | re.DOTALL,
)
INVOKE_PATTERN = re.compile(
    r'<invoke\s+name=["\']([^"\']+)["\']>(.*?)</invoke>',
    re.IGNORECASE | re.DOTALL,
)
PARAMETER_PATTERN = re.compile(
    r'<parameter\s+name=["\']([^"\']+)["\']>(.*?)</parameter>',
    re.IGNORECASE | re.DOTALL,
)


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
            for iteration in range(self._max_iterations):
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
                fallback_calls: list[tuple[str, dict[str, Any]]] = []

                for block in blocks:
                    if block.get("type") == "text" and block.get("text"):
                        text = str(block["text"])
                        parsed_calls = self._parse_text_tool_calls(text)
                        if parsed_calls:
                            fallback_calls.extend(parsed_calls)
                        else:
                            adapter.output_callback(block)
                            final_text.append(text)
                    if block.get("type") != "tool_use":
                        continue
                    adapter.output_callback(block)
                    result = await tools.run(
                        str(block.get("name", "")),
                        dict(block.get("input") or {}),
                    )
                    tool_use_id = str(block.get("id", ""))
                    adapter.tool_output_callback(result, tool_use_id)
                    tool_results.append(self._tool_result_block(result, tool_use_id))

                if fallback_calls:
                    fallback_results: list[dict[str, Any]] = [
                        {
                            "type": "text",
                            "text": (
                                "The previous response contained proposed textual tool calls. "
                                "Ignore any claimed outputs in that response. The following are "
                                "the real results produced by the isolated sandbox. Continue from "
                                "these results and use another tool call if verification is needed."
                            ),
                        }
                    ]
                    for call_index, (name, tool_input) in enumerate(fallback_calls):
                        tool_use_id = f"text-tool-{iteration + 1}-{call_index + 1}"
                        adapter.output_callback(
                            {
                                "type": "tool_use",
                                "id": tool_use_id,
                                "name": name,
                                "input": tool_input,
                            }
                        )
                        result = await tools.run(name, tool_input)
                        adapter.tool_output_callback(result, tool_use_id)
                        fallback_results.extend(self._fallback_result_content(name, result))
                    messages.append({"role": "user", "content": fallback_results})
                    continue

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

    @staticmethod
    def _parse_text_tool_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
        calls: list[tuple[str, dict[str, Any]]] = []
        for function_body in FUNCTION_CALLS_PATTERN.findall(text):
            for raw_name, invoke_body in INVOKE_PATTERN.findall(function_body):
                name = html.unescape(raw_name.strip())
                tool_input = {
                    html.unescape(raw_key.strip()): AnthropicAgentRunner._parse_parameter(raw_value)
                    for raw_key, raw_value in PARAMETER_PATTERN.findall(invoke_body)
                }
                calls.append((name, tool_input))
        return calls

    @staticmethod
    def _parse_parameter(value: str) -> Any:
        decoded = html.unescape(value.strip())
        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            return decoded

    @staticmethod
    def _fallback_result_content(name: str, result: ToolResult) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        status = "error" if result.error else "success"
        output = result.error or result.output or "(no textual output)"
        content.append(
            {
                "type": "text",
                "text": f"Actual sandbox result for {name} ({status}):\n{output}",
            }
        )
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
        return content
