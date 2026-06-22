"""LoadSkill：read-only 系统工具，按需激活一个 Skill。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult


class LoadSkillParams(BaseModel):
    name: str


class LoadSkill(Tool):
    """把指定 skill 的完整 SOP 钉到上下文，并（目录型）注册其专属工具。"""

    name = "LoadSkill"
    description = (
        "按需激活一个 Skill：把它的完整 SOP 钉到环境上下文，并注册该 Skill 自带的专属工具。"
        "当用户请求与某个 Skill 匹配时调用，参数 name 为 Skill 名。"
    )
    params_model = LoadSkillParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True

    def __init__(self) -> None:
        self._loader = None
        self._agent = None

    def set_loader(self, loader) -> None:
        self._loader = loader

    def set_agent(self, agent) -> None:
        self._agent = agent

    async def execute(self, params: LoadSkillParams) -> ToolResult:
        if self._loader is None or self._agent is None:
            return ToolResult("LoadSkill not properly initialized", is_error=True)
        skill = self._loader.get(params.name)
        if skill is None:
            listing = "\n".join(f"- {n}: {d}" for n, d in self._loader.get_catalog())
            return ToolResult(
                f"未找到 skill '{params.name}'。可用 skill：\n{listing}", is_error=True
            )
        self._agent.activate_skill(skill.name, skill.prompt_body)
        msg = f"Skill '{skill.name}' activated. SOP pinned to context."
        if skill.is_directory and skill.source_path:
            from aixcode.skills.directory import register_skill_tools

            count = register_skill_tools(
                str(Path(skill.source_path).parent), self._agent.registry
            )
            if count:
                msg += f" {count} specialized tool(s) registered."
        return ToolResult(msg)
