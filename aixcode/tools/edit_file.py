"""EditFile：基于原文唯一匹配做一次性替换。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult


class EditFileParams(BaseModel):
    file_path: str
    old_string: str
    new_string: str


class EditFile(Tool):
    name = "EditFile"
    description = (
        "把文件里唯一匹配的 old_string 替换成 new_string；匹配不到或多处都会报错。"
        "调用前必须先用 ReadFile 读过该文件，old_string 要照抄原文（含缩进）。"
    )
    params_model = EditFileParams
    category = "write"

    async def execute(self, params: EditFileParams) -> ToolResult:
        path = Path(params.file_path)
        if not path.is_file():
            return ToolResult(f"Error: file not found: {params.file_path}", is_error=True)

        text = path.read_text(encoding="utf-8")
        count = text.count(params.old_string)
        if count == 0:
            return ToolResult(
                f"Error: old_string not found in {params.file_path}", is_error=True
            )
        if count > 1:
            return ToolResult(
                f"Error: old_string found {count} times, must be unique", is_error=True
            )

        path.write_text(text.replace(params.old_string, params.new_string, 1), encoding="utf-8")
        return ToolResult(f"Successfully edited {params.file_path}")
