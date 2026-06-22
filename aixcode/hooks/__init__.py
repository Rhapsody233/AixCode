"""Hook 系统：声明式（YAML）生命周期钩子 + 条件匹配 + 多动作执行。"""

from aixcode.hooks.conditions import (
    Condition,
    ConditionGroup,
    ConditionParseError,
    parse_condition,
)
from aixcode.hooks.engine import HookEngine, HookNotification
from aixcode.hooks.events import LifecycleEvent
from aixcode.hooks.loader import HookConfigError, load_hooks
from aixcode.hooks.models import (
    Action,
    ActionResult,
    Hook,
    HookContext,
    ToolRejectedError,
)

__all__ = [
    "Action",
    "ActionResult",
    "Condition",
    "ConditionGroup",
    "ConditionParseError",
    "Hook",
    "HookConfigError",
    "HookContext",
    "HookEngine",
    "HookNotification",
    "LifecycleEvent",
    "ToolRejectedError",
    "load_hooks",
    "parse_condition",
]
