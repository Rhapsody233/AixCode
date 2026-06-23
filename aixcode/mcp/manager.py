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
        self._resource_index: dict[str, str] = {}  # ch16：uri(str) → server name

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

    # --- ch16：资源与提示发现 + 路由 ---

    async def register_all_resources(self) -> list[tuple]:
        """顺序连每个 server 收资源清单，建 uri→server 索引；单 server 失败不阻塞。"""
        out: list[tuple] = []
        for name in self._configs:
            try:
                client = await self.get_client(name)
                for r in await client.list_resources():
                    uri = str(getattr(r, "uri", ""))
                    self._resource_index[uri] = name
                    out.append(
                        (name, uri, getattr(r, "name", ""), getattr(r, "description", ""))
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server %r 资源发现失败：%s", name, e)
        return out

    async def read_resource(self, uri) -> str:
        """按 uri→server 索引路由到对应 client 读取；未知 uri 抛 KeyError。"""
        server = self._resource_index.get(str(uri))
        if server is None:
            raise KeyError(f"未知资源 uri: {uri}")
        client = await self.get_client(server)
        return await client.read_resource(uri)

    async def list_all_prompts(self) -> list[tuple]:
        """顺序连每个 server 收 (server, name, description)；单 server 失败不阻塞。"""
        out: list[tuple] = []
        for name in self._configs:
            try:
                client = await self.get_client(name)
                for p in await client.list_prompts():
                    out.append((name, getattr(p, "name", ""), getattr(p, "description", "")))
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server %r 提示发现失败：%s", name, e)
        return out

    async def get_prompt(self, server: str, name: str, args: dict) -> str:
        client = await self.get_client(server)
        return await client.get_prompt(name, args)

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
