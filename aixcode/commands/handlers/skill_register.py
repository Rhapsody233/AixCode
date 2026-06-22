"""把每个已加载 Skill 注册成 /<name> 短命令（skill 覆盖同名内置命令）。"""

from __future__ import annotations

import asyncio

from aixcode.commands.registry import Command, CommandContext, CommandRegistry, CommandType

# 跟踪本会话已注册的 skill 命令名，重复调用先清旧再注册
_REGISTERED_SKILL_NAMES: set[str] = set()


def _make_handler(skill_name: str, loader, executor):
    async def handler(ctx: CommandContext) -> None:
        skill = loader.get(skill_name)  # 每次执行重读，支持热重载
        if skill is None:
            ctx.ui.add_system_message(f"未找到 skill：{skill_name}")
            return
        if skill.mode == "fork":
            ctx.ui.add_system_message(f"正在后台运行 skill /{skill.name}（fork）…")

            async def _run_fork():
                result = await executor.execute_fork(skill, ctx.args, ctx.conversation)
                ctx.ui.add_system_message(f"[{skill.name} skill 结果]\n{result}")

            asyncio.create_task(_run_fork())
        else:
            await executor.execute_inline(skill, ctx.args)
            await ctx.ui.send_user_message(ctx.args or f"开始执行 {skill.name}。")

    return handler


def register_skill_commands(
    registry: CommandRegistry, loader, executor
) -> None:
    """把所有 skill 注册成 /<name>；重复调用先清旧的，并覆盖同名内置命令。"""
    global _REGISTERED_SKILL_NAMES
    for name in _REGISTERED_SKILL_NAMES:
        registry.unregister(name)
    _REGISTERED_SKILL_NAMES = set()

    for name, description in loader.get_catalog():
        skill = loader.get(name)
        if skill is None:
            continue
        registry.unregister(name)  # skill 覆盖同名内置命令（如 /review）
        registry.register_sync(
            Command(
                name=name,
                description=f"{description} [skill]",
                handler=_make_handler(name, loader, executor),
                type=CommandType.LOCAL_UI,
            )
        )
        _REGISTERED_SKILL_NAMES.add(name)
