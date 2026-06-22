"""ReadFile：读文本文件并按行号输出。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult


class ReadFileParams(BaseModel):
    file_path: str
    offset: int = 0
    limit: int = 2000


class ReadFile(Tool):
    name = "ReadFile"
    description = (
        "读取文本文件内容，按行号输出。支持 offset/limit 切片。"
        "编辑文件前先用本工具读取，不要用 Bash 的 cat 替代。"
    )
    params_model = ReadFileParams
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: ReadFileParams) -> ToolResult:
        path = Path(params.file_path)
        if not path.exists():
            return ToolResult(f"Error: file not found: {params.file_path}", is_error=True)
        if not path.is_file():
            return ToolResult(f"Error: not a file: {params.file_path}", is_error=True)

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult(f"Error reading file: {e}", is_error=True)

        lines = text.splitlines()
        sliced = lines[params.offset : params.offset + params.limit]
        numbered = [f"{i + params.offset + 1}\t{line}" for i, line in enumerate(sliced)]
        return ToolResult("\n".join(numbered))
