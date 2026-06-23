"""把 MCP server 暴露的 prompts 注册成 slash command `/mcp__<server>__<name>`（ch16）。"""

from __future__ import annotations

import logging

from aixcode.commands.registry import Command, CommandContext, CommandType

log = logging.getLogger(__name__)


def _parse_prompt_args(raw: str) -> dict:
    """最简参数解析：空格切分的 `key=value`；无 `=` 的 token 忽略。"""
    out: dict = {}
    for token in raw.split():
        key, sep, value = token.partition("=")
        if sep:
            out[key] = value
    return out


def build_mcp_prompt_command(
    mcp_manager, server: str, name: str, description: str
) -> Command:
    """把一个 MCP prompt 包成 PROMPT 型命令：调用即把 server 返回的提示投回 Agent。"""

    async def handler(ctx: CommandContext) -> None:
        text = await mcp_manager.get_prompt(server, name, _parse_prompt_args(ctx.args))
        await ctx.ui.send_user_message(text)

    return Command(
        name=f"mcp__{server}__{name}",
        description=description or f"MCP prompt: {name}",
        handler=handler,
        type=CommandType.PROMPT,
    )


async def register_mcp_prompts(registry, mcp_manager) -> int:
    """发现所有 MCP prompts 并注册为命令；重名冲突跳过。返回成功注册数。"""
    count = 0
    for server, name, description in await mcp_manager.list_all_prompts():
        cmd = build_mcp_prompt_command(mcp_manager, server, name, description)
        try:
            registry.register_sync(cmd)
            count += 1
        except ValueError:
            log.warning("MCP prompt 命令名冲突，跳过：%s", cmd.name)
    return count
