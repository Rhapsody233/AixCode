"""权限主入口：装配各层后对 (Tool, arguments) 调一次 check 拿回 Decision。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aixcode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from aixcode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from aixcode.permissions.rules import RuleEngine, extract_content
from aixcode.permissions.sandbox import PathSandbox
from aixcode.tools.base import Tool


@dataclass
class Decision:
    effect: DecisionEffect
    reason: str


class PermissionChecker:
    """纵深防御：危险命令 → 安全命令 → BYPASS → 沙箱 → 规则 → 模式矩阵。

    check 无副作用（除规则文件读盘），只读、不改 in-memory 状态（N4）。
    """

    def __init__(
        self,
        detector: DangerousCommandDetector,
        sandbox: PathSandbox,
        rule_engine: RuleEngine,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.rule_engine = rule_engine
        self.mode = mode

    def check(self, tool: Tool, arguments: dict[str, Any]) -> Decision:
        content = extract_content(tool.name, arguments)

        # ① 命令类：危险命令不可绕过；再查安全白名单
        if tool.category == "command":
            hit, reason = self.detector.detect(content)
            if hit:
                return Decision("deny", f"危险命令拦截：{reason}")
            if is_safe_command(content):
                return Decision("allow", "已知安全只读命令")

        # ② BYPASS：跳过沙箱/规则/矩阵，直接放行（危险命令已在上面拦下）
        if self.mode == PermissionMode.BYPASS:
            return Decision("allow", "bypass 模式")

        # ③ 读/写类的路径沙箱
        if tool.category in ("read", "write") and content:
            ok, reason = self.sandbox.check(content)
            if not ok:
                return Decision("deny", reason)

        # ④ 规则引擎
        effect = self.rule_engine.evaluate(tool.name, content)
        if effect is not None:
            return Decision(effect, f"规则命中：{tool.name}({content})")

        # ⑤ 模式矩阵兜底
        return Decision(
            mode_decide(self.mode, tool.category),
            f"{self.mode.value} 模式默认（{tool.category}）",
        )
