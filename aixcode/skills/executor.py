"""SkillExecutor：inline / fork 两种执行 + 工具白名单过滤。"""

from __future__ import annotations

from aixcode.conversation import ConversationManager
from aixcode.skills.parser import SkillDef, substitute_arguments
from aixcode.tools import ToolRegistry

# 不受 allowed_tools 白名单约束、始终透传的系统工具
SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})


class SkillDependencyError(Exception):
    """skill 的 allowed_tools 里声明了 registry 中不存在的工具。"""


def filter_tool_registry(registry: ToolRegistry, allowed: list[str]) -> ToolRegistry:
    """按 allowed 重建一个新 ToolRegistry；空白名单返回原 registry。

    缺工具立刻 raise SkillDependencyError；`is_system_tool=True` 的工具自动透传。
    """
    if not allowed:
        return registry
    new = ToolRegistry()
    added: set[str] = set()
    for name in allowed:
        tool = registry.get(name)
        if tool is None:
            raise SkillDependencyError(f"skill 依赖的工具不存在：{name}")
        new.register(tool)
        added.add(name)
    for tool in registry.list_tools():
        if tool.is_system_tool and tool.name not in added:
            new.register(tool)
            added.add(tool.name)
    return new


class SkillExecutor:
    """执行 skill：inline 钉到主对话上下文，fork 开独立子 Agent 回流摘要。"""

    def __init__(self, agent, client, protocol: str) -> None:
        self.agent = agent
        self.client = client
        self.protocol = protocol

    async def execute_inline(self, skill: SkillDef, args: str) -> None:
        """渲染 SOP 并钉到 Agent 上下文；不直接调 LLM（由命令 handler 触发 loop）。"""
        rendered = substitute_arguments(skill.prompt_body, args)
        self.agent.activate_skill(skill.name, rendered)

    async def execute_fork(
        self, skill: SkillDef, args: str, source_conversation=None
    ) -> str:
        """开独立子 Agent 隔离执行，把累计文本回流为摘要字符串。"""
        # 局部 import 避免与 agent 形成循环依赖
        from aixcode.agent import Agent, ErrorEvent, LoopComplete, StreamText

        rendered = substitute_arguments(skill.prompt_body, args)
        fork_conv = ConversationManager()
        self._build_fork_context(skill.context, source_conversation, fork_conv)
        fork_conv.add_user_message(rendered)

        try:
            registry = filter_tool_registry(self.agent.registry, skill.allowed_tools)
        except SkillDependencyError as e:
            return f"[skill '{skill.name}' 无法执行：{e}]"

        fork_agent = Agent(
            self.client,
            registry,
            protocol=self.protocol,
            work_dir=self.agent.work_dir,
            max_iterations=self.agent.max_iterations,
            context_window=self.agent.context_window,
        )

        parts: list[str] = []
        async for event in fork_agent.run(fork_conv):
            if isinstance(event, StreamText):
                parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                parts.append(f"[error: {event.message}]")
            elif isinstance(event, LoopComplete):
                break
        return "".join(parts)

    @staticmethod
    def _build_fork_context(context: str, source, fork_conv: ConversationManager) -> None:
        """按 context 三档把主对话历史装进 fork 会话。"""
        if context == "none" or source is None:
            return
        msgs = [
            m for m in source.history
            if m.role in ("user", "assistant") and m.content
        ]
        if context == "recent":
            for m in msgs[-5:]:
                if m.role == "user":
                    fork_conv.add_user_message(m.content)
                else:
                    fork_conv.add_assistant_message(m.content)
        elif context == "full" and msgs:
            summary = "## Previous conversation summary\n\n" + "\n".join(
                f"{m.role}: {m.content}" for m in msgs
            )
            fork_conv.add_user_message(summary)
