"""/mode —— 切换权限档位（LOCAL_UI）。

parse_mode_name 是此命令的权威纯逻辑实现，供 app 复用。
"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType
from aixcode.permissions import PermissionMode

# /mode 可切到的四档（plan 走 /plan·/do，不在此列）
_MODE_NAMES = {
    "strict": PermissionMode.STRICT,
    "default": PermissionMode.DEFAULT,
    "accept": PermissionMode.ACCEPT_EDITS,
    "bypass": PermissionMode.BYPASS,
}

_USAGE = "用法：/mode <strict|default|accept|bypass>"


def parse_mode_name(name: str) -> PermissionMode | None:
    """把 /mode 后的名字解析成 PermissionMode；未识别返回 None。"""
    return _MODE_NAMES.get(name.strip().lower())


async def handle_mode(ctx: CommandContext) -> None:
    name, _, rest = ctx.args.partition(" ")
    mode = parse_mode_name(name)
    if mode is None:
        ctx.ui.add_system_message(_USAGE)
        return
    ctx.agent.set_permission_mode(mode)
    ctx.ui.add_system_message(f"已切换权限模式：{mode.value}")
    rest = rest.strip()
    if rest:
        await ctx.ui.send_user_message(rest)


MODE_COMMAND = Command(
    name="mode",
    description="切换权限档位（strict/default/accept/bypass）",
    handler=handle_mode,
    type=CommandType.LOCAL_UI,
    usage=_USAGE,
)
