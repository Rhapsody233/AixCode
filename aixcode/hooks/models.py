"""Hook 数据模型：Action / Hook / HookContext / ActionResult / 异常。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VAR_RE = re.compile(r"\$TOOL_ARGS\.(\w+)|\$(EVENT|TOOL_NAME|FILE_PATH|MESSAGE|ERROR)")


@dataclass
class Action:
    """一个动作；单结构承载 command / prompt / http / agent 四种类型。"""

    type: str
    command: str | None = None
    message: str | None = None
    url: str | None = None
    method: str = "POST"
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    prompt: str | None = None
    timeout: int = 30


@dataclass
class ActionResult:
    """动作执行的统一结果。"""

    output: str
    success: bool


@dataclass
class HookContext:
    """触发钩子时的上下文，供 condition 取值与动作模板展开。"""

    event_name: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    file_path: str | None = None
    message: str | None = None
    error: str | None = None

    def get_field(self, name: str) -> str:
        """供 Condition 取值：tool / event / args.<key>；缺失返回空串。"""
        if name == "tool":
            return self.tool_name or ""
        if name == "event":
            return self.event_name or ""
        if name.startswith("args."):
            return str(self.tool_args.get(name[5:], ""))
        return ""

    def expand(self, template: str) -> str:
        """模板展开：$EVENT/$TOOL_NAME/$FILE_PATH/$MESSAGE/$ERROR/$TOOL_ARGS.<key>。

        未定义变量替换为空串。
        """
        simple = {
            "EVENT": self.event_name or "",
            "TOOL_NAME": self.tool_name or "",
            "FILE_PATH": self.file_path or "",
            "MESSAGE": self.message or "",
            "ERROR": self.error or "",
        }

        def repl(m: re.Match) -> str:
            if m.group(1) is not None:  # $TOOL_ARGS.<key>
                return str(self.tool_args.get(m.group(1), ""))
            return simple[m.group(2)]

        return _VAR_RE.sub(repl, template)


@dataclass
class Hook:
    """一条已解析的钩子规则。"""

    id: str
    event: str
    action: Action
    condition: Any = None  # Condition | ConditionGroup | None
    reject: bool = False
    once: bool = False
    async_exec: bool = False
    executed: bool = False

    def should_run(self) -> bool:
        return not (self.once and self.executed)

    def mark_executed(self) -> None:
        self.executed = True


class ToolRejectedError(Exception):
    """pre_tool_use 钩子拦截工具调用。"""

    def __init__(self, tool: str, reason: str, hook_id: str) -> None:
        super().__init__(f"tool {tool} rejected by hook {hook_id}: {reason}")
        self.tool = tool
        self.reason = reason
        self.hook_id = hook_id
