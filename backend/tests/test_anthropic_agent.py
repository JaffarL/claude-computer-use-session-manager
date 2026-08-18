from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from anthropic import AsyncAnthropic

import app.agents.anthropic as anthropic_module
from app.agents.anthropic import AnthropicAgentRunner
from app.agents.remote_tools import CommandResult, RemoteBashTool, RemoteComputerTool
from app.domain import EventType


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict[str, Any]]] = []

    async def emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class FakeSandbox:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.closed = False

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 120,
    ) -> CommandResult:
        self.commands.append(command)
        if command[:3] == ["base64", "-w", "0"]:
            return CommandResult(0, b"cG5n", b"")
        return CommandResult(0, b"", b"")

    async def close(self) -> None:
        self.closed = True


class FakeBlock:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self._payload


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = [
            SimpleNamespace(
                content=[
                    FakeBlock(
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "computer",
                            "input": {"action": "screenshot"},
                        }
                    )
                ]
            ),
            SimpleNamespace(content=[FakeBlock({"type": "text", "text": "任务完成"})]),
        ]

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()
        self.beta = SimpleNamespace(messages=self.messages)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_anthropic_runner_executes_tool_in_bound_sandbox_and_publishes_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = FakeSandbox()
    client = FakeAnthropicClient()
    monkeypatch.setattr(anthropic_module, "DockerSandboxExecutor", lambda _: sandbox)
    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", lambda **_: client)
    sink = RecordingSink()
    runner = AnthropicAgentRunner(
        api_key="test-key",
        base_url="https://example.invalid",
        model="claude-sonnet-test",
    )

    final_text = await runner.run("查看桌面", sink, runtime_id="runtime-a")

    assert final_text == "任务完成"
    assert [event_type for event_type, _ in sink.events] == [
        EventType.TOOL_STARTED,
        EventType.TOOL_RESULT,
        EventType.SCREENSHOT_AVAILABLE,
        EventType.ASSISTANT_MESSAGE,
    ]
    assert sandbox.commands[0][0] == "scrot"
    assert client.messages.calls[0]["tools"][0]["type"] == "computer_20251124"
    assert client.messages.calls[0]["betas"] == ["computer-use-2025-11-24"]
    tool_result_messages = [
        message
        for message in client.messages.calls[1]["messages"]
        if message["role"] == "user"
        and isinstance(message["content"], list)
        and message["content"]
        and message["content"][0].get("type") == "tool_result"
    ]
    assert tool_result_messages[-1]["content"][0]["tool_use_id"] == "tool-1"
    assert sandbox.closed and client.closed


@pytest.mark.asyncio
async def test_remote_computer_rejects_out_of_bounds_coordinate() -> None:
    sandbox = FakeSandbox()
    tool = RemoteComputerTool(sandbox, settle_seconds=0)

    result = await tool(action="mouse_move", coordinate=[2048, 10])

    assert result.error and "超出桌面范围" in result.error
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_remote_bash_runs_only_inside_sandbox() -> None:
    sandbox = FakeSandbox()
    tool = RemoteBashTool(sandbox)

    result = await tool(command="printf test")

    assert result.error is None
    assert sandbox.commands == [
        ["timeout", "--signal=KILL", "120s", "/bin/bash", "-lc", "printf test"]
    ]


@pytest.mark.asyncio
async def test_anthropic_sdk_serializes_current_computer_use_payload() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg-test",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnthropic(
        api_key="test-key",
        base_url="https://example.invalid",
        http_client=http_client,
    )
    try:
        response = await client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            tools=[
                {
                    "type": "computer_20251124",
                    "name": "computer",
                    "display_width_px": 1024,
                    "display_height_px": 768,
                    "display_number": 1,
                    "enable_zoom": True,
                },
                {"type": "bash_20250124", "name": "bash"},
            ],
            betas=["computer-use-2025-11-24"],
        )
    finally:
        await client.close()

    assert response.content[0].text == "ok"  # type: ignore[union-attr]
    assert requests[0].url == "https://example.invalid/v1/messages?beta=true"
    assert requests[0].headers["anthropic-beta"] == "computer-use-2025-11-24"
