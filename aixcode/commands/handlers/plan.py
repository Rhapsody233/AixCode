"""/plan —— 进入计划模式（LOCAL_UI）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType


async def handle_plan(ctx: CommandContext) -> None:
    ctx.ui.set_plan_mode(True)
    ctx.ui.add_system_message("已进入计划模式：只读、产出计划待审批。")
    if ctx.args:
        await ctx.ui.send_user_message(ctx.args)


PLAN_COMMAND = Command(
    name="plan",
    description="进入计划模式（只读、产出计划待审批）",
    handler=handle_plan,
    type=CommandType.LOCAL_UI,
    aliases=["p"],
    usage="/plan [要规划的任务]",
)
