"""ch16 T12：AixCodeApp._init_mcp 接入 MCP 资源/提示的集成测试。"""

import asyncio
import io

from rich.console import Console

import aixcode.app as appmod
from aixcode.app import AixCodeApp
from aixcode.config import MCPServerConfig
from aixcode.conversation import ConversationManager
from aixcode.permissions import PermissionMode
from aixcode.tools import ToolRegistry


class _FakeManager:
    def load_configs(self, cfgs):
        pass

    async def register_all_tools(self, registry):
        return []

    async def register_all_resources(self):
        return [("srv", "mem://a", "A", "desc")]

    async def list_all_prompts(self):
        return [("srv", "greet", "desc")]

    async def get_prompt(self, server, name, args):
        return "PROMPT"

    async def shutdown(self):
        pass


class _MiniAgent:
    def __init__(self):
        self.permission_mode = PermissionMode.DEFAULT
        self.memory_manager = None
        self.registry = ToolRegistry()

    def set_permission_mode(self, m):
        self.permission_mode = m


def test_init_mcp_wires_resources_and_prompts(monkeypatch):
    monkeypatch.setattr(appmod, "MCPManager", _FakeManager)
    agent = _MiniAgent()
    app = AixCodeApp(
        agent, ConversationManager(), model="deepseek-chat",
        mcp_servers=[MCPServerConfig(name="srv", command="x")],
    )
    app.console = Console(file=io.StringIO(), record=True, width=120)
    asyncio.run(app._init_mcp())
    assert agent.registry.get("ReadMcpResource") is not None
    assert app.command_registry.find("mcp__srv__greet") is not None
