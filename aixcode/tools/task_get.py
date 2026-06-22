"""TaskGet：按 id 查看团队共享任务详情。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.tools.base import Tool, ToolResult


class TaskGetParams(BaseModel):
    task_id: int = Field(..., description="任务 id")


class TaskGetTool(Tool):
    name = "TaskGet"
    description = "按 id 查看团队共享任务的详情。"
    params_model = TaskGetParams
    category = "read"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: TaskGetParams) -> ToolResult:
        team_name = getattr(self.parent_agent, "team_name", "")
        if not team_name:
            return ToolResult("当前没有活跃团队，请先用 TeamCreate 创建团队。", is_error=True)
        store = self.team_manager.get_task_store(team_name)
        if store is None:
            return ToolResult(f"找不到团队 {team_name!r} 的任务清单。", is_error=True)
        task = store.get(params.task_id)
        if task is None:
            return ToolResult(f"未找到任务 #{params.task_id}。", is_error=True)
        lines = [
            f"#{task.id} [{task.status}] {task.title}",
            f"  描述: {task.description or '(无)'}",
            f"  指派: {task.assignee or '(未指派)'}",
            f"  创建者: {task.created_by or '(未知)'}",
            f"  阻塞: {task.blocks or '[]'}  被阻塞: {task.blocked_by or '[]'}",
        ]
        return ToolResult("\n".join(lines))
