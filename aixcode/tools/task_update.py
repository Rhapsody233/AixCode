"""TaskUpdate：部分更新团队共享任务字段，依赖列表去重追加。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult


class TaskUpdateParams(BaseModel):
    task_id: int = Field(..., description="任务 id")
    status: str = Field("", description="新状态：pending/in_progress/completed/blocked")
    assignee: str = ""
    title: str = ""
    description: str = ""
    add_blocks: list[int] | None = Field(None, description="追加本任务阻塞的任务 id")
    add_blocked_by: list[int] | None = Field(None, description="追加阻塞本任务的任务 id")


class TaskUpdateTool(Tool):
    name = "TaskUpdate"
    description = "部分更新团队共享任务的字段（状态/指派/标题/描述/依赖）。"
    params_model = TaskUpdateParams
    category = "write"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: TaskUpdateParams) -> ToolResult:
        team_name = getattr(self.parent_agent, "team_name", "")
        if not team_name:
            return ToolResult("当前没有活跃团队，请先用 TeamCreate 创建团队。", is_error=True)
        store = self.team_manager.get_task_store(team_name)
        if store is None:
            return ToolResult(f"找不到团队 {team_name!r} 的任务清单。", is_error=True)
        task = store.update(
            params.task_id,
            status=params.status,
            assignee=params.assignee,
            title=params.title,
            description=params.description,
            add_blocks=params.add_blocks,
            add_blocked_by=params.add_blocked_by,
        )
        if task is None:
            return ToolResult(f"未找到任务 #{params.task_id}。", is_error=True)
        return ToolResult(f"已更新任务 #{task.id}: [{task.status}] {task.title}")
