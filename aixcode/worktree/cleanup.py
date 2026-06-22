"""孤儿 worktree 后台过期清理：三层 fail-closed 过滤，绝不误删用户工作。"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from aixcode.worktree.changes import has_unpushed_commits, has_worktree_changes
from aixcode.worktree.slug import flatten_slug

log = logging.getLogger(__name__)

# 自动产物命名模式（用户手动起的名永不匹配，因而永不被自动删）
EPHEMERAL_PATTERNS = [
    re.compile(r"^agent-[0-9a-f]{8}$"),
    re.compile(r"^wf_[0-9a-f]{8}-[0-9a-f]{3}-\d+$"),
    re.compile(r"^wf-\d+$"),
    re.compile(r"^bridge-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$"),
    re.compile(r"^job-[a-zA-Z0-9._-]{1,55}-[0-9a-f]{8}$"),
]


def _is_ephemeral(name: str) -> bool:
    return any(p.match(name) for p in EPHEMERAL_PATTERNS)


async def cleanup_stale_worktrees(manager, cutoff_hours: float) -> int:
    """三层过滤后删过期孤儿 worktree，返回清理数。

    L1 命名（用户起名永不删）→ L2 时态（当前 session 占用 / 未过期跳过）
    → L3 git 状态 fail-closed（读不到 HEAD / 有变更 / 有未推送提交都跳过）。
    """
    wt_dir = Path(manager.worktree_dir)
    if not wt_dir.is_dir():
        return 0
    cutoff = time.time() - cutoff_hours * 3600
    current = manager.current_session
    current_name = (
        flatten_slug(current.worktree_name) if current and current.worktree_name else None
    )
    removed = 0
    for info in wt_dir.iterdir():
        if not info.is_dir():
            continue
        name = info.name
        # L1 命名
        if not _is_ephemeral(name):
            continue
        # L2 时态
        if current_name is not None and current_name == name:
            continue
        try:
            if info.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        # L3 git 状态 fail-closed
        sha = manager.read_worktree_head_sha(str(info))
        if sha is None:
            continue
        if has_worktree_changes(str(info), sha):
            continue
        if has_unpushed_commits(str(info)):
            continue
        # 通过：删 worktree + 删分支
        manager._run_git(["worktree", "remove", "--force", str(info)])
        await asyncio.sleep(0.1)  # 等 git lockfile 释放
        manager._run_git(["branch", "-D", f"worktree-{name}"])
        manager.active.pop(name, None)
        removed += 1
    return removed


async def start_stale_cleanup_task(
    manager, interval: float, cutoff_hours: float
) -> None:
    """死循环：每 interval 秒跑一轮过期清理；异常 warning 不抛（不拖垮主程序）。"""
    while True:
        await asyncio.sleep(interval)
        try:
            await cleanup_stale_worktrees(manager, cutoff_hours)
        except Exception as e:  # noqa: BLE001
            log.warning("worktree 过期清理失败：%s", e)
