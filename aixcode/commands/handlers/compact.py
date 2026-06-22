"""/compact —— 手动压缩上下文（LOCAL_UI）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType

_THRESHOLD = 5000


async def handle_compact(ctx: CommandContext) -> None:
    tokens = ctx.conversation.last_input_tokens
    if tokens < _THRESHOLD:
        ctx.ui.add_system_message(f"当前 token 数 {tokens}，无需压缩。")
        return
    result = await ctx.agent.manual_compact(ctx.conversation)
    if isinstance(result, str):
        ctx.ui.add_system_message(result)
    else:
        ctx.ui.add_system_message(
            f"上下文已压缩（压缩前 {result.before_tokens} tokens）"
        )


COMPACT_COMMAND = Command(
    name="compact",
    description="手动压缩当前上下文（token 过低则跳过）",
    handler=handle_compact,
    type=CommandType.LOCAL_UI,
    aliases=["c"],
)
