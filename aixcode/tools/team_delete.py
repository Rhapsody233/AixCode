"""TeamDelete：删团队（校验全员 idle），如在 Coordinator Mode 则恢复工具集。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.teams.manager import TeamError
from aixcode.tools.base import Tool, ToolResult


class TeamDeleteParams(BaseModel):
    team_name: str = Field(..., description="要删除的团队名")


class TeamDeleteTool(Tool):
    name = "TeamDelete"
    description = "删除一个团队并释放其资源（需全员 idle）。"
    params_model = TeamDeleteParams
    category = "command"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: TeamDeleteParams) -> ToolResult:
        try:
            await self.team_manager.delete_team(params.team_name)
        except TeamError as e:
            return ToolResult(str(e), is_error=True)

        output = f"已删除团队 '{params.team_name}'。"

        if getattr(self.parent_agent, "coordinator_mode", False):
            full = getattr(self.parent_agent, "_full_registry", None)
            if full is not None:
                self.parent_agent.registry = full
            self.parent_agent.coordinator_mode = False
            self.parent_agent.team_name = ""
            output += "\nCoordinator Mode deactivated（已退出协调模式，工具集已恢复）。"

        return ToolResult(output)
