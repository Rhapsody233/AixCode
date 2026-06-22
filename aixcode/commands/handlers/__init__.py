"""内置 slash 命令 handler 集合 + 聚合注册入口。"""

from __future__ import annotations

from aixcode.commands.handlers.clear import CLEAR_COMMAND
from aixcode.commands.handlers.compact import COMPACT_COMMAND
from aixcode.commands.handlers.do import DO_COMMAND
from aixcode.commands.handlers.help import HELP_COMMAND
from aixcode.commands.handlers.memory import MEMORY_COMMAND
from aixcode.commands.handlers.mode import MODE_COMMAND
from aixcode.commands.handlers.plan import PLAN_COMMAND
from aixcode.commands.handlers.review import REVIEW_COMMAND
from aixcode.commands.handlers.session import SESSION_COMMAND
from aixcode.commands.handlers.skill import SKILL_COMMAND
from aixcode.commands.handlers.status import STATUS_COMMAND
from aixcode.commands.handlers.tasks import TASKS_COMMAND
from aixcode.commands.handlers.trace import TRACE_COMMAND
from aixcode.commands.registry import CommandRegistry

ALL_COMMANDS = [
    HELP_COMMAND,
    CLEAR_COMMAND,
    STATUS_COMMAND,
    COMPACT_COMMAND,
    PLAN_COMMAND,
    DO_COMMAND,
    MODE_COMMAND,
    SESSION_COMMAND,
    MEMORY_COMMAND,
    REVIEW_COMMAND,
    SKILL_COMMAND,
    TASKS_COMMAND,
    TRACE_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    """把内置命令逐个注册进 registry（冲突即抛 ValueError）。"""
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)


__all__ = ["ALL_COMMANDS", "register_all_commands"]
