"""SubAgent worktree 隔离的上下文 notice 与命名。"""

from __future__ import annotations

import secrets

WORKTREE_NOTICE_TEMPLATE = """[WORKTREE CONTEXT]
You are running in an isolated Git Worktree at:
  {wt_path}

The parent session's working directory is:
  {parent_cwd}

All your file operations happen inside the worktree. If the user or the task
refers to paths under the parent directory, translate them to your local worktree path.
Always re-read files before editing — the worktree is a separate checkout and its
contents may differ from the parent.
[/WORKTREE CONTEXT]"""


def generate_worktree_name() -> str:
    """生成自动子 Agent worktree 名：agent- + 8 hex。"""
    return f"agent-{secrets.token_hex(4)}"


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """把两路径注入 notice 模板。"""
    return WORKTREE_NOTICE_TEMPLATE.format(parent_cwd=parent_cwd, wt_path=wt_path)
