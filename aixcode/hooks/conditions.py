"""Condition DSL：leaf 操作符（==/!=/=~/~=）+ 复合（&&/||，不混用）。"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from aixcode.hooks.models import HookContext

_OPERATORS = ("==", "!=", "=~", "~=")
_SPLIT_RE = re.compile(r"\s*(==|!=|=~|~=)\s*")


class ConditionParseError(Exception):
    """condition 字符串解析失败。"""


@dataclass
class Condition:
    """叶子条件：field <op> value。"""

    field: str
    operator: str
    value: str

    def evaluate(self, ctx: HookContext) -> bool:
        actual = ctx.get_field(self.field)
        if self.operator == "==":
            return actual == self.value
        if self.operator == "!=":
            return actual != self.value
        if self.operator == "=~":
            pattern = self.value
            if len(pattern) >= 2 and pattern[0] == "/" and pattern[-1] == "/":
                pattern = pattern[1:-1]
            try:
                return re.search(pattern, actual) is not None
            except re.error:
                return False
        if self.operator == "~=":
            return fnmatch.fnmatch(actual, self.value)
        return False


@dataclass
class ConditionGroup:
    """复合条件：conditions + logic（"and"/"or"）。"""

    conditions: list[Condition]
    logic: str

    def evaluate(self, ctx: HookContext) -> bool:
        if not self.conditions:
            return True
        results = [c.evaluate(ctx) for c in self.conditions]
        return all(results) if self.logic == "and" else any(results)


def _parse_single(expr: str) -> Condition:
    parts = _SPLIT_RE.split(expr.strip(), maxsplit=1)
    if len(parts) != 3:
        raise ConditionParseError(
            f"Cannot parse condition {expr!r} (expected 'field <op> value')"
        )
    field_, op, value = parts[0].strip(), parts[1], parts[2].strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return Condition(field_, op, value)


def parse_condition(expr: str | None):
    """解析 condition 字符串成 Condition / ConditionGroup / None。"""
    if expr is None:
        return None
    s = expr.strip()
    if not s:
        return None
    has_and = "&&" in s
    has_or = "||" in s
    if has_and and has_or:
        raise ConditionParseError(
            "Cannot mix '&&' and '||' in a single condition expression"
        )
    if has_and:
        return ConditionGroup([_parse_single(p) for p in s.split("&&")], "and")
    if has_or:
        return ConditionGroup([_parse_single(p) for p in s.split("||")], "or")
    return _parse_single(s)
