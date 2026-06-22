"""TeamCreate：建团队（按环境选后端落盘），可选切 Coordinator Mode。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.agents.tool_filter import apply_coordinator_filter
from aixcode.teams.backend_detect import BackendDetectionError
from aixcode.teams.coordinator import is_coordinator_mode
from aixcode.tools.base import Tool, ToolResult


class TeamCreateParams(BaseModel):
    team_name: str = Field(..., description="团队名")
    description: str = Field("", description="团队目标的简短描述")


class TeamCreateTool(Tool):
    name = "TeamCreate"
    description = "创建一个长期协作团队（按环境自动选后端，本机走 in-process）。"
    params_model = TeamCreateParams
    category = "command"
    is_system_tool = False

    def __init__(
        self,
        team_manager,
        parent_agent,
        teammate_mode: str = "",
        is_interactive: bool = True,
        enable_coordinator_mode: bool = False,
    ) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent
        self.teammate_mode = teammate_mode
        self.is_interactive = is_interactive
        self.enable_coordinator_mode = enable_coordinator_mode

    async def execute(self, params: TeamCreateParams) -> ToolResult:
        try:
            backend = self.team_manager.detect_backend(
                self.teammate_mode, self.is_interactive
            )
        except BackendDetectionError as e:
            return ToolResult(str(e), is_error=True)

        team = self.team_manager.create_team(
            params.team_name,
            lead_agent_id=getattr(self.parent_agent, "agent_id", ""),
            description=params.description,
            teammate_mode=self.teammate_mode,
            is_interactive=self.is_interactive,
        )
        self.parent_agent.team_name = team.name

        output = (
            f"已创建团队 '{team.name}'。后端：{backend.value}。"
            f"配置：{team.config_path}"
        )

        if is_coordinator_mode(self.enable_coordinator_mode):
            self.parent_agent.coordinator_mode = True
            self.parent_agent._full_registry = self.parent_agent.registry
            self.parent_agent.registry = apply_coordinator_filter(
                self.parent_agent.registry
            )
            output += "\nCoordinator Mode activated（已切换为协调模式，写工具已收起）。"

        return ToolResult(output)
