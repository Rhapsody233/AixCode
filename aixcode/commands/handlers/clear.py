"""/clear —— 清空对话历史并清屏（LOCAL_UI）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType


async def handle_clear(ctx: CommandContext) -> None:
    # clear_chat 闭包由 app 提供：replace_history([]) + 复位归档游标 + 清屏。
    ctx.config["clear_chat"]()
    # ch11：清对话时一并清掉已激活 skill，避免新对话残留旧 SOP。
    if ctx.agent is not None and hasattr(ctx.agent, "clear_active_skills"):
        ctx.agent.clear_active_skills()
    ctx.ui.add_system_message("已清空对话。")


CLEAR_COMMAND = Command(
    name="clear",
    description="清空对话历史并清屏",
    handler=handle_clear,
    type=CommandType.LOCAL_UI,
    aliases=["cls"],
)
