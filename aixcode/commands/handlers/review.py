"""/review —— 把代码审查 prompt 投回 Agent（PROMPT）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType

REVIEW_PROMPT = (
    "请审查当前改动，按以下四个方面给出问题与改进建议：\n"
    "1. 逻辑错误：边界条件、空值、异常路径、并发竞态。\n"
    "2. 安全问题：注入、越权、敏感信息泄露、不安全的默认值。\n"
    "3. 性能问题：不必要的循环 / 拷贝 / 重复计算、可优化的 I-O。\n"
    "4. 代码风格：命名、重复、与既有约定不一致之处。"
)


async def handle_review(ctx: CommandContext) -> None:
    text = REVIEW_PROMPT
    if ctx.args:
        text += "\n\n额外关注：" + ctx.args
    await ctx.ui.send_user_message(text)


REVIEW_COMMAND = Command(
    name="review",
    description="对当前改动做逻辑 / 安全 / 性能 / 风格审查",
    handler=handle_review,
    type=CommandType.PROMPT,
    usage="/review [额外关注点]",
)
