"""权限系统：危险命令检测 + 路径沙箱 + 规则引擎 + 权限模式。"""

from aixcode.permissions.checker import Decision, PermissionChecker
from aixcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from aixcode.permissions.modes import (
    DecisionEffect,
    PermissionMode,
    mode_decide,
)
from aixcode.permissions.rules import Rule, RuleEngine, extract_content, parse_rule
from aixcode.permissions.sandbox import PathSandbox

__all__ = [
    "Decision",
    "DecisionEffect",
    "DangerousCommandDetector",
    "is_safe_command",
    "PathSandbox",
    "PermissionChecker",
    "PermissionMode",
    "Rule",
    "RuleEngine",
    "extract_content",
    "mode_decide",
    "parse_rule",
]
