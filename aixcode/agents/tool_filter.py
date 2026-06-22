"""四层工具过滤：按子 Agent 定义与运行模式重建一个受限 ToolRegistry。"""

from __future__ import annotations

from aixcode.agents.parser import AgentDef
from aixcode.tools import ToolRegistry

# 任意层级子 Agent 一律禁用：防递归（Agent）+ 禁交互式提问（AskUser）
ALL_AGENT_DISALLOWED_TOOLS = frozenset({"Agent", "AskUser"})

# 非 builtin 来源的子 Agent 额外禁用
CUSTOM_AGENT_DISALLOWED_TOOLS = frozenset({"LoadSkill"})

# 后台子 Agent 只保留这些（无需 HITL 的工具）
ASYNC_AGENT_ALLOWED_TOOLS = frozenset(
    {"ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep",
     "ToolSearch", "LoadSkill"}
)


def _is_mcp(name: str) -> bool:
    return name.startswith("mcp_")


def resolve_agent_tools(
    registry: ToolRegistry, definition: AgentDef, is_background: bool
) -> ToolRegistry:
    """按四层规则重建一个新 ToolRegistry；MCP 工具一律直通。"""
    disallowed = set(ALL_AGENT_DISALLOWED_TOOLS)
    if definition.source != "builtin":
        disallowed |= CUSTOM_AGENT_DISALLOWED_TOOLS
    disallowed |= set(definition.disallowed_tools)

    def_whitelist = set(definition.tools) if definition.tools else None

    new = ToolRegistry()
    for tool in registry.list_tools():
        name = tool.name
        if _is_mcp(name):
            new.register(tool)  # MCP 直通，不受任何层约束
            continue
        if name in disallowed:
            continue
        if is_background and name not in ASYNC_AGENT_ALLOWED_TOOLS:
            continue
        if def_whitelist is not None and name not in def_whitelist:
            continue
        new.register(tool)
    return new
