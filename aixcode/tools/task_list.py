"""TaskList：列出团队共享任务，可按 status / assignee 过滤。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult


class TaskListParams(BaseModel):
    status: str = Field("", description="按状态过滤：pending/in_progress/completed/blocked")
    assignee: str = Field("", description="按指派人过滤")


class TaskListTool(Tool):
    name = "TaskList"
    description = "列出团队共享任务清单（可按 status / assignee 过滤）。"
    params_model = TaskListParams
    category = "read"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: TaskListParams) -> ToolResult:
        team_name = getattr(self.parent_agent, "team_name", "")
        if not team_name:
            return ToolResult("当前没有活跃团队，请先用 TeamCreate 创建团队。", is_error=True)
        store = self.team_manager.get_task_store(team_name)
        if store is None:
            return ToolResult(f"找不到团队 {team_name!r} 的任务清单。", is_error=True)
        tasks = store.list_tasks(
            status=params.status or None, assignee=params.assignee or None
        )
        if not tasks:
            return ToolResult("（任务清单为空或无匹配项）")
        lines = [
            f"#{t.id} [{t.status}] {t.title}"
            + (f" -> {t.assignee}" if t.assignee else "")
            for t in tasks
        ]
        return ToolResult("\n".join(lines))
