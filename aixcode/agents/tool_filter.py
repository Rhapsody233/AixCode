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

# ch15：Coordinator Mode 白名单（写工具 WriteFile/EditFile 被排除）
COORDINATOR_MODE_ALLOWED_TOOLS = frozenset(
    {"Agent", "SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
     "TeamCreate", "TeamDelete", "ReadFile", "Glob", "Grep", "Bash"}
)

# ch15：队员可见的协作工具
TEAMMATE_COORDINATION_TOOLS = frozenset(
    {"SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate"}
)

# ch15：in-process 队员严格白名单（无 Cron，AixCode 不实现）
IN_PROCESS_TEAMMATE_ALLOWED_TOOLS = (
    ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS
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


def apply_coordinator_filter(registry: ToolRegistry) -> ToolRegistry:
    """Coordinator Mode：重建一个只含 12 项白名单（MCP 直通）的新 ToolRegistry。"""
    new = ToolRegistry()
    for tool in registry.list_tools():
        if _is_mcp(tool.name) or tool.name in COORDINATOR_MODE_ALLOWED_TOOLS:
            new.register(tool)
    return new


def build_teammate_tools(registry: ToolRegistry, backend) -> ToolRegistry:
    """按后端分流构造队员工具池：in-process 严格白名单；pane 仅剔除 TeamCreate/TeamDelete。"""
    from aixcode.teams.models import BackendType

    in_process = backend == BackendType.IN_PROCESS
    new = ToolRegistry()
    for tool in registry.list_tools():
        name = tool.name
        if _is_mcp(name):
            new.register(tool)
            continue
        if in_process:
            if name in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS:
                new.register(tool)
        elif name not in ("TeamCreate", "TeamDelete"):
            new.register(tool)
    return new
