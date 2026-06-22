"""Bash：通过 shell 子进程执行命令，带超时与输出捕获。"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from aixcode.tools.base import Tool, ToolResult

MAX_TIMEOUT = 600


class BashParams(BaseModel):
    command: str
    timeout: int = 120


class Bash(Tool):
    name = "Bash"
    description = (
        "在 shell 里执行命令，返回 stdout/stderr 与退出码。"
        "仅用于确实没有专用工具覆盖的命令（构建、测试、git 等）；"
        "读文件用 ReadFile、找文件用 Glob、搜内容用 Grep，不要用 cat/ls/grep/find。"
    )
    params_model = BashParams
    category = "command"

    async def execute(self, params: BashParams) -> ToolResult:
        timeout = min(params.timeout, MAX_TIMEOUT)
        proc = await asyncio.create_subprocess_shell(
            params.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                f"Error: command timed out after {timeout}s", is_error=True
            )

        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        parts = []
        if out:
            parts.append(f"STDOUT:\n{out}")
        if err:
            parts.append(f"STDERR:\n{err}")
        body = "\n".join(parts) if parts else "(no output)"
        return ToolResult(body, is_error=(proc.returncode != 0))
