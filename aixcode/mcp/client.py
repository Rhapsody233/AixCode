"""单个 MCP server 的会话句柄：连接 → 工具发现 → 工具调用 → 收尾。

复用官方 mcp SDK；传输与会话生命周期统一挂在 AsyncExitStack 上，close 时静默
吞掉 anyio 在跨 task 收尾时抛的 "cancel scope" RuntimeError（已知 SDK race）。
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from aixcode.config import MCPServerConfig, build_child_env, resolve_env_vars

logger = logging.getLogger(__name__)


class MCPClient:
    """一个 MCP server 的连接 + 会话。"""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.name = config.name
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._alive = False

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def connect(self) -> None:
        """按传输类型握手；失败回滚 AsyncExitStack 并置 _alive=False。"""
        self._stack = AsyncExitStack()
        try:
            if self.config.is_stdio:
                read, write = await self._connect_stdio()
            else:
                read, write = await self._connect_http()
            session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._session = session
            self._alive = True
        except Exception:
            await self._cleanup_stack()
            self._alive = False
            raise

    async def _connect_stdio(self):
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=build_child_env(self.config.env),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        return read, write

    async def _connect_http(self):
        headers = resolve_env_vars(self.config.headers)
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(self.config.url, headers=headers)
        )
        return read, write

    async def list_tools(self) -> list[types.Tool]:
        return (await self._session.list_tools()).tools

    async def call_tool(self, name: str, args: dict):
        return await self._session.call_tool(name, args)

    # --- ch16：资源与提示（SDK 直通）---

    async def list_resources(self) -> list:
        return (await self._session.list_resources()).resources

    async def read_resource(self, uri) -> str:
        """读资源，把各 contents 的文本部分拼成字符串。"""
        result = await self._session.read_resource(uri)
        parts = [
            t for c in getattr(result, "contents", []) or []
            if (t := getattr(c, "text", None))
        ]
        return "\n".join(parts)

    async def list_prompts(self) -> list:
        return (await self._session.list_prompts()).prompts

    async def get_prompt(self, name: str, args: dict) -> str:
        """取 prompt，把各 message 的文本内容拼成字符串。"""
        result = await self._session.get_prompt(name, args)
        parts = []
        for msg in getattr(result, "messages", []) or []:
            content = getattr(msg, "content", None)
            t = getattr(content, "text", None)
            if t:
                parts.append(t)
        return "\n".join(parts)

    async def close(self) -> None:
        self._alive = False
        await self._cleanup_stack()

    async def _cleanup_stack(self) -> None:
        """交还 AsyncExitStack；吞掉 anyio 的 cancel-scope RuntimeError。"""
        if self._stack is None:
            return
        try:
            await self._stack.aclose()
        except RuntimeError as e:
            if "cancel scope" not in str(e):
                logger.debug("MCP client %s 收尾异常：%s", self.name, e)
        except Exception as e:  # noqa: BLE001
            logger.debug("MCP client %s 收尾异常：%s", self.name, e)
        finally:
            self._stack = None
            self._session = None
