"""/help —— 列全部命令或单命令用法（LOCAL）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType


async def handle_help(ctx: CommandContext) -> None:
    registry = ctx.config["registry"]
    arg = ctx.args.strip()
    if not arg:
        lines: list[str] = []
        for cmd in sorted(registry.list_commands(), key=lambda c: c.name):
            if cmd.hidden:
                continue
            alias = (
                "  [" + ", ".join("/" + a for a in cmd.aliases) + "]"
                if cmd.aliases
                else ""
            )
            lines.append(f"/{cmd.name}{alias} — {cmd.description}")
        ctx.ui.add_system_message("\n".join(lines))
        return
    cmd = registry.find(arg.lstrip("/"))
    if cmd is None:
        ctx.ui.add_system_message(f"未知命令：{arg}")
        return
    usage = cmd.usage or f"/{cmd.name}"
    ctx.ui.add_system_message(f"/{cmd.name} — {cmd.description}\n用法：{usage}")


HELP_COMMAND = Command(
    name="help",
    description="列出全部命令或查看单个命令用法",
    handler=handle_help,
    type=CommandType.LOCAL,
    aliases=["h", "?"],
    usage="/help [命令名]",
)
