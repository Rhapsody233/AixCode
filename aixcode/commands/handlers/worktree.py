"""/worktree —— 手动管理 worktree（LOCAL）：create/list/enter/exit/status。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType
from aixcode.worktree.manager import WorktreeError

_USAGE = "用法：/worktree <create|list|enter|exit|status> [name] [--remove] [--discard]"


def create_worktree_command(manager) -> Command:
    """闭包捕获 WorktreeManager，返回 /worktree 命令。"""

    async def handle(ctx: CommandContext) -> None:
        sub, _, rest = ctx.args.strip().partition(" ")
        rest = rest.strip()
        sub = sub.lower()
        if sub in ("", "list"):
            await _handle_list(ctx, manager)
        elif sub == "create":
            await _handle_create(ctx, manager, rest)
        elif sub == "enter":
            await _handle_enter(ctx, manager, rest)
        elif sub == "exit":
            await _handle_exit(ctx, manager, rest)
        elif sub == "status":
            await _handle_status(ctx, manager)
        else:
            ctx.ui.add_system_message(f"未知子命令: {sub}\n{_USAGE}")

    return Command(
        name="worktree",
        description="管理 git worktree（create/list/enter/exit/status）",
        handler=handle,
        type=CommandType.LOCAL,
        aliases=["wt"],
        usage=_USAGE,
    )


async def _handle_create(ctx: CommandContext, manager, name: str) -> None:
    if not name:
        ctx.ui.add_system_message("用法：/worktree create <name>")
        return
    try:
        wt = await manager.create(name)
        session = await manager.enter(name)
    except WorktreeError as e:
        ctx.ui.add_system_message(f"创建 worktree 失败：{e}")
        return
    ctx.agent.work_dir = session.worktree_path
    ctx.ui.add_system_message(
        f"已创建并进入 worktree：{wt.path}（分支 {wt.branch}）"
    )


async def _handle_enter(ctx: CommandContext, manager, name: str) -> None:
    if not name:
        ctx.ui.add_system_message("用法：/worktree enter <name>")
        return
    try:
        await manager.create(name)
        session = await manager.enter(name)
    except WorktreeError as e:
        ctx.ui.add_system_message(f"进入 worktree 失败：{e}")
        return
    ctx.agent.work_dir = session.worktree_path
    ctx.ui.add_system_message(f"已进入 worktree：{session.worktree_path}")


async def _handle_exit(ctx: CommandContext, manager, rest: str) -> None:
    session = manager.get_current_session()
    if session is None:
        ctx.ui.add_system_message("当前没有活跃的 worktree 会话。")
        return
    tokens = rest.split()
    action = "remove" if "--remove" in tokens else "keep"
    discard = "--discard" in tokens
    try:
        await manager.exit(session.worktree_name, action, discard_changes=discard)
    except WorktreeError as e:
        ctx.ui.add_system_message(str(e))
        return
    ctx.agent.work_dir = session.original_cwd
    verb = "已删除并退出" if action == "remove" else "已保留并退出"
    ctx.ui.add_system_message(f"{verb} worktree，已切回 {session.original_cwd}")


async def _handle_list(ctx: CommandContext, manager) -> None:
    worktrees = manager.list_worktrees()
    if not worktrees:
        ctx.ui.add_system_message("当前没有 worktree。")
        return
    session = manager.get_current_session()
    current = session.worktree_name if session else None
    lines = ["worktree 列表："]
    for wt in worktrees:
        mark = " ←当前" if wt.name == current else ""
        lines.append(f"- {wt.name}｜{wt.branch}｜{wt.path}{mark}")
    ctx.ui.add_system_message("\n".join(lines))


async def _handle_status(ctx: CommandContext, manager) -> None:
    session = manager.get_current_session()
    if session is None:
        ctx.ui.add_system_message("当前不在任何 worktree 会话中。")
        return
    ctx.ui.add_system_message(
        f"当前 worktree：{session.worktree_name}\n"
        f"路径：{session.worktree_path}\n"
        f"原始目录：{session.original_cwd}\n"
        f"原始分支：{session.original_branch}"
    )
