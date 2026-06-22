"""ToolSearch：渐进式工具披露入口（按名精确选 / 关键词搜）。"""

from __future__ import annotations

import json

from pydantic import BaseModel

from aixcode.tools import ToolRegistry
from aixcode.tools.base import Tool, ToolResult


class ToolSearchParams(BaseModel):
    query: str
    max_results: int = 5


class ToolSearchTool(Tool):
    name = "ToolSearch"
    description = (
        "搜索按需披露的工具。用 select:Name1,Name2 精确选，或用关键词搜索。"
    )
    params_model = ToolSearchParams
    category = "read"
    is_system_tool = True
    should_defer = False

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, params: ToolSearchParams) -> ToolResult:
        query = params.query.strip()
        if query.startswith("select:"):
            names = [n.strip() for n in query[len("select:"):].split(",") if n.strip()]
            results = self._registry.find_deferred_by_names(names)
        else:
            results = self._registry.search_deferred(query, params.max_results)

        if not results:
            available = ", ".join(self._registry.get_deferred_tool_names())
            return ToolResult(
                f'No matching deferred tools for "{query}". Available: {available}'
            )

        body = f"Found {len(results)} tool(s):\n" + json.dumps(
            results, ensure_ascii=False, indent=2
        )
        return ToolResult(body)
