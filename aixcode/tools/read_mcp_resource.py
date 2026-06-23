"""ReadMcpResource：按 uri 读取已接入 MCP server 暴露的资源（ch16）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult


class ReadMcpResourceParams(BaseModel):
    uri: str = Field(..., description="资源 uri（来自环境里列出的 MCP 资源清单）")


class ReadMcpResource(Tool):
    name = "ReadMcpResource"
    description = "按 uri 读取已接入 MCP server 暴露的资源内容。"
    params_model = ReadMcpResourceParams
    category = "read"
    should_defer = True
    is_system_tool = True

    def __init__(self, mcp_manager) -> None:
        self.mcp_manager = mcp_manager

    async def execute(self, params: ReadMcpResourceParams) -> ToolResult:
        try:
            text = await self.mcp_manager.read_resource(params.uri)
        except Exception as e:  # noqa: BLE001
            return ToolResult(f"读取 MCP 资源失败（{params.uri}）：{e}", is_error=True)
        return ToolResult(text or "(资源为空)")
