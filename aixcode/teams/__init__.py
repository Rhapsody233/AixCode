"""AgentTeam 系统：网状协作团队的数据结构与服务（ch15）。"""

from __future__ import annotations

from aixcode.teams.backend_detect import BackendDetectionError, detect_backend
from aixcode.teams.mailbox import Mailbox, MailboxMessage, create_message
from aixcode.teams.manager import TeamError, TeamManager
from aixcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from aixcode.teams.registry import AgentNameRegistry
from aixcode.teams.shared_task import SharedTask, SharedTaskStore

__all__ = [
    "AgentTeam",
    "AgentNameRegistry",
    "BackendDetectionError",
    "BackendType",
    "Mailbox",
    "MailboxMessage",
    "SharedTask",
    "SharedTaskStore",
    "TeamError",
    "TeamManager",
    "TeammateInfo",
    "create_message",
    "detect_backend",
    "resolve_team_dir",
    "unique_team_name",
]
