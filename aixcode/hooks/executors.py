"""四种动作执行器：command / prompt / http / agent。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import urllib.error
import urllib.request

from aixcode.hooks.models import Action, ActionResult, HookContext

log = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30
_RESPONSE_LIMIT = 500


async def _kill_process_tree(proc) -> None:
    """杀掉子进程及其整棵子树（shell 经常再 fork 出孙进程，单杀 shell 不够）。

    Windows 用 `taskkill /T` 杀树；POSIX 杀进程组。杀完确认退出（带兜底超时）。
    """
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        pass


async def execute_command(action: Action, ctx: HookContext) -> ActionResult:
    """跑 shell 命令（stderr 合并到 stdout），支持变量替换与超时清理。"""
    cmd = ctx.expand(action.command or "")
    kwargs = {}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True  # 独立进程组，便于超时时整组 kill
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **kwargs,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=action.timeout)
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)  # 杀整棵树并确认退出，避免泄漏子进程
        return ActionResult(
            f"Command timed out after {action.timeout}s: {cmd}", success=False
        )
    output = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
    return ActionResult(output, success=proc.returncode == 0)


async def execute_prompt(action: Action, ctx: HookContext) -> ActionResult:
    """提示词动作：模板替换后原样返回。"""
    return ActionResult(ctx.expand(action.message or ""), success=True)


async def execute_http(action: Action, ctx: HookContext) -> ActionResult:
    """HTTP 动作：默认 POST，超时 + 响应体截断，同步 urlopen 放线程池。"""
    url = ctx.expand(action.url or "")
    method = (action.method or "POST").upper()
    headers = dict(action.headers or {})
    data = None
    if action.body is not None:
        body = action.body
        if not isinstance(body, (str, bytes)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = ctx.expand(body).encode("utf-8")
        data = body
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    def _do_request():
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                status = getattr(resp, "status", None) or getattr(resp, "code", 200)
                raw = resp.read()
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            return status, text[:_RESPONSE_LIMIT]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    loop = asyncio.get_event_loop()
    status, text = await loop.run_in_executor(None, _do_request)
    if status is None:
        return ActionResult(f"HTTP error: {text}", success=False)
    return ActionResult(f"HTTP {status}: {text}", success=200 <= status < 300)


async def execute_agent(action: Action, ctx: HookContext) -> ActionResult:
    """子 Agent 动作：当前为 stub。"""
    log.info("agent action stub (prompt=%r)", action.prompt)
    return ActionResult("agent executor not yet implemented", success=True)


_EXECUTOR_MAP = {
    "command": execute_command,
    "prompt": execute_prompt,
    "http": execute_http,
    "agent": execute_agent,
}


async def execute_action(action: Action, ctx: HookContext) -> ActionResult:
    """按 action.type 派发到对应执行器；未知类型返回 success=False。"""
    fn = _EXECUTOR_MAP.get(action.type)
    if fn is None:
        return ActionResult(f"unknown action type: {action.type}", success=False)
    return await fn(action, ctx)
