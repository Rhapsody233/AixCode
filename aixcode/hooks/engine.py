"""HookEngine：匹配 + 执行 + once/async 控制 + pre_tool_use 拦截。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aixcode.hooks.executors import execute_action
from aixcode.hooks.models import Hook, HookContext, ToolRejectedError

log = logging.getLogger(__name__)


@dataclass
class HookNotification:
    """一次 hook 执行结果，供 TUI 展示。"""

    hook_id: str
    event: str
    output: str
    success: bool


class HookEngine:
    """运行在单 event loop 上，顺序触发命中钩子；错误隔离不拖垮主流程。"""

    def __init__(self, hooks: list[Hook]) -> None:
        self.hooks = hooks
        self._prompt_messages: list[str] = []
        self._notifications: list[HookNotification] = []

    def find_matching_hooks(self, event: str, ctx: HookContext) -> list[Hook]:
        """三层过滤：事件名 + should_run（once）+ condition。"""
        matched = []
        for hook in self.hooks:
            if hook.event != event or not hook.should_run():
                continue
            if hook.condition is not None and not hook.condition.evaluate(ctx):
                continue
            matched.append(hook)
        return matched

    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        """触发普通事件的全部命中钩子；async_exec 的后台跑不 await。"""
        for hook in self.find_matching_hooks(event, ctx):
            if hook.async_exec:
                asyncio.ensure_future(self._run_single(hook, ctx))
            else:
                await self._run_single(hook, ctx)

    async def _run_single(self, hook: Hook, ctx: HookContext) -> None:
        hook.mark_executed()
        try:
            result = await execute_action(hook.action, ctx)
        except Exception as e:  # 错误隔离：绝不让 hook 拖垮主流程
            log.warning("hook %r execution failed: %s", hook.id, e)
            self._notifications.append(
                HookNotification(hook.id, hook.event, f"hook error: {e}", False)
            )
            return
        if hook.action.type == "prompt" and result.success:
            self._prompt_messages.append(result.output)
        self._notifications.append(
            HookNotification(hook.id, hook.event, result.output, result.success)
        )

    async def run_pre_tool_hooks(self, ctx: HookContext) -> ToolRejectedError | None:
        """pre_tool_use 专用：遇 reject=True 命中即返回 ToolRejectedError。"""
        for hook in self.find_matching_hooks("pre_tool_use", ctx):
            hook.mark_executed()
            try:
                result = await execute_action(hook.action, ctx)
            except Exception as e:  # 错误隔离
                log.warning("pre_tool hook %r failed: %s", hook.id, e)
                continue
            self._notifications.append(
                HookNotification(hook.id, hook.event, result.output, result.success)
            )
            if hook.reject:
                return ToolRejectedError(
                    tool=ctx.tool_name or "", reason=result.output, hook_id=hook.id
                )
        return None

    def get_prompt_messages(self) -> list[str]:
        """一次性取出并清空 prompt 类型 hook 的输出。"""
        msgs = self._prompt_messages
        self._prompt_messages = []
        return msgs

    def drain_notifications(self) -> list[HookNotification]:
        """一次性取出并清空通知队列。"""
        notes = self._notifications
        self._notifications = []
        return notes
