"""/tasks —— 查看 / 取消后台子 Agent 任务（LOCAL）。"""

from __future__ import annotations

from aixcode.agents.notification import format_task_notification
from aixcode.commands.registry import Command, CommandContext, CommandType

_USAGE = "用法：/tasks list | view <id> | cancel <id>"
_NO_MANAGER = "后台任务管理不可用（task_manager 未装配）。"


def _elapsed(task) -> str:
    if task.end_time is not None and task.start_time:
        return f"{task.end_time - task.start_time:.1f}s"
    return "-"


async def handle_tasks(ctx: CommandContext) -> None:
    tm = ctx.config.get("task_manager")
    if tm is None:
        ctx.ui.add_system_message(_NO_MANAGER)
        return

    sub, _, rest = ctx.args.strip().partition(" ")
    sub = sub.lower()
    rest = rest.strip()

    if sub in ("", "list"):
        tasks = tm.list_tasks()
        if not tasks:
            ctx.ui.add_system_message("当前没有后台任务。")
            return
        lines = ["后台任务："]
        for t in tasks:
            lines.append(
                f"- {t.task_id}｜{t.agent_type}｜{t.status}｜"
                f"in={t.input_tokens} out={t.output_tokens}｜{_elapsed(t)}"
            )
        ctx.ui.add_system_message("\n".join(lines))
        return

    if sub == "view":
        task = tm.get(rest)
        if task is None:
            ctx.ui.add_system_message(f"没有该任务：{rest}")
            return
        ctx.ui.add_system_message(format_task_notification(task))
        return

    if sub == "cancel":
        ok = tm.cancel(rest)
        ctx.ui.add_system_message(
            f"已取消任务 {rest}" if ok else f"无法取消任务 {rest}（不存在或非运行中）"
        )
        return

    ctx.ui.add_system_message(_USAGE)


TASKS_COMMAND = Command(
    name="tasks",
    description="查看 / 取消后台子 Agent 任务（list/view/cancel）",
    handler=handle_tasks,
    type=CommandType.LOCAL,
    usage=_USAGE,
)
