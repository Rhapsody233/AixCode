"""/skill —— 管理子命令：list / info <name> / reload（LOCAL）。"""

from __future__ import annotations

from aixcode.commands.handlers.skill_register import register_skill_commands
from aixcode.commands.registry import Command, CommandContext, CommandType

_USAGE = "用法：/skill [list | info <name> | reload]"


async def handle_skill(ctx: CommandContext) -> None:
    loader = ctx.config.get("skill_loader")
    if loader is None:
        ctx.ui.add_system_message("Skill 系统未初始化。")
        return

    parts = ctx.args.split()
    sub = parts[0] if parts else "list"

    if sub == "list":
        catalog = loader.get_catalog()
        if not catalog:
            ctx.ui.add_system_message("（当前没有已加载的 Skill）")
            return
        lines = [
            f"  {name:<20} {desc}  [{loader.get_source_label(name)}]"
            for name, desc in catalog
        ]
        ctx.ui.add_system_message("已加载 Skill：\n" + "\n".join(lines))
        return

    if sub == "info":
        if len(parts) < 2:
            ctx.ui.add_system_message("用法：/skill info <name>")
            return
        skill = loader.get(parts[1])
        if skill is None:
            ctx.ui.add_system_message(f"未找到 skill：{parts[1]}")
            return
        ctx.ui.add_system_message(
            f"Skill: {skill.name}\n"
            f"  description : {skill.description}\n"
            f"  mode        : {skill.mode}\n"
            f"  context     : {skill.context}\n"
            f"  model       : {skill.model or '(默认)'}\n"
            f"  allowedTools: {', '.join(skill.allowed_tools) or '(全部)'}\n"
            f"  source      : {loader.get_source_label(skill.name)}\n"
            f"  directory   : {skill.is_directory}\n"
            f"  path        : {skill.source_path}"
        )
        return

    if sub == "reload":
        loader.reload()
        executor = ctx.config.get("skill_executor")
        registry = ctx.config.get("registry")
        if executor is not None and registry is not None:
            register_skill_commands(registry, loader, executor)
        ctx.ui.add_system_message("Skill 已重新扫描并注册。")
        return

    ctx.ui.add_system_message(_USAGE)


SKILL_COMMAND = Command(
    name="skill",
    description="管理 Skill（list / info <name> / reload）",
    handler=handle_skill,
    type=CommandType.LOCAL,
    usage=_USAGE,
)
