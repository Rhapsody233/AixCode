"""权限模式与「模式 × 工具类别」决策矩阵。"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from aixcode.tools.base import ToolCategory

DecisionEffect = Literal["allow", "deny", "ask"]


class PermissionMode(str, Enum):
    """五档权限模式，覆盖在具体规则之上、整体切换。"""

    STRICT = "strict"
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    BYPASS = "bypass"
    PLAN = "plan"


# 模式 × 类别 → 默认 effect；危险命令检测在矩阵之前，BYPASS 也拦不住。
_MODE_MATRIX: dict[PermissionMode, dict[ToolCategory, DecisionEffect]] = {
    PermissionMode.STRICT: {"read": "ask", "write": "ask", "command": "ask"},
    PermissionMode.DEFAULT: {"read": "allow", "write": "ask", "command": "ask"},
    PermissionMode.ACCEPT_EDITS: {"read": "allow", "write": "allow", "command": "ask"},
    PermissionMode.PLAN: {"read": "allow", "write": "deny", "command": "deny"},
    PermissionMode.BYPASS: {"read": "allow", "write": "allow", "command": "allow"},
}


def mode_decide(mode: PermissionMode, category: ToolCategory) -> DecisionEffect:
    """按模式与工具类别索引决策矩阵。"""
    return _MODE_MATRIX[mode][category]
