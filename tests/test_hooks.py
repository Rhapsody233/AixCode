"""ch12 Hook 系统测试。"""

import asyncio

import pytest

from aixcode.hooks.events import LifecycleEvent

_EXPECTED_EVENTS = {
    "session_start", "session_end", "turn_start", "turn_end",
    "pre_tool_use", "post_tool_use", "pre_send", "post_receive",
    "startup", "shutdown", "error", "compact",
    "permission_request", "file_change", "command_execute",
}


# ======================================================================
# T1: LifecycleEvent
# ======================================================================

def test_lifecycle_event_count():
    assert len(LifecycleEvent) == 15


def test_lifecycle_event_values():
    assert {e.value for e in LifecycleEvent} == _EXPECTED_EVENTS


def test_lifecycle_event_str_comparable():
    assert LifecycleEvent.SESSION_START == "session_start"
    assert LifecycleEvent.PRE_TOOL_USE == "pre_tool_use"


# ======================================================================
# T2: 数据模型
# ======================================================================

from aixcode.hooks.models import (
    Action,
    ActionResult,
    Hook,
    HookContext,
    ToolRejectedError,
)


def test_action_defaults():
    a = Action(type="command", command="echo hi")
    assert a.timeout == 30
    assert a.method == "POST"


def test_action_result_fields():
    r = ActionResult(output="ok", success=True)
    assert r.output == "ok" and r.success is True


def test_hook_should_run_once():
    h = Hook(id="h1", event="turn_start", action=Action(type="prompt", message="m"), once=True)
    assert h.should_run() is True
    h.mark_executed()
    assert h.executed is True
    assert h.should_run() is False


def test_hook_should_run_not_once():
    h = Hook(id="h2", event="turn_start", action=Action(type="prompt", message="m"))
    h.mark_executed()
    assert h.should_run() is True  # once=False，始终可跑


def test_context_get_field():
    ctx = HookContext(event_name="pre_tool_use", tool_name="Bash",
                      tool_args={"command": "rm -rf /"})
    assert ctx.get_field("tool") == "Bash"
    assert ctx.get_field("event") == "pre_tool_use"
    assert ctx.get_field("args.command") == "rm -rf /"
    assert ctx.get_field("args.missing") == ""
    assert ctx.get_field("nope") == ""


def test_context_expand_all_vars():
    ctx = HookContext(event_name="pre_tool_use", tool_name="Bash",
                      tool_args={"command": "ls"}, file_path="/a.py",
                      message="hi", error="boom")
    out = ctx.expand("$EVENT|$TOOL_NAME|$FILE_PATH|$MESSAGE|$ERROR|$TOOL_ARGS.command")
    assert out == "pre_tool_use|Bash|/a.py|hi|boom|ls"


def test_context_expand_undefined_to_empty():
    ctx = HookContext(event_name="turn_start")
    assert ctx.expand("[$TOOL_NAME][$TOOL_ARGS.command]") == "[][]"


def test_tool_rejected_error_fields():
    err = ToolRejectedError(tool="Bash", reason="blocked", hook_id="h1")
    assert err.tool == "Bash" and err.reason == "blocked" and err.hook_id == "h1"


# ======================================================================
# T3: Condition DSL
# ======================================================================

from aixcode.hooks.conditions import (
    Condition,
    ConditionGroup,
    ConditionParseError,
    parse_condition,
)


def _ctx(tool="Bash", command="ls", event="pre_tool_use"):
    return HookContext(event_name=event, tool_name=tool, tool_args={"command": command})


def test_parse_single():
    c = parse_condition('tool == "Bash"')
    assert isinstance(c, Condition)
    assert c.field == "tool" and c.operator == "==" and c.value == "Bash"


def test_parse_and_group():
    g = parse_condition('tool == "Bash" && args.command =~ /rm/')
    assert isinstance(g, ConditionGroup)
    assert g.logic == "and" and len(g.conditions) == 2


def test_parse_or_group():
    g = parse_condition('tool == "Bash" || tool == "Grep"')
    assert isinstance(g, ConditionGroup) and g.logic == "or"


def test_parse_mix_raises():
    with pytest.raises(ConditionParseError):
        parse_condition('a == "1" && b == "2" || c == "3"')


def test_parse_empty_returns_none():
    assert parse_condition("") is None
    assert parse_condition("   ") is None
    assert parse_condition(None) is None


def test_parse_no_operator_raises():
    with pytest.raises(ConditionParseError):
        parse_condition("justatoken")


def test_condition_eq_neq():
    assert Condition("tool", "==", "Bash").evaluate(_ctx()) is True
    assert Condition("tool", "!=", "Bash").evaluate(_ctx()) is False


def test_condition_regex():
    c = Condition("args.command", "=~", r"/rm\s+-rf/")
    assert c.evaluate(_ctx(command="rm -rf /")) is True
    assert c.evaluate(_ctx(command="ls")) is False


def test_condition_regex_invalid_returns_false():
    assert Condition("args.command", "=~", "[unclosed").evaluate(_ctx()) is False


def test_condition_glob():
    assert Condition("args.command", "~=", "*.py").evaluate(_ctx(command="main.py")) is True
    assert Condition("args.command", "~=", "*.py").evaluate(_ctx(command="main.txt")) is False


def test_group_and():
    g = ConditionGroup([Condition("tool", "==", "Bash"), Condition("args.command", "==", "ls")], "and")
    assert g.evaluate(_ctx()) is True
    g2 = ConditionGroup([Condition("tool", "==", "Bash"), Condition("args.command", "==", "rm")], "and")
    assert g2.evaluate(_ctx()) is False


def test_group_or():
    g = ConditionGroup([Condition("tool", "==", "X"), Condition("tool", "==", "Bash")], "or")
    assert g.evaluate(_ctx()) is True
    g2 = ConditionGroup([Condition("tool", "==", "X"), Condition("tool", "==", "Y")], "or")
    assert g2.evaluate(_ctx()) is False


def test_group_empty_true():
    assert ConditionGroup([], "and").evaluate(_ctx()) is True


# ======================================================================
# T6: 动作执行器
# ======================================================================

from aixcode.hooks import executors
from aixcode.hooks.executors import (
    execute_action,
    execute_agent,
    execute_command,
    execute_http,
    execute_prompt,
)

_SLEEP10 = 'python -c "import time;time.sleep(10)"'


def test_execute_command_basic():
    a = Action(type="command", command="echo hello")
    res = asyncio.run(execute_command(a, HookContext(event_name="post_tool_use")))
    assert res.success is True
    assert "hello" in res.output


def test_execute_command_expands_vars():
    a = Action(type="command", command="echo $TOOL_NAME")
    ctx = HookContext(event_name="post_tool_use", tool_name="Bash")
    res = asyncio.run(execute_command(a, ctx))
    assert "Bash" in res.output


def test_execute_command_timeout():
    a = Action(type="command", command=_SLEEP10, timeout=1)
    res = asyncio.run(execute_command(a, HookContext(event_name="post_tool_use")))
    assert res.success is False
    assert "timed out" in res.output.lower()


def test_execute_prompt():
    a = Action(type="prompt", message="hi $TOOL_NAME")
    ctx = HookContext(event_name="pre_send", tool_name="Bash")
    res = asyncio.run(execute_prompt(a, ctx))
    assert res.success is True and res.output == "hi Bash"


class _FakeResp:
    status = 200

    def read(self):
        return b'{"ok": true}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_execute_http_mock(monkeypatch):
    monkeypatch.setattr(
        executors.urllib.request, "urlopen", lambda req, timeout=30: _FakeResp()
    )
    a = Action(type="http", url="http://example.com/hook", body={"a": 1})
    res = asyncio.run(execute_http(a, HookContext(event_name="post_tool_use")))
    assert res.success is True
    assert "200" in res.output


def test_execute_agent_no_runner():
    res = asyncio.run(execute_agent(Action(type="agent", prompt="p"),
                                    HookContext(event_name="turn_start"), None))
    assert res.success is False


def test_execute_agent_with_runner():
    async def runner(prompt):
        return f"ran:{prompt}"

    res = asyncio.run(execute_agent(Action(type="agent", prompt="do it"),
                                    HookContext(event_name="turn_start"), runner))
    assert res.success is True
    assert res.output == "ran:do it"


def test_execute_agent_runner_raises():
    async def runner(prompt):
        raise RuntimeError("boom")

    res = asyncio.run(execute_agent(Action(type="agent", prompt="p"),
                                    HookContext(event_name="turn_start"), runner))
    assert res.success is False


def test_execute_agent_expands_prompt():
    async def runner(prompt):
        return prompt

    ctx = HookContext(event_name="post_tool_use", tool_name="Bash")
    res = asyncio.run(execute_agent(Action(type="agent", prompt="ran $TOOL_NAME"),
                                    ctx, runner))
    assert res.output == "ran Bash"


def test_execute_action_dispatch():
    res = asyncio.run(execute_action(Action(type="prompt", message="x"),
                                     HookContext(event_name="turn_start")))
    assert res.output == "x"


def test_execute_action_agent_threads_runner():
    async def runner(prompt):
        return f"got:{prompt}"

    res = asyncio.run(execute_action(Action(type="agent", prompt="hey"),
                                     HookContext(event_name="turn_start"), runner))
    assert res.success is True
    assert res.output == "got:hey"


def test_hook_engine_agent_runner_integration():
    from aixcode.hooks.engine import HookEngine
    from aixcode.hooks.models import Hook

    async def runner(prompt):
        return f"agent ran: {prompt}"

    hook = Hook(id="h1", event="turn_start",
                action=Action(type="agent", prompt="investigate"))
    engine = HookEngine([hook])
    engine.set_agent_runner(runner)
    asyncio.run(engine.run_hooks("turn_start", HookContext(event_name="turn_start")))
    notes = engine.drain_notifications()
    assert any(n.success and "agent ran: investigate" in n.output for n in notes)


def test_execute_action_unknown_type():
    res = asyncio.run(execute_action(Action(type="bogus"),
                                     HookContext(event_name="turn_start")))
    assert res.success is False


# ======================================================================
# T4 + T5: HookEngine
# ======================================================================

import time

from aixcode.hooks import engine as engine_mod
from aixcode.hooks.engine import HookEngine


def test_find_matching_event_filter():
    eng = HookEngine([
        Hook("a", "turn_start", Action(type="prompt", message="m")),
        Hook("b", "turn_end", Action(type="prompt", message="m")),
    ])
    matched = eng.find_matching_hooks("turn_start", HookContext(event_name="turn_start"))
    assert [h.id for h in matched] == ["a"]


def test_find_matching_condition_filter():
    hook = Hook("a", "pre_tool_use", Action(type="prompt", message="m"),
                condition=parse_condition('tool == "Bash"'))
    eng = HookEngine([hook])
    assert eng.find_matching_hooks(
        "pre_tool_use", HookContext(event_name="pre_tool_use", tool_name="Grep")) == []
    assert len(eng.find_matching_hooks(
        "pre_tool_use", HookContext(event_name="pre_tool_use", tool_name="Bash"))) == 1


def test_find_matching_once_filter():
    hook = Hook("a", "turn_start", Action(type="prompt", message="m"), once=True)
    eng = HookEngine([hook])
    ctx = HookContext(event_name="turn_start")
    assert len(eng.find_matching_hooks("turn_start", ctx)) == 1
    hook.mark_executed()
    assert eng.find_matching_hooks("turn_start", ctx) == []


def test_run_hooks_collects_prompt():
    eng = HookEngine([Hook("a", "pre_send", Action(type="prompt", message="injected"))])
    asyncio.run(eng.run_hooks("pre_send", HookContext(event_name="pre_send")))
    assert eng.get_prompt_messages() == ["injected"]
    assert eng.get_prompt_messages() == []  # 取出后清空


def test_run_hooks_records_notifications():
    eng = HookEngine([Hook("a", "turn_start", Action(type="prompt", message="m"))])
    asyncio.run(eng.run_hooks("turn_start", HookContext(event_name="turn_start")))
    notes = eng.drain_notifications()
    assert len(notes) == 1 and notes[0].hook_id == "a"
    assert eng.drain_notifications() == []


def test_run_hooks_error_isolated(monkeypatch):
    async def boom(action, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(engine_mod, "execute_action", boom)
    eng = HookEngine([Hook("a", "turn_start", Action(type="prompt", message="m"))])
    asyncio.run(eng.run_hooks("turn_start", HookContext(event_name="turn_start")))  # 不抛
    notes = eng.drain_notifications()
    assert any(not n.success for n in notes)


def test_async_hook_does_not_block(monkeypatch):
    async def slow(action, ctx):
        await asyncio.sleep(10)
        return ActionResult("done", True)

    monkeypatch.setattr(engine_mod, "execute_action", slow)
    eng = HookEngine([
        Hook("a", "turn_start", Action(type="prompt", message="m"), async_exec=True)
    ])
    start = time.perf_counter()
    asyncio.run(eng.run_hooks("turn_start", HookContext(event_name="turn_start")))
    assert time.perf_counter() - start < 3  # ensure_future 派发不 await，立即返回


def test_pre_tool_reject():
    hook = Hook("blk", "pre_tool_use", Action(type="prompt", message="blocked"),
                reject=True, condition=parse_condition('tool == "Bash"'))
    eng = HookEngine([hook])
    ctx = HookContext(event_name="pre_tool_use", tool_name="Bash",
                      tool_args={"command": "rm -rf /"})
    err = asyncio.run(eng.run_pre_tool_hooks(ctx))
    assert err is not None
    assert err.reason == "blocked" and err.tool == "Bash" and err.hook_id == "blk"


def test_pre_tool_no_reject_returns_none():
    eng = HookEngine([Hook("log", "pre_tool_use", Action(type="prompt", message="log"))])
    ctx = HookContext(event_name="pre_tool_use", tool_name="Bash")
    assert asyncio.run(eng.run_pre_tool_hooks(ctx)) is None


def test_pre_tool_condition_no_match():
    hook = Hook("blk", "pre_tool_use", Action(type="prompt", message="blocked"),
                reject=True, condition=parse_condition('tool == "Grep"'))
    eng = HookEngine([hook])
    ctx = HookContext(event_name="pre_tool_use", tool_name="Bash")
    assert asyncio.run(eng.run_pre_tool_hooks(ctx)) is None


# ======================================================================
# T7: load_hooks
# ======================================================================

from aixcode.hooks.loader import HookConfigError, load_hooks


def test_load_hooks_empty():
    assert load_hooks(None) == []
    assert load_hooks([]) == []


def test_load_hooks_full_config():
    raw = [{
        "id": "block-rm",
        "event": "pre_tool_use",
        "if": 'tool == "Bash" && args.command =~ /rm\\s+-rf/',
        "action": {"type": "prompt", "message": "blocked"},
        "reject": True,
    }]
    hooks = load_hooks(raw)
    assert len(hooks) == 1
    h = hooks[0]
    assert h.id == "block-rm" and h.event == "pre_tool_use"
    assert h.reject is True and h.action.type == "prompt"
    assert h.condition is not None


def test_load_hooks_auto_id():
    hooks = load_hooks([{"event": "turn_start", "action": {"type": "prompt", "message": "m"}}])
    assert hooks[0].id == "turn_start_0"


def test_load_hooks_async_maps():
    hooks = load_hooks([{"event": "post_tool_use", "action": {"type": "command", "command": "echo x"},
                         "async": True}])
    assert hooks[0].async_exec is True


def test_load_hooks_bad_event():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "bogus", "action": {"type": "prompt", "message": "m"}}])


def test_load_hooks_bad_action_type():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "turn_start", "action": {"type": "bogus"}}])


def test_load_hooks_missing_required_field():
    with pytest.raises(HookConfigError) as ei:
        load_hooks([{"id": "x", "event": "turn_start", "action": {"type": "command"}}])
    assert "command" in str(ei.value) and "requires" in str(ei.value)


def test_load_hooks_reject_only_pre_tool():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "turn_start", "action": {"type": "prompt", "message": "m"},
                     "reject": True}])


def test_load_hooks_async_not_pre_tool():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "pre_tool_use", "action": {"type": "prompt", "message": "m"},
                     "async": True}])


def test_load_hooks_bad_timeout():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "turn_start",
                     "action": {"type": "command", "command": "x", "timeout": 0}}])


def test_load_hooks_bad_condition():
    with pytest.raises(HookConfigError):
        load_hooks([{"event": "turn_start", "action": {"type": "prompt", "message": "m"},
                     "if": 'a == 1 && b == 2 || c == 3'}])


def test_load_hooks_error_locator_uses_index():
    with pytest.raises(HookConfigError) as ei:
        load_hooks([{"event": "bogus", "action": {"type": "prompt", "message": "m"}}])
    assert "hook #1" in str(ei.value)


# ======================================================================
# T8: 包出口
# ======================================================================

def test_package_exports():
    from aixcode.hooks import (  # noqa: F401
        Action,
        ActionResult,
        Condition,
        ConditionGroup,
        ConditionParseError,
        Hook,
        HookConfigError,
        HookContext,
        HookEngine,
        HookNotification,
        LifecycleEvent,
        ToolRejectedError,
        load_hooks,
        parse_condition,
    )

    assert HookEngine is not None and load_hooks is not None


# ======================================================================
# T9: config.load_raw_hooks
# ======================================================================

def test_load_raw_hooks(tmp_path):
    from aixcode.config import load_raw_hooks

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "hooks:\n  - event: turn_start\n    action:\n      type: prompt\n      message: hi\n",
        encoding="utf-8",
    )
    raw = load_raw_hooks(str(cfg))
    assert isinstance(raw, list) and raw[0]["event"] == "turn_start"


def test_load_raw_hooks_missing_key(tmp_path):
    from aixcode.config import load_raw_hooks

    cfg = tmp_path / "config.yaml"
    cfg.write_text("protocol: openai\n", encoding="utf-8")
    assert load_raw_hooks(str(cfg)) == []


def test_load_raw_hooks_no_file():
    from aixcode.config import load_raw_hooks

    assert load_raw_hooks("/no/such/config.yaml") == []


# ======================================================================
# T10: Agent hook 字段 + 辅助 + HookEvent
# ======================================================================

from aixcode.tools import create_default_registry


def _agent(tmp_path, engine=None):
    from aixcode.agent import Agent

    return Agent(object(), create_default_registry(), work_dir=str(tmp_path),
                 hook_engine=engine)


def test_agent_hook_engine_none_safe(tmp_path):
    agent = _agent(tmp_path)
    assert agent.hook_engine is None
    ctx = agent._build_hook_context("turn_start")
    assert ctx.event_name == "turn_start"
    assert agent._drain_hook_events() == []
    assert asyncio.run(agent._emit_hooks("turn_start", ctx)) == []


def test_agent_drain_hook_events(tmp_path):
    from aixcode.agent import HookEvent
    from aixcode.hooks.engine import HookNotification

    eng = HookEngine([])
    eng._notifications.append(HookNotification("h1", "turn_start", "out", True))
    agent = _agent(tmp_path, eng)
    events = agent._drain_hook_events()
    assert len(events) == 1
    assert isinstance(events[0], HookEvent)
    assert events[0].hook_id == "h1" and events[0].output == "out"


def test_agent_emit_hooks_runs_and_returns_events(tmp_path):
    eng = HookEngine([Hook("a", "turn_start", Action(type="prompt", message="m"))])
    agent = _agent(tmp_path, eng)
    ctx = agent._build_hook_context("turn_start")
    events = asyncio.run(agent._emit_hooks("turn_start", ctx))
    assert any(e.hook_id == "a" for e in events)


def test_agent_build_hook_context_tool_fields(tmp_path):
    agent = _agent(tmp_path)
    ctx = agent._build_hook_context("pre_tool_use", tool_name="Bash",
                                    tool_args={"command": "ls"})
    assert ctx.tool_name == "Bash" and ctx.tool_args == {"command": "ls"}


# ======================================================================
# T11: Agent loop 集成（pre_tool_use reject 端到端）
# ======================================================================

from aixcode.agent import Agent, ToolResultEvent
from aixcode.conversation import ConversationManager
from aixcode.tools.base import StreamEnd, TextDelta, ToolCallComplete


class _ScriptClient:
    def __init__(self, scripts):
        self._scripts = list(scripts)

    async def stream(self, conversation, tools=None, system=None):
        for event in self._scripts.pop(0):
            yield event


def test_agent_pre_tool_reject_skips_tool(tmp_path):
    raw = [{
        "event": "pre_tool_use",
        "if": 'tool == "Bash" && args.command =~ /rm\\s+-rf/',
        "action": {"type": "prompt", "message": "blocked"},
        "reject": True,
    }]
    engine = HookEngine(load_hooks(raw))
    client = _ScriptClient([
        [ToolCallComplete("c1", "Bash", {"command": "rm -rf /"}), StreamEnd(1, 1)],
        [TextDelta("已停手"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path),
                  hook_engine=engine)

    async def go():
        return [e async for e in agent.run(ConversationManager())]

    events = asyncio.run(go())
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is True
    assert "Hook rejected" in tool_results[0].output
    assert "blocked" in tool_results[0].output


def test_agent_no_engine_still_runs(tmp_path):
    client = _ScriptClient([[TextDelta("hi"), StreamEnd(1, 1)]])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path))
    async def go():
        return [e async for e in agent.run(ConversationManager())]
    events = asyncio.run(go())
    assert any(type(e).__name__ == "LoopComplete" for e in events)


def test_app_accepts_hook_engine(tmp_path):
    from aixcode.app import AixCodeApp

    engine = HookEngine([])
    app = AixCodeApp(_agent(tmp_path), ConversationManager(), model="x", hook_engine=engine)
    assert app.hook_engine is engine
