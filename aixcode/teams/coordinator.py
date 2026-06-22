"""Coordinator Mode：双开关判定 + 阶段化工作流系统提示（提示词层引导，工具层不强制）。"""

from __future__ import annotations

import os

_COORDINATOR_ENV = "AIXCODE_COORDINATOR_MODE"
_TRUTHY = {"1", "true", "yes"}


def is_coordinator_mode(enable_flag: bool) -> bool:
    """双开关：enable_flag 为假直接 False；为真时再看 AIXCODE_COORDINATOR_MODE env。"""
    if not enable_flag:
        return False
    return os.environ.get(_COORDINATOR_ENV, "").strip().lower() in _TRUTHY


def get_coordinator_system_prompt() -> str:
    """协调模式系统提示：四阶段工作流引导 + anti-pattern。"""
    return """# Coordinator Mode

你现在是团队的协调者（Lead）。你没有代码写权限（WriteFile / EditFile 已被收起），
你的职责是理解、拆解、派发与综合，而不是亲自动手改代码。按以下四阶段推进：

1. Research（调研）：用 ReadFile / Glob / Grep / Bash 摸清问题与代码现状，必要时
   派 Agent 队员并行调查不同方向。
2. Synthesis（综合）：把队员通过 SendMessage 反馈的发现汇总成一份连贯的判断，
   用 TaskCreate / TaskList 维护共享任务清单与依赖关系。
3. Implementation（实施）：把任务通过 Agent 工具分派给队员执行；用 TaskUpdate
   跟踪状态；队员之间用 SendMessage 直接协作。
4. Verification（验证）：队员完成后检查产出，必要时让其继续修正；全部完成后给出
   综合结论。

Anti-pattern：不要对队员说 "based on your findings, do X" 这类把综合责任甩回给
队员的空话——综合是你的工作。给队员的指令必须是具体、自包含、可独立执行的任务。
"""
