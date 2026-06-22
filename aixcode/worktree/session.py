"""worktree 会话持久化：序列化 WorktreeSession 到 JSON，容忍各种损坏。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from aixcode.worktree.models import WorktreeSession

log = logging.getLogger(__name__)

SESSION_FILENAME = "worktree_session.json"


def _session_path(aixcode_dir: str) -> Path:
    return Path(aixcode_dir) / SESSION_FILENAME


def save_worktree_session(aixcode_dir: str, session: WorktreeSession | None) -> None:
    """dump 7 字段到 JSON；session is None 时写 '{}' 等价清空。"""
    path = _session_path(aixcode_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if session is None:
        path.write_text("{}", encoding="utf-8")
        return
    path.write_text(
        json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_worktree_session(aixcode_dir: str) -> WorktreeSession | None:
    """文件缺失 / JSON 损坏 / 空 dict / 缺 worktree_path 全返 None。"""
    path = _session_path(aixcode_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("worktree session 解析失败：%s", e)
        return None
    if not isinstance(data, dict) or not data.get("worktree_path"):
        return None
    try:
        return WorktreeSession(
            original_cwd=data["original_cwd"],
            worktree_path=data["worktree_path"],
            worktree_name=data["worktree_name"],
            original_branch=data["original_branch"],
            original_head_commit=data["original_head_commit"],
            session_id=data.get("session_id", ""),
            hook_based=data.get("hook_based", False),
        )
    except KeyError as e:
        log.warning("worktree session 缺字段：%s", e)
        return None
