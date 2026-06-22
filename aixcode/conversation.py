"""会话历史：消息模型 + 多轮历史管理 + 序列化为后端请求体。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """一条对话消息。

    assistant 消息可带 tool_calls；tool 角色消息带 tool_call_id。
    """

    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class ConversationManager:
    """本会话的多轮历史。纯内存，不持久化、不裁剪。"""

    history: list[Message] = field(default_factory=list)
    env_injected: bool = False
    ltm_injected: bool = False
    last_input_tokens: int = 0

    def add_user_message(self, content: str) -> None:
        self.history.append(Message(role="user", content=content))

    def replace_history(self, messages: list[Message]) -> None:
        """就地替换历史（压缩/恢复用）；重置注入标记以便下次重新注入。"""
        self.history[:] = messages
        self.env_injected = False
        self.ltm_injected = False

    def inject_long_term_memory(self, instructions: str, memories: str) -> None:
        """把项目指令与自动记忆作为独立消息插到对话开头（env 之后）；幂等。"""
        if self.ltm_injected:
            return
        pos = 1 if self.env_injected else 0
        injected = False
        if instructions:
            self.history.insert(pos, Message(role="user", content=f"## 项目指令\n{instructions}"))
            pos += 1
            injected = True
        if memories:
            self.history.insert(pos, Message(role="user", content=f"## 自动记忆\n{memories}"))
            pos += 1
            injected = True
        if injected:
            self.history.insert(
                pos, Message(role="assistant", content="好的，我已了解项目背景和记忆。")
            )
            self.ltm_injected = True

    def inject_environment(self, context: str) -> None:
        """把环境上下文作为对话最前的补充消息头插；幂等（重复调用忽略）。"""
        if self.env_injected:
            return
        self.history.insert(0, Message(role="user", content=context))
        self.env_injected = True

    def add_system_reminder(self, content: str) -> None:
        """追加一条 <system-reminder> 标签包裹的 user 消息（运行时补充指令）。"""
        wrapped = f"<system-reminder>\n{content}\n</system-reminder>"
        self.history.append(Message(role="user", content=wrapped))

    def add_assistant_message(
        self, content: str, tool_calls: list[dict[str, Any]] | None = None
    ) -> None:
        self.history.append(
            Message(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.history.append(
            Message(role="tool", content=content, tool_call_id=tool_call_id)
        )

    def get_messages(self) -> list[Message]:
        """返回历史的浅拷贝。"""
        return list(self.history)

    def serialize(self) -> list[dict[str, Any]]:
        """转为 chat-completions 请求体，不丢历史。"""
        out: list[dict[str, Any]] = []
        for m in self.history:
            if m.role == "tool":
                out.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
                )
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {"role": "assistant", "content": m.content, "tool_calls": m.tool_calls}
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out
