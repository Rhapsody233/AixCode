"""记忆系统：项目指令 + 会话存档 + 自动记忆。"""

from aixcode.memory.auto_memory import MemoryManager
from aixcode.memory.instructions import load_instructions, process_includes
from aixcode.memory.session import (
    ResumeResult,
    Session,
    SessionManager,
    SessionMeta,
    SessionRecord,
    build_time_gap_message,
    records_to_messages,
    validate_message_chain,
)

__all__ = [
    "MemoryManager",
    "load_instructions",
    "process_includes",
    "ResumeResult",
    "Session",
    "SessionManager",
    "SessionMeta",
    "SessionRecord",
    "build_time_gap_message",
    "records_to_messages",
    "validate_message_chain",
]
