"""EnterWorktree 工具：让 LLM 自主创建并进入一个隔离 worktree。"""

from __future__ import annotations

import secrets

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult
from aixcode.worktree.slug import validate_slug


class EnterWorktreeParams(BaseModel):
    """EnterWorktree 参数。"""

    name: str | None = Field(
        default=None,
        description="worktree 名（可选，省略则自动生成 wt-<hex>）；支持 / 嵌套",
    )


class EnterWorktreeTool(Tool):
    """创建并进入一个上下文隔离的 git worktree（会话级）。"""

    name = "EnterWorktree"
    description = (
        "创建并进入一个隔离的 git worktree（独立 working tree + 独立分支，共享 .git）。"
        "进入后本会话的文件操作都发生在 worktree 里，用 ExitWorktree 离开。"
    )
    params_model = EnterWorktreeParams
    category = "command"
    is_concurrency_safe = False
    should_defer = False

    def __init__(self, worktree_manager) -> None:
        self.worktree_manager = worktree_manager

    async def execute(self, params: EnterWorktreeParams) -> ToolResult:
        manager = self.worktree_manager
        if manager.get_current_session() is not None:
            return ToolResult("Already in a worktree session", is_error=True)
        slug = params.name or f"wt-{secrets.token_hex(4)}"
        err = validate_slug(slug)
        if err is not None:
            return ToolResult(f"Invalid worktree name: {err}", is_error=True)
        wt = await manager.create(slug)
        session = await manager.enter(slug)
        return ToolResult(
            f"Created worktree at {session.worktree_path} on branch {wt.branch}. "
            "The session is now working in the worktree. Use ExitWorktree to leave "
            "mid-session, or exit the session to be prompted."
        )
