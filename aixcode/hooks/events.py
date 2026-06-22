"""生命周期事件常量。"""

from __future__ import annotations

from enum import Enum


class LifecycleEvent(str, Enum):
    """Agent 主流程可挂钩子的 15 个生命周期事件（值可直接与字符串比较）。"""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_SEND = "pre_send"
    POST_RECEIVE = "post_receive"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    COMPACT = "compact"
    PERMISSION_REQUEST = "permission_request"
    FILE_CHANGE = "file_change"
    COMMAND_EXECUTE = "command_execute"
