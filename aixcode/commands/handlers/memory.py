"""/memory —— 查看 / 清空 / 编辑自动记忆（LOCAL）。

render_memory 是此命令的权威纯逻辑实现，供 app 复用。
"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType


def render_memory(memory_manager, payload: str) -> str:
    """`/memory` 子命令纯逻辑：返回要打印的文本。"""
    if memory_manager is None:
        return "记忆管理器未初始化。"
    parts = payload.split()
    sub = parts[0] if parts else "list"
    if sub in ("", "list"):
        return memory_manager.get_display_text()
    if sub == "clear":
        memory_manager.clear()
        return "所有自动记忆已清空。"
    if sub == "edit":
        return (
            f"用户级记忆：{memory_manager.user_path}\n"
            f"项目级记忆：{memory_manager.project_path}\n"
            "用任意编辑器打开上面的文件即可手改。"
        )
    return "用法：/memory [list | clear | edit]"


async def handle_memory(ctx: CommandContext) -> None:
    ctx.ui.add_system_message(render_memory(ctx.memory_manager, ctx.args))


MEMORY_COMMAND = Command(
    name="memory",
    description="查看 / 清空 / 编辑自动记忆",
    handler=handle_memory,
    type=CommandType.LOCAL,
    usage="/memory [list | clear | edit]",
)
