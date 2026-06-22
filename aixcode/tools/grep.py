"""Grep：按正则逐行搜索文件内容，跳过无关目录。"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from aixcode.tools.base import SKIP_DIRS, Tool, ToolResult


class GrepParams(BaseModel):
    pattern: str
    path: str = "."
    include: str = ""


class Grep(Tool):
    name = "Grep"
    description = "按正则搜索文件内容，输出 <文件>:<行号>:<行>。include 按文件名 glob 过滤。"
    params_model = GrepParams
    category = "read"
    is_concurrency_safe = True

    async def execute(self, params: GrepParams) -> ToolResult:
        try:
            regex = re.compile(params.pattern)
        except re.error as e:
            return ToolResult(f"Error: invalid regex: {e}", is_error=True)

        base = Path(params.path)
        glob_pat = f"**/{params.include}" if params.include else "**/*"
        matches = []
        for p in sorted(base.glob(glob_pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(base)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{line_num}:{line}")

        if not matches:
            return ToolResult("No matches found.")
        return ToolResult("\n".join(matches))
