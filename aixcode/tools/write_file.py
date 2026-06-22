"""WriteFile：写入文件，自动创建中间目录。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult


class WriteFileParams(BaseModel):
    file_path: str
    content: str


class WriteFile(Tool):
    name = "WriteFile"
    description = (
        "把内容写入指定路径（整体覆盖），目录不存在时自动创建。"
        "修改已有文件请优先用 EditFile 做局部替换，本工具用于新建或整体重写。"
    )
    params_model = WriteFileParams
    category = "write"

    async def execute(self, params: WriteFileParams) -> ToolResult:
        path = Path(params.file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.content, encoding="utf-8")
        except OSError as e:
            return ToolResult(f"Error writing file: {e}", is_error=True)
        return ToolResult(f"Successfully wrote to {params.file_path}")
