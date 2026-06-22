"""同进程后端：以 asyncio.Task 起一个队员协程，轻量、无进程隔离。"""

from __future__ import annotations

import asyncio

from aixcode.conversation import ConversationManager


class InProcessTeammateHandle:
    """包装队员协程的 asyncio.Task，供 TeamManager 跟踪生命周期。"""

    def __init__(self, agent, task: asyncio.Task, name: str) -> None:
        self.agent = agent
        self.task = task
        self.name = name

    @property
    def done(self) -> bool:
        return self.task.done()

    @property
    def result(self):
        """已完成且无异常/未取消时返回结果，否则 None。"""
        if not self.task.done() or self.task.cancelled():
            return None
        if self.task.exception() is not None:
            return None
        return self.task.result()

    def cancel(self) -> None:
        if not self.task.done():
            self.task.cancel()


def spawn_inprocess_teammate(
    agent, prompt: str, name: str, conversation: ConversationManager | None = None
) -> InProcessTeammateHandle:
    """起一个同进程队员协程；懒导入 run_to_completion 避免循环依赖。"""
    from aixcode.tools.agent_tool import run_to_completion

    if conversation is None:
        conversation = ConversationManager()
        conversation.add_user_message(prompt)
    task = asyncio.create_task(
        run_to_completion(agent, conversation), name=f"teammate-{name}"
    )
    return InProcessTeammateHandle(agent, task, name)
