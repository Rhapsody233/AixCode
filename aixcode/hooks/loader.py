"""从声明式 dict 列表加载并校验 Hook，错误可定位到具体规则。"""

from __future__ import annotations

from aixcode.hooks.conditions import ConditionParseError, parse_condition
from aixcode.hooks.events import LifecycleEvent
from aixcode.hooks.models import Action, Hook

_VALID_ACTION_TYPES = {"command", "prompt", "http", "agent"}
_REQUIRED_FIELDS = {
    "command": "command",
    "prompt": "message",
    "http": "url",
    "agent": "prompt",
}


class HookConfigError(Exception):
    """hook 声明配置非法。"""


def load_hooks(raw_hooks: list[dict] | None) -> list[Hook]:
    """校验并解析原始 hook 配置；任意非法抛 HookConfigError（消息带定位）。"""
    if not raw_hooks:
        return []
    valid_events = {e.value for e in LifecycleEvent}
    hooks: list[Hook] = []
    for i, raw in enumerate(raw_hooks):
        raw = raw or {}
        explicit_id = raw.get("id")
        loc = f"hook '{explicit_id}'" if explicit_id else f"hook #{i + 1}"

        event = raw.get("event")
        if event not in valid_events:
            raise HookConfigError(f"{loc}: invalid event {event!r}")

        action_raw = raw.get("action") or {}
        atype = action_raw.get("type")
        if atype not in _VALID_ACTION_TYPES:
            raise HookConfigError(f"{loc}: invalid action type {atype!r}")
        required = _REQUIRED_FIELDS[atype]
        if not action_raw.get(required):
            raise HookConfigError(
                f"{loc}: action type {atype!r} requires {required!r} field"
            )

        reject = bool(raw.get("reject", False))
        async_exec = bool(raw.get("async", False))
        if reject and event != "pre_tool_use":
            raise HookConfigError(f"{loc}: reject only allowed on pre_tool_use event")
        if async_exec and event == "pre_tool_use":
            raise HookConfigError(f"{loc}: async not allowed on pre_tool_use event")

        timeout = action_raw.get("timeout", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise HookConfigError(f"{loc}: action timeout must be a positive integer")

        try:
            condition = parse_condition(raw.get("if"))
        except ConditionParseError as e:
            raise HookConfigError(f"{loc}: invalid condition: {e}") from e

        action = Action(
            type=atype,
            command=action_raw.get("command"),
            message=action_raw.get("message"),
            url=action_raw.get("url"),
            method=action_raw.get("method", "POST"),
            body=action_raw.get("body"),
            headers=dict(action_raw.get("headers") or {}),
            prompt=action_raw.get("prompt"),
            timeout=timeout,
        )
        hooks.append(
            Hook(
                id=explicit_id or f"{event}_{i}",
                event=event,
                action=action,
                condition=condition,
                reject=reject,
                once=bool(raw.get("once", False)),
                async_exec=async_exec,
            )
        )
    return hooks
