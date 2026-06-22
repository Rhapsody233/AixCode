"""AskUserQuestion：在终端向用户提结构化问题并等待作答。"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult


class QuestionItem(BaseModel):
    name: str
    message: str
    type: str = "single"
    options: list[str] = []


class AskUserParams(BaseModel):
    questions: list[QuestionItem]


class AskUserTool(Tool):
    name = "AskUserQuestion"
    description = "向用户提一个或多个带选项的问题，等待用户作答后把结果回灌。"
    params_model = AskUserParams
    category = "read"
    should_defer = True
    is_system_tool = True
    timeout = 300

    async def execute(self, params: AskUserParams) -> ToolResult:
        try:
            return await asyncio.wait_for(self._ask(params), timeout=self.timeout)
        except TimeoutError:
            return ToolResult("User did not respond within 5 minutes", is_error=True)

    async def _ask(self, params: AskUserParams) -> ToolResult:
        answers = []
        for q in params.questions:
            lines = [q.message]
            for i, opt in enumerate(q.options, 1):
                lines.append(f"  {i}. {opt}")
            print("\n".join(lines))
            raw = await asyncio.to_thread(input, "> ")
            answers.append(f"{q.name}: {self._resolve(raw, q.options)}")
        return ToolResult("\n".join(answers))

    @staticmethod
    def _resolve(raw: str, options: list[str]) -> str:
        raw = raw.strip()
        if options and raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        return raw
