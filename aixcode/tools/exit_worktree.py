"""ExitWorktree 工具：让 LLM 离开当前 worktree（保留或删除，带变更保护）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult
from aixcode.worktree.changes import count_worktree_changes, describe_changes
from aixcode.worktree.manager import WorktreeError

_NO_SESSION = (
    "No-op: there is no active EnterWorktree session to exit. This tool only "
    "operates on worktrees created by EnterWorktree in the current session — it "
    "will not touch worktrees created manually or in a previous session. No "
    "filesystem changes were made."
)


class ExitWorktreeParams(BaseModel):
    """ExitWorktree 参数。"""

    action: str = Field(description="keep（保留 worktree）或 remove（删除 worktree）")
    discard_changes: bool | None = Field(
        default=None, description="remove 时若有未保存变更，需显式 True 才丢弃强删"
    )


class ExitWorktreeTool(Tool):
    """离开当前会话的 worktree；remove 时有未保存变更默认拒绝（需 discard）。"""

    name = "ExitWorktree"
    description = (
        "离开 EnterWorktree 创建的当前 worktree。action=keep 保留，action=remove 删除。"
        "remove 时若有未提交改动或未推送提交会被拒绝，除非 discard_changes=true。"
    )
    params_model = ExitWorktreeParams
    category = "command"
    is_concurrency_safe = False
    should_defer = False

    def __init__(self, worktree_manager) -> None:
        self.worktree_manager = worktree_manager

    async def execute(self, params: ExitWorktreeParams) -> ToolResult:
        manager = self.worktree_manager
        session = manager.get_current_session()
        if session is None:
            return ToolResult(_NO_SESSION, is_error=True)
        if params.action not in ("keep", "remove"):
            return ToolResult(
                f"Invalid action {params.action!r}; expected 'keep' or 'remove'.",
                is_error=True,
            )

        discard = bool(params.discard_changes)
        name = session.worktree_name
        wt = manager.active.get(name)
        wt_path = wt.path if wt else session.worktree_path

        if params.action == "remove" and not discard:
            head = wt.head_commit if wt else "HEAD"
            ch = count_worktree_changes(wt_path, head)
            if ch.uncommitted > 0 or ch.new_commits > 0:
                return ToolResult(
                    f"Refusing to remove worktree '{name}': it has "
                    f"{describe_changes(ch)}. Pass discard_changes=true to force, "
                    "or commit/push your work first.",
                    is_error=True,
                )

        try:
            await manager.exit(name, params.action, discard_changes=discard)
        except WorktreeError as e:
            return ToolResult(str(e), is_error=True)

        if params.action == "keep":
            return ToolResult(
                f"Your work is preserved at {wt_path}. Session is now back in "
                f"{session.original_cwd}."
            )
        return ToolResult(
            f"Exited and removed worktree at {wt_path}. Session is now back in "
            f"{session.original_cwd}."
        )
