"""Glob：按模式递归匹配文件名，跳过无关目录。"""

from __future__ import annotations

from pydantic import BaseModel

from aixcode.tools.base import SKIP_DIRS, Tool, ToolResult
from aixcode.tools.workdir import resolve_path


class GlobParams(BaseModel):
    pattern: str
    path: str = "."


class Glob(Tool):
    name = "Glob"
    description = "按 glob 模式查找文件，返回相对路径（字典序）。"
    params_model = GlobParams
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: GlobParams) -> ToolResult:
        base = resolve_path(params.path)
        matches = []
        for p in base.glob(params.pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(base)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            matches.append(str(rel))

        if not matches:
            return ToolResult("No files matched the pattern.")
        matches.sort()
        return ToolResult("\n".join(matches))
