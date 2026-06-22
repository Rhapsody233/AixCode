"""SendMessage：队员间点对点/广播消息，走名字注册表 + 邮箱两段式寻址。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aixcode.teams.mailbox import create_message
from aixcode.teams.registry import AgentNameRegistry
from aixcode.tools.base import Tool, ToolResult

VALID_MESSAGE_TYPES = {"text", "shutdown_request", "shutdown_response"}


class SendMessageParams(BaseModel):
    to: str = Field(..., description="收件人 name 或 agent_id；'*' 表示广播给全队")
    message: str = Field(..., description="消息正文")
    summary: str = Field("", description="5-10 词摘要（text 类型必填）")
    message_type: str = Field("text", description="text / shutdown_request / shutdown_response")
    metadata: dict | None = None


class SendMessageTool(Tool):
    name = "SendMessage"
    description = "给团队里的另一个队员（或 '*' 广播）发一条消息。"
    params_model = SendMessageParams
    category = "command"
    is_system_tool = False

    def __init__(self, team_manager, parent_agent) -> None:
        self.team_manager = team_manager
        self.parent_agent = parent_agent

    async def execute(self, params: SendMessageParams) -> ToolResult:
        team_name = getattr(self.parent_agent, "team_name", "")
        if not team_name:
            return ToolResult("当前没有活跃团队，请先用 TeamCreate 创建团队。", is_error=True)
        if params.message_type not in VALID_MESSAGE_TYPES:
            return ToolResult(
                f"非法 message_type: {params.message_type!r}，可选 {sorted(VALID_MESSAGE_TYPES)}",
                is_error=True,
            )
        if params.message_type == "text" and not params.summary.strip():
            return ToolResult("text 类型消息必须带非空 summary（5-10 词）。", is_error=True)
        mailbox = self.team_manager.get_mailbox(team_name)
        if mailbox is None:
            return ToolResult(f"找不到团队 {team_name!r} 的邮箱。", is_error=True)

        self_id = getattr(self.parent_agent, "agent_id", "")
        msg = create_message(
            from_agent=self_id,
            to_agent=params.to,
            content=params.message,
            summary=params.summary,
            message_type=params.message_type,
            metadata=params.metadata,
        )

        if params.to == "*":
            team = self.team_manager.get_team(team_name)
            recipients = {m.agent_id for m in team.members}
            if team.lead_agent_id:
                recipients.add(team.lead_agent_id)
            recipients.discard(self_id)
            mailbox.broadcast(sorted(recipients), msg)
            for rid in recipients:
                self._wake_pane(rid)
            return ToolResult(f"已广播给 {len(recipients)} 个成员。")

        target_id = AgentNameRegistry.instance().resolve(params.to)
        if target_id is None:
            return ToolResult(f"Cannot resolve recipient '{params.to}'", is_error=True)
        mailbox.write(target_id, msg)
        self._wake_pane(target_id)
        return ToolResult(f"已发送给 {params.to}。")

    def _wake_pane(self, target_id: str) -> None:
        """pane 后端需 send-keys 唤醒对方读新消息；in-process 无 pane_id，no-op。"""
        pane_id = self.team_manager.get_pane_id(target_id)
        if not pane_id:
            return
        from aixcode.teams.spawn_tmux import send_keys_to_pane

        send_keys_to_pane(pane_id, "")
