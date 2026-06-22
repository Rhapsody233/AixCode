"""/do —— 退出计划模式（LOCAL_UI）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType


async def handle_do(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(False)
    ctx.ui.add_system_message("已退出计划模式。")
    if ctx.args:
        await ctx.ui.send_user_message(ctx.args)


DO_COMMAND = Command(
    name="do",
    description="退出计划模式，回到可执行模式",
    handler=handle_do,
    type=CommandType.LOCAL_UI,
    usage="/do [要执行的任务]",
)
