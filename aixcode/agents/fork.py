"""Fork：把当前对话深拷贝成一个临时子 Agent 的独立会话。"""

from __future__ import annotations

import copy

from aixcode.conversation import ConversationManager

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = f"""{FORK_BOILERPLATE_TAG}
你是从主 Agent fork 出来的临时子 Agent，继承了上面的完整对话上下文。强制规则：

- 你**不能再 fork**，也不能调用 Agent 工具开新子 Agent。
- 不要主动与用户对话、不要请求确认；直接用工具动手完成任务。
- 聚焦下面的任务，完成后给出**控字数、结构化**的最终报告。
{FORK_BOILERPLATE_TAG}"""


class ForkError(Exception):
    """从一个已 fork 的对话再次 fork（嵌套）。"""


def build_forked_messages(conversation, task: str) -> ConversationManager:
    """深拷贝父对话历史成新会话，补 interrupted 占位，末尾追加 fork 任务。"""
    for msg in conversation.history:
        if msg.content and FORK_BOILERPLATE_TAG in msg.content:
            raise ForkError("Cannot fork from a forked agent.")

    forked = ConversationManager()
    forked.history = copy.deepcopy(conversation.history)

    # 带 tool_calls 但缺对应 tool 结果的 assistant 消息：补 interrupted 占位
    answered = {m.tool_call_id for m in forked.history if m.role == "tool"}
    for msg in list(forked.history):
        if msg.role == "assistant" and msg.tool_calls:
            for call in msg.tool_calls:
                call_id = call.get("id")
                if call_id and call_id not in answered:
                    forked.add_tool_result(call_id, "interrupted")
                    answered.add(call_id)

    forked.add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")
    return forked
