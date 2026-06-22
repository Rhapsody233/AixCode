"""TaskCreate：在团队共享任务清单里新建一条任务。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult


class TaskCreateParams(BaseModel):
    title: str = Field(..., description="任务标题")
    description: str = ""
    assignee: str = Field("", description="指派给哪个队员（name）")
    blocks: list[int] | None = Field(None, description="本任务阻塞的任务 id 列表")
    blocked_by: list[int] | None = Field(None, description="阻塞本任务的任务 id 列表")


class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = "在团队共享任务清单里新建一条任务（需先建团队）。"
    params_model = TaskCreateParams
    category = "write"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: TaskCreateParams) -> ToolResult:
        team_name = getattr(self.parent_agent, "team_name", "")
        if not team_name:
            return ToolResult("当前没有活跃团队，请先用 TeamCreate 创建团队。", is_error=True)
        store = self.team_manager.get_task_store(team_name)
        if store is None:
            return ToolResult(f"找不到团队 {team_name!r} 的任务清单。", is_error=True)
        task = store.create(
            title=params.title,
            description=params.description,
            assignee=params.assignee,
            blocks=params.blocks,
            blocked_by=params.blocked_by,
            created_by=getattr(self.parent_agent, "agent_id", ""),
        )
        return ToolResult(
            f"已创建任务 #{task.id}: {task.title}"
            + (f"（指派给 {task.assignee}）" if task.assignee else "")
        )
