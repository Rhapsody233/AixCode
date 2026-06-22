"""worktree 变更检测，fail-closed：git 失败一律按"有变更"处理，绝不误删用户工作。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

# 关终端密码提示，绝不挂起等输入
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


@dataclass
class Changes:
    """worktree 变更计数。"""

    uncommitted: int
    new_commits: int


@dataclass
class CleanupResult:
    """Agent 级自动清理返回值。"""

    kept: bool
    path: str | None = None
    branch: str | None = None


def count_worktree_changes(path: str, head_commit: str) -> Changes:
    """统计未提交改动 + 相对 head_commit 的新提交；git 失败对应计数置 1（fail-closed）。"""
    try:
        result = _run_git(["status", "--porcelain"], path)
        uncommitted = len([ln for ln in result.stdout.splitlines() if ln.strip()])
    except (subprocess.SubprocessError, OSError, ValueError):
        uncommitted = 1
    try:
        result = _run_git(["rev-list", "--count", f"{head_commit}..HEAD"], path)
        new_commits = int(result.stdout.strip() or "0")
    except (subprocess.SubprocessError, OSError, ValueError):
        new_commits = 1
    return Changes(uncommitted=uncommitted, new_commits=new_commits)


def has_worktree_changes(path: str, head_commit: str) -> bool:
    """任一计数 > 0 即有变更。"""
    ch = count_worktree_changes(path, head_commit)
    return ch.uncommitted > 0 or ch.new_commits > 0


def describe_changes(ch: Changes) -> str:
    """把变更计数描述成单复数正确的人类可读串（给 LLM 判断是否强删）。"""
    parts = []
    if ch.uncommitted > 0:
        s = "" if ch.uncommitted == 1 else "s"
        parts.append(f"{ch.uncommitted} uncommitted file{s}")
    if ch.new_commits > 0:
        s = "" if ch.new_commits == 1 else "s"
        parts.append(f"{ch.new_commits} commit{s}")
    return " and ".join(parts)


def has_unpushed_commits(path: str) -> bool:
    """是否有未推送到任何 remote 的提交；git 失败返 True（fail-closed）。"""
    try:
        result = _run_git(
            ["rev-list", "--max-count=1", "HEAD", "--not", "--remotes"], path
        )
    except (subprocess.SubprocessError, OSError, ValueError):
        return True
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())
