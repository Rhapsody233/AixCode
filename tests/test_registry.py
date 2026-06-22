import asyncio

from pydantic import BaseModel

from aixcode.tools import ToolRegistry, create_default_registry
from aixcode.tools.base import Tool, ToolResult


class _P(BaseModel):
    x: int = 0


class RegularTool(Tool):
    name = "Regular"
    description = "a regular read tool"
    params_model = _P
    category = "read"

    async def execute(self, params):
        return ToolResult("ok")


class DeferredTool(Tool):
    name = "SpecialSearch"
    description = "search special slack things"
    params_model = _P
    category = "read"
    should_defer = True

    async def execute(self, params):
        return ToolResult("ok")


def _registry():
    reg = ToolRegistry()
    reg.register(RegularTool())
    reg.register(DeferredTool())
    return reg


def test_register_get_list():
    reg = _registry()
    assert reg.get("Regular").name == "Regular"
    assert reg.get("missing") is None
    assert {t.name for t in reg.list_tools()} == {"Regular", "SpecialSearch"}


def test_disable_excludes_from_schemas():
    reg = _registry()
    reg.disable("Regular")
    assert reg.is_enabled("Regular") is False
    names = [s["function"]["name"] for s in reg.get_all_schemas()]
    assert "Regular" not in names


def test_get_all_schemas_chat_completions_shape():
    reg = _registry()
    schema = next(s for s in reg.get_all_schemas() if s["function"]["name"] == "Regular")
    assert schema["type"] == "function"
    assert schema["function"]["description"] == "a regular read tool"
    assert "parameters" in schema["function"]


def test_deferred_hidden_until_discovered():
    reg = _registry()
    names = [s["function"]["name"] for s in reg.get_all_schemas()]
    assert "SpecialSearch" not in names

    reg.mark_discovered("SpecialSearch")
    names = [s["function"]["name"] for s in reg.get_all_schemas()]
    assert "SpecialSearch" in names


def test_get_deferred_tool_names():
    reg = _registry()
    assert reg.get_deferred_tool_names() == ["SpecialSearch"]
    reg.mark_discovered("SpecialSearch")
    assert reg.get_deferred_tool_names() == []


def test_search_deferred_by_keyword_marks_discovered():
    reg = _registry()
    results = reg.search_deferred("slack")
    assert [s["function"]["name"] for s in results] == ["SpecialSearch"]
    assert reg.is_discovered("SpecialSearch") is True


def test_find_deferred_by_names_only_deferred_and_marks():
    reg = _registry()
    # 普通工具不是 deferred，按名查不到
    assert reg.find_deferred_by_names(["Regular"]) == []
    results = reg.find_deferred_by_names(["SpecialSearch"])
    assert [s["function"]["name"] for s in results] == ["SpecialSearch"]
    assert reg.is_discovered("SpecialSearch") is True


def test_execute_still_works():
    reg = _registry()
    result = asyncio.run(reg.get("Regular").execute(_P()))
    assert result.output == "ok"


def test_create_default_registry_has_six_core_tools():
    reg = create_default_registry()
    names = {t.name for t in reg.list_tools()}
    assert names == {"ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep"}
