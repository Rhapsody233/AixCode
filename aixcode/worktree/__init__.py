"""ch14 Worktree 系统：会话级 / Agent 级 worktree 隔离。"""

from aixcode.worktree.changes import (
    Changes,
    CleanupResult,
    count_worktree_changes,
    has_worktree_changes,
)
from aixcode.worktree.cleanup import cleanup_stale_worktrees, start_stale_cleanup_task
from aixcode.worktree.manager import WorktreeError, WorktreeManager
from aixcode.worktree.models import Worktree, WorktreeSession
from aixcode.worktree.session import load_worktree_session, save_worktree_session
from aixcode.worktree.slug import flatten_slug, validate_slug

__all__ = [
    "Changes",
    "CleanupResult",
    "Worktree",
    "WorktreeError",
    "WorktreeManager",
    "WorktreeSession",
    "cleanup_stale_worktrees",
    "count_worktree_changes",
    "flatten_slug",
    "has_worktree_changes",
    "load_worktree_session",
    "save_worktree_session",
    "start_stale_cleanup_task",
    "validate_slug",
]
