"""Slash Command 数据模型 + 进程内注册中心。

不 import app/agent 实现细节：反向依赖通过 CommandContext.config 闭包与
UIController 注入。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


class CommandType(Enum):
    """命令三态。

    LOCAL    —— handler 回显系统消息（如 help/status/memory）。
    LOCAL_UI —— handler 改 UI 状态（清屏 / 切 Plan / 切 mode / 压缩 / session）。
    PROMPT   —— handler 经 ui.send_user_message 把构造好的 prompt 投回 Agent。
    """

    LOCAL = "local"
    LOCAL_UI = "local_ui"
    PROMPT = "prompt"


@runtime_checkable
class UIController(Protocol):
    """handler 与 app 交互的窄接口（不直接依赖 rich/prompt_toolkit 细节）。"""

    def add_system_message(self, text: str) -> None: ...
    async def send_user_message(self, text: str) -> None: ...
    def set_plan_mode(self, on: bool) -> None: ...
    def get_token_count(self) -> int: ...
    def refresh_status(self) -> None: ...


@dataclass
class Command:
    """一个 slash 命令的声明。"""

    name: str
    description: str
    handler: Callable[[CommandContext], Awaitable[None]]
    type: CommandType
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    arg_prompt: str = ""
    hidden: bool = False


@dataclass
class CommandContext:
    """传给 handler 的运行时句柄集合。

    config 托管 app 回写闭包（set_conversation / clear_chat / set_session 等），
    让 commands 包无需 import app 即可改 app 状态。
    """

    args: str
    agent: Any
    conversation: Any
    session: Any
    session_manager: Any
    memory_manager: Any
    ui: UIController
    config: dict[str, Any]


class CommandRegistry:
    """命令注册中心：name + alias 索引，注册并发安全，冲突即抛。"""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def register_sync(self, cmd: Command) -> None:
        """同步注册；name 或 alias 与已有冲突抛 ValueError。"""
        if cmd.name in self._commands or cmd.name in self._alias_map:
            raise ValueError(f"命令名冲突: {cmd.name}")
        for alias in cmd.aliases:
            if alias in self._commands or alias in self._alias_map:
                raise ValueError(f"别名冲突: {alias}")
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._alias_map[alias] = cmd.name

    async def register(self, cmd: Command) -> None:
        """并发安全注册（为后续 skill 热重载预留）。"""
        async with self._lock:
            self.register_sync(cmd)

    def unregister(self, name: str) -> None:
        """注销命令及其别名（缺失则忽略）。"""
        cmd = self._commands.pop(name, None)
        if cmd is None:
            return
        for alias in cmd.aliases:
            self._alias_map.pop(alias, None)

    def find(self, name: str) -> Command | None:
        """按 name 或 alias 查找。"""
        if name in self._commands:
            return self._commands[name]
        canonical = self._alias_map.get(name)
        if canonical is not None:
            return self._commands.get(canonical)
        return None

    def list_commands(self) -> list[Command]:
        """返回全部命令（含 hidden）。"""
        return list(self._commands.values())
