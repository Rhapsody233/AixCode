"""/session —— info / list / resume / new / delete（LOCAL_UI）。

app 状态变更（关旧会话、替换历史、复位归档游标与 loop 计数）经
config["set_session"](session, messages, last_active) 闭包完成。
"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType

_USAGE = "用法：/session [list | resume <id> | new | delete <id>]"


async def handle_session(ctx: CommandContext) -> None:
    sm = ctx.session_manager
    if sm is None:
        ctx.ui.add_system_message("会话存档未初始化。")
        return
    parts = ctx.args.split()
    sub = parts[0] if parts else ""

    if sub in ("", "info"):
        meta = ctx.session.meta if ctx.session is not None else None
        if meta is None:
            ctx.ui.add_system_message("当前无活跃会话。")
        else:
            ctx.ui.add_system_message(
                f"当前会话 {meta.id}｜{meta.title or '(无标题)'}｜{meta.message_count} 条消息"
            )
        return

    if sub == "list":
        metas = sm.list()[:10]
        if not metas:
            ctx.ui.add_system_message("没有历史会话。")
            return
        lines = [
            f"  {i}. {m.id}｜{m.title or '(无标题)'}｜{m.message_count} 条｜{m.last_active:%Y-%m-%d %H:%M}"
            for i, m in enumerate(metas, 1)
        ]
        ctx.ui.add_system_message("\n".join(lines))
        return

    if sub == "resume":
        if len(parts) < 2:
            ctx.ui.add_system_message("用法：/session resume <id|序号>")
            return
        target = parts[1]
        metas = sm.list()
        if target.isdigit() and 1 <= int(target) <= len(metas):
            target = metas[int(target) - 1].id
        result = sm.resume(target)
        if result is None:
            ctx.ui.add_system_message(f"未找到会话：{target}")
            return
        ctx.config["set_session"](result.session, result.messages, result.last_active)
        ctx.ui.add_system_message(
            f"已恢复会话 {target}（{len(result.messages)} 条消息）。"
        )
        return

    if sub == "new":
        session = sm.create()
        ctx.config["set_session"](session, [], None)
        ctx.ui.add_system_message("已新建会话。")
        return

    if sub == "delete":
        if len(parts) < 2:
            ctx.ui.add_system_message("用法：/session delete <id>")
            return
        ok = sm.delete(parts[1])
        ctx.ui.add_system_message("已删除。" if ok else f"未找到：{parts[1]}")
        return

    ctx.ui.add_system_message(_USAGE)


SESSION_COMMAND = Command(
    name="session",
    description="管理会话存档（list / resume / new / delete）",
    handler=handle_session,
    type=CommandType.LOCAL_UI,
    usage=_USAGE,
)
