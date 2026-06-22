"""/status —— 打印当前会话状态（LOCAL）。"""

from __future__ import annotations

import os

from aixcode.commands.registry import Command, CommandContext, CommandType

_NO_MEMORY = "当前没有任何自动记忆。"


async def handle_status(ctx: CommandContext) -> None:
    agent = ctx.agent
    lines = [f"模式：{agent.permission_mode.value}"]

    meta = ctx.session.meta if ctx.session is not None else None
    if meta is None:
        lines.append("会话：（无）")
    else:
        lines.append(
            f"会话：{meta.id}｜{meta.title or '(无标题)'}｜{meta.message_count} 条消息"
        )

    lines.append(f"Token：{ctx.conversation.last_input_tokens}")
    lines.append(f"工具：{len(agent.registry.list_tools())} 个")

    mm = ctx.memory_manager
    has_memory = mm is not None and mm.get_display_text() != _NO_MEMORY
    lines.append(f"记忆：{'有' if has_memory else '无'}")

    lines.append(f"工作目录：{os.getcwd()}")
    lines.append(f"版本：{ctx.config.get('version', '')}")
    ctx.ui.add_system_message("\n".join(lines))


STATUS_COMMAND = Command(
    name="status",
    description="查看模式 / 会话 / Token / 工具 / 记忆 / 工作目录 / 版本",
    handler=handle_status,
    type=CommandType.LOCAL,
    aliases=["s"],
)
