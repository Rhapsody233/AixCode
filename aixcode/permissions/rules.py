"""Layer 3：规则引擎。三层优先级 会话(内存) > 项目(文件) > 用户(文件)。

规则语法 `ToolName(pattern)`，effect ∈ allow/deny；规则文件为 YAML 列表
`[{rule: "...", effect: "..."}, ...]`。解析对所有异常静默降级，单条坏规则
不影响其余（N3）。每次 evaluate 读盘，不做热重载。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Effect = Literal["allow", "deny"]

_RULE_RE = re.compile(r"^(\w+)\((.+)\)$")

# 6 工具 → 主参数字段名。
_CONTENT_FIELDS: dict[str, str] = {
    "Bash": "command",
    "ReadFile": "file_path",
    "WriteFile": "file_path",
    "EditFile": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


@dataclass(frozen=True)
class Rule:
    tool_name: str
    pattern: str
    effect: Effect

    def matches(self, tool_name: str, content: str) -> bool:
        return tool_name == self.tool_name and fnmatch.fnmatch(content, self.pattern)


def parse_rule(raw: str, effect: Effect) -> Rule:
    """解析 `ToolName(pattern)`；非法语法 raise ValueError。"""
    m = _RULE_RE.match(raw.strip())
    if m is None:
        raise ValueError(f"非法规则语法：{raw!r}")
    return Rule(m.group(1), m.group(2), effect)


def extract_content(tool_name: str, arguments: dict[str, Any]) -> str:
    """取工具主参数；未识别工具返回空串。"""
    field = _CONTENT_FIELDS.get(tool_name)
    if field is None:
        return ""
    return str(arguments.get(field, ""))


def _load_rules_file(path: Path) -> list[Rule]:
    """读 YAML 规则列表；缺失/YAML 错/非列表/单条坏规则静默跳过。"""
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, list):
        return []
    rules: list[Rule] = []
    for item in data:
        try:
            rules.append(parse_rule(item["rule"], item["effect"]))
        except (KeyError, TypeError, ValueError):
            continue
    return rules


class RuleEngine:
    """三层规则匹配 + 会话内存规则 + 项目规则文件写入。"""

    def __init__(self, user_rules_path: str, project_rules_path: str) -> None:
        self._user_path = Path(user_rules_path)
        self._project_path = Path(project_rules_path)
        self._session_rules: list[Rule] = []

    def evaluate(self, tool_name: str, content: str) -> Effect | None:
        """按 会话 > 项目 > 用户 顺序，单层 reversed LIFO；命中即返回，否则 None。"""
        layers = [
            self._session_rules,
            _load_rules_file(self._project_path),
            _load_rules_file(self._user_path),
        ]
        for rules in layers:
            for rule in reversed(rules):
                if rule.matches(tool_name, content):
                    return rule.effect
        return None

    def add_session_rule(self, rule: Rule) -> None:
        self._session_rules.append(rule)

    def append_project_rule(self, rule: Rule) -> None:
        """把规则追加到项目规则文件（读现有 → append → 重写）。"""
        self._project_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[Any] = []
        try:
            data = yaml.safe_load(self._project_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data
        except (OSError, yaml.YAMLError):
            existing = []
        existing.append({"rule": f"{rule.tool_name}({rule.pattern})", "effect": rule.effect})
        self._project_path.write_text(
            yaml.dump(existing, allow_unicode=True), encoding="utf-8"
        )
