import asyncio
import shlex
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import docker
from docker.errors import APIError, NotFound

MAX_TOOL_OUTPUT = 16_000


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class ToolResult:
    output: str | None = None
    error: str | None = None
    base64_image: str | None = None
    system: str | None = None


class SandboxExecutor(Protocol):
    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 120,
    ) -> CommandResult: ...

    async def close(self) -> None: ...


class DockerSandboxExecutor:
    """Execute one argv-safe command in the sandbox bound to a session."""

    def __init__(self, runtime_id: str, client: Any | None = None) -> None:
        self._runtime_id = runtime_id
        self._client = client or docker.from_env()

    async def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: float = 120,
    ) -> CommandResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._execute_sync, command),
                timeout=timeout_seconds + 5,
            )
        except TimeoutError as exc:
            raise RuntimeError("sandbox 命令执行超时。") from exc

    def _execute_sync(self, command: list[str]) -> CommandResult:
        try:
            container = self._client.containers.get(self._runtime_id)
            container.reload()
            if container.status != "running":
                raise RuntimeError("会话 sandbox 当前未运行。")
            result = container.exec_run(
                command,
                demux=True,
                environment={"DISPLAY": ":1", "HOME": "/home/sandbox"},
                user="sandbox",
            )
        except NotFound as exc:
            raise RuntimeError("会话 sandbox 不存在。") from exc
        except APIError as exc:
            raise RuntimeError("Docker 无法在会话 sandbox 中执行工具。") from exc

        stdout, stderr = result.output if isinstance(result.output, tuple) else (result.output, b"")
        return CommandResult(
            exit_code=result.exit_code,
            stdout=stdout or b"",
            stderr=stderr or b"",
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)


class RemoteComputerTool:
    name = "computer"

    def __init__(
        self,
        executor: SandboxExecutor,
        *,
        width: int = 1024,
        height: int = 768,
        settle_seconds: float = 0.5,
    ) -> None:
        self._executor = executor
        self._width = width
        self._height = height
        self._settle_seconds = settle_seconds

    def to_params(self) -> dict[str, Any]:
        return {
            "type": "computer_20251124",
            "name": self.name,
            "display_width_px": self._width,
            "display_height_px": self._height,
            "display_number": 1,
            "enable_zoom": True,
        }

    async def __call__(self, **tool_input: Any) -> ToolResult:
        action = str(tool_input.get("action", ""))
        try:
            return await self._dispatch(action, tool_input)
        except (TypeError, ValueError) as exc:
            return ToolResult(error=f"无效的 computer 工具参数：{exc}")

    async def _dispatch(self, action: str, tool_input: dict[str, Any]) -> ToolResult:
        coordinate = tool_input.get("coordinate")

        if action == "screenshot":
            return await self.screenshot()
        if action == "wait":
            duration = self._duration(tool_input.get("duration"))
            await asyncio.sleep(duration)
            return await self.screenshot()
        if action == "mouse_move":
            x, y = self._coordinate(coordinate)
            return await self._xdotool("mousemove", "--sync", str(x), str(y))
        if action == "left_click_drag":
            start_x, start_y = self._coordinate(tool_input.get("start_coordinate"))
            end_x, end_y = self._coordinate(coordinate)
            return await self._xdotool(
                "mousemove",
                "--sync",
                str(start_x),
                str(start_y),
                "mousedown",
                "1",
                "mousemove",
                "--sync",
                str(end_x),
                str(end_y),
                "mouseup",
                "1",
            )
        if action in {"left_mouse_down", "left_mouse_up"}:
            verb = "mousedown" if action == "left_mouse_down" else "mouseup"
            return await self._xdotool(verb, "1")
        if action == "type":
            text = self._text(tool_input.get("text"))
            for start in range(0, len(text), 50):
                result = await self._execute(
                    ["xdotool", "type", "--delay", "12", "--", text[start : start + 50]],
                    screenshot=False,
                )
                if result.error:
                    return result
            return await self.screenshot()
        if action == "key":
            return await self._xdotool("key", "--", self._text(tool_input.get("text")))
        if action == "cursor_position":
            result = await self._execute(
                ["xdotool", "getmouselocation", "--shell"],
                screenshot=False,
            )
            return result
        if action in {
            "left_click",
            "right_click",
            "middle_click",
            "double_click",
            "triple_click",
        }:
            return await self._click(action, coordinate, tool_input.get("key"))
        if action == "scroll":
            return await self._scroll(tool_input)
        if action == "hold_key":
            return await self._hold_key(tool_input)
        if action == "zoom":
            return await self._zoom(tool_input.get("region"))
        return ToolResult(error=f"不支持的 computer action：{action}")

    async def _click(self, action: str, coordinate: Any, key: Any) -> ToolResult:
        if coordinate is not None:
            x, y = self._coordinate(coordinate)
            moved = await self._execute(
                ["xdotool", "mousemove", "--sync", str(x), str(y)],
                screenshot=False,
            )
            if moved.error:
                return moved

        if key is not None:
            pressed = await self._execute(
                ["xdotool", "keydown", self._text(key)],
                screenshot=False,
            )
            if pressed.error:
                return pressed

        click_args = {
            "left_click": ["click", "1"],
            "right_click": ["click", "3"],
            "middle_click": ["click", "2"],
            "double_click": ["click", "--repeat", "2", "--delay", "10", "1"],
            "triple_click": ["click", "--repeat", "3", "--delay", "10", "1"],
        }[action]
        result = await self._execute(["xdotool", *click_args], screenshot=False)

        if key is not None:
            released = await self._execute(
                ["xdotool", "keyup", self._text(key)],
                screenshot=False,
            )
            if released.error and not result.error:
                result = released
        if result.error:
            return result
        await asyncio.sleep(self._settle_seconds)
        return await self.screenshot()

    async def _scroll(self, tool_input: dict[str, Any]) -> ToolResult:
        direction = str(tool_input.get("scroll_direction", ""))
        button = {"up": "4", "down": "5", "left": "6", "right": "7"}.get(direction)
        if button is None:
            return ToolResult(error="scroll_direction 必须是 up/down/left/right。")
        amount = tool_input.get("scroll_amount")
        if not isinstance(amount, int) or not 0 <= amount <= 1000:
            return ToolResult(error="scroll_amount 必须是 0 到 1000 的整数。")

        coordinate = tool_input.get("coordinate")
        if coordinate is not None:
            x, y = self._coordinate(coordinate)
            moved = await self._execute(
                ["xdotool", "mousemove", "--sync", str(x), str(y)],
                screenshot=False,
            )
            if moved.error:
                return moved

        modifier = tool_input.get("text")
        if modifier:
            await self._execute(
                ["xdotool", "keydown", self._text(modifier)],
                screenshot=False,
            )
        result = await self._execute(
            ["xdotool", "click", "--repeat", str(amount), button],
            screenshot=False,
        )
        if modifier:
            await self._execute(
                ["xdotool", "keyup", self._text(modifier)],
                screenshot=False,
            )
        if result.error:
            return result
        await asyncio.sleep(self._settle_seconds)
        return await self.screenshot()

    async def _hold_key(self, tool_input: dict[str, Any]) -> ToolResult:
        key = self._text(tool_input.get("text"))
        duration = self._duration(tool_input.get("duration"))
        pressed = await self._execute(["xdotool", "keydown", key], screenshot=False)
        if pressed.error:
            return pressed
        try:
            await asyncio.sleep(duration)
        finally:
            await self._execute(["xdotool", "keyup", key], screenshot=False)
        return await self.screenshot()

    async def _zoom(self, region: Any) -> ToolResult:
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            return ToolResult(error="zoom region 必须包含四个坐标。")
        x0, y0 = self._coordinate(region[:2])
        x1, y1 = self._coordinate(region[2:])
        if x1 <= x0 or y1 <= y0:
            return ToolResult(error="zoom region 的右下角必须大于左上角。")
        return await self._capture(area=(x0, y0, x1 - x0, y1 - y0))

    async def _xdotool(self, *args: str) -> ToolResult:
        return await self._execute(["xdotool", *args], screenshot=True)

    async def _execute(self, command: list[str], *, screenshot: bool) -> ToolResult:
        result = await self._executor.execute(command, timeout_seconds=30)
        output = self._decode(result.stdout)
        error = self._decode(result.stderr) if result.exit_code else None
        if result.exit_code and not error:
            error = f"sandbox 命令退出码：{result.exit_code}"
        if error or not screenshot:
            return ToolResult(output=output or None, error=error)
        await asyncio.sleep(self._settle_seconds)
        captured = await self.screenshot()
        return ToolResult(output=output or None, base64_image=captured.base64_image)

    async def screenshot(self) -> ToolResult:
        return await self._capture(area=None)

    async def _capture(self, area: tuple[int, int, int, int] | None) -> ToolResult:
        path = f"/tmp/computer-use-{uuid.uuid4().hex}.png"
        capture = ["scrot", "-p"]
        if area is not None:
            capture.extend(["-a", ",".join(str(value) for value in area)])
        capture.append(path)
        created = await self._executor.execute(capture, timeout_seconds=30)
        if created.exit_code:
            return ToolResult(error=self._decode(created.stderr) or "截图失败。")
        encoded = await self._executor.execute(["base64", "-w", "0", path], timeout_seconds=30)
        await self._executor.execute(["rm", "-f", path], timeout_seconds=30)
        if encoded.exit_code:
            return ToolResult(error=self._decode(encoded.stderr) or "读取截图失败。")
        return ToolResult(base64_image=encoded.stdout.decode("ascii"))

    def _coordinate(self, value: Any) -> tuple[int, int]:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("coordinate 必须包含两个整数")
        x, y = value
        if not isinstance(x, int) or not isinstance(y, int):
            raise ValueError("coordinate 必须是整数")
        if not 0 <= x < self._width or not 0 <= y < self._height:
            raise ValueError("coordinate 超出桌面范围")
        return x, y

    @staticmethod
    def _duration(value: Any) -> float:
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError("duration 必须是 0 到 100 的数字")
        return float(value)

    @staticmethod
    def _text(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("text 必须是非空字符串")
        return value

    @staticmethod
    def _decode(value: bytes) -> str:
        return value.decode(errors="replace")[:MAX_TOOL_OUTPUT]


class RemoteBashTool:
    name = "bash"

    def __init__(self, executor: SandboxExecutor) -> None:
        self._executor = executor

    def to_params(self) -> dict[str, str]:
        return {"type": "bash_20250124", "name": self.name}

    async def __call__(self, **tool_input: Any) -> ToolResult:
        if tool_input.get("restart"):
            return ToolResult(system="bash 工具使用无状态隔离执行，无需重启。")
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return ToolResult(error="bash command 必须是非空字符串。")
        wrapped = [
            "timeout",
            "--signal=KILL",
            "120s",
            "/bin/bash",
            "-lc",
            command,
        ]
        result = await self._executor.execute(wrapped, timeout_seconds=120)
        output = result.stdout.decode(errors="replace")[:MAX_TOOL_OUTPUT]
        error = result.stderr.decode(errors="replace")[:MAX_TOOL_OUTPUT]
        if result.exit_code and not error:
            error = f"bash 退出码：{result.exit_code}"
        return ToolResult(output=output or None, error=error or None)


class RemoteToolCollection:
    def __init__(self, *tools: RemoteComputerTool | RemoteBashTool) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def to_params(self) -> list[dict[str, Any]]:
        return [tool.to_params() for tool in self._tools.values()]

    async def run(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(error=f"未知工具：{shlex.quote(name)}")
        return await tool(**tool_input)
