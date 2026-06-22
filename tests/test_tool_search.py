import asyncio

from pydantic import BaseModel

from aixcode.tools import ToolRegistry
from aixcode.tools.base import Tool, ToolResult
from aixcode.tools.tool_search import ToolSearchTool


class _P(BaseModel):
    pass


class Deferred(Tool):
    name = "SpecialThing"
    description = "does special slack work"
    params_model = _P
    category = "read"
    should_defer = True

    async def execute(self, params):
        return ToolResult("ok")


def _reg():
    reg = ToolRegistry()
    reg.register(Deferred())
    return reg


def _run(tool, query):
    return asyncio.run(tool.execute(tool.params_model(query=query)))


def test_tool_search_not_deferred_itself():
    assert ToolSearchTool(_reg()).should_defer is False


def test_select_prefix_finds_by_name_and_marks_discovered():
    reg = _reg()
    result = _run(ToolSearchTool(reg), "select:SpecialThing")

    assert "Found 1 tool" in result.output
    assert "SpecialThing" in result.output
    assert reg.is_discovered("SpecialThing") is True


def test_keyword_search_finds():
    reg = _reg()
    result = _run(ToolSearchTool(reg), "slack")

    assert "SpecialThing" in result.output
    assert reg.is_discovered("SpecialThing") is True


def test_miss_lists_available_deferred():
    reg = _reg()
    result = _run(ToolSearchTool(reg), "select:Nonexistent")

    assert 'No matching deferred tools for' in result.output
    assert "SpecialThing" in result.output  # 回退列出可用 deferred 名
