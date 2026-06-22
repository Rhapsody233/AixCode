"""多 MCP server 调度：连接、把工具注册进 ToolRegistry、懒连/重连、统一收尾。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from aixcode.config import MCPServerConfig
from aixcode.mcp.client import MCPClient
from aixcode.mcp.tool_wrapper import MCPToolWrapper

logger = logging.getLogger(__name__)


class MCPManager:
    """持有多个 server 的配置与已连接客户端，统一对外。"""

    def __init__(
        self, client_factory: Callable[[MCPServerConfig], MCPClient] = MCPClient
    ) -> None:
        self._client_factory = client_factory
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        for cfg in configs:
            self._configs[cfg.name] = cfg

    async def register_all_tools(self, registry) -> list[str]:
        """顺序连接每个 server，把其工具包成 wrapper 注册；单个失败不阻塞其余。"""
        errors: list[str] = []
        for name in self._configs:
            try:
                client = await self.get_client(name)
                for tool_def in await client.list_tools():
                    registry.register(MCPToolWrapper(self, name, tool_def))
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server %r 连接失败：%s", name, e)
                errors.append(f"{name}: {e}")
        return errors

    async def get_client(self, name: str) -> MCPClient:
        """返回活客户端：缓存命中且存活直接复用，否则（重）建并连接。"""
        existing = self._clients.get(name)
        if existing is not None and existing.is_alive:
            return existing
        client = self._client_factory(self._configs[name])
        await client.connect()
        self._clients[name] = client
        return client

    async def shutdown(self) -> None:
        """幂等关闭所有客户端，异常仅记日志。"""
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception as e:  # noqa: BLE001
                logger.debug("关闭 MCP client 异常：%s", e)
        self._clients.clear()
