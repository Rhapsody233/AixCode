"""worktree 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Worktree:
    """一个活跃 worktree 的注册项。"""

    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime = field(default_factory=datetime.now)


@dataclass
class WorktreeSession:
    """会话级 worktree 单例，序列化到 JSON。"""

    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str = ""
    hook_based: bool = False
