"""Headless 单次执行：`python -m aixcode -p` 直接驱动 agent.run，纯文本流到 stdout。

不依赖 rich/prompt_toolkit；权限 ask 一律拒绝（无人应答）；出错返回非零退出码。
"""

from __future__ import annotations

import sys

from aixcode.agent import (
    ErrorEvent,
    LoopComplete,
    PermissionRequest,
    PermissionResponse,
    StreamText,
)
from aixcode.conversation import ConversationManager


async def run_headless(runtime, prompt: str, permission_mode=None) -> int:
    """跑一次 agent 循环：流式打 stdout、ask→DENY、出错非零退出。返回退出码。"""
    conv = ConversationManager()
    conv.add_user_message(prompt)

    had_error = False
    streamed_any = False
    async for ev in runtime.agent.run(conv):
        if isinstance(ev, StreamText):
            sys.stdout.write(ev.text)
            sys.stdout.flush()
            streamed_any = True
        elif isinstance(ev, PermissionRequest):
            ev.future.set_result(PermissionResponse.DENY)
        elif isinstance(ev, ErrorEvent):
            print(ev.message, file=sys.stderr)
            had_error = True
        elif isinstance(ev, LoopComplete):
            # 真实 Agent 里 LoopComplete.text 与流式累计相同：只补换行；
            # 仅当整轮没有任何流式输出时兜底打印最终文本。
            if not streamed_any and ev.text:
                sys.stdout.write(ev.text)
            sys.stdout.write("\n")
            sys.stdout.flush()

    return 1 if had_error else 0
