"""ch13 SubAgent 系统测试。"""

import asyncio

import pytest

from aixcode.agents.parser import (
    VALID_MODELS,
    VALID_PERMISSION_MODES,
    AgentDef,
    AgentParseError,
    parse_agent_file,
    parse_frontmatter,
)


def _write(tmp_path, content, name="a.md"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# --- T1: AgentDef dataclass ---

def test_agentdef_defaults():
    d = AgentDef(agent_type="x", when_to_use="use it", system_prompt="body")
    assert d.agent_type == "x"
    assert d.when_to_use == "use it"
    assert d.system_prompt == "body"
    assert d.model == "inherit"
    assert d.max_turns == 50
    assert d.permission_mode == "default"
    assert d.background is False
    assert d.tools == []
    assert d.disallowed_tools == []
    assert d.file_path is None
    assert d.source == "builtin"


def test_agentdef_lists_independent():
    a = AgentDef(agent_type="a", when_to_use="w", system_prompt="s")
    b = AgentDef(agent_type="b", when_to_use="w", system_prompt="s")
    a.tools.append("ReadFile")
    assert b.tools == []


# --- T2: parse_frontmatter + parse_agent_file + 校验 ---

_VALID = """---
name: explore
description: explore code
tools: [ReadFile, Grep, Glob]
maxTurns: 30
model: deepseek-chat
---
You explore code.
"""


def test_constants():
    assert VALID_MODELS == {"inherit", "deepseek-chat", "deepseek-pro", ""}
    assert VALID_PERMISSION_MODES == {"", "strict", "default", "accept", "bypass"}


def test_parse_frontmatter_valid():
    meta, body = parse_frontmatter(_VALID)
    assert meta["name"] == "explore"
    assert body.strip() == "You explore code."


def test_parse_frontmatter_missing_open():
    with pytest.raises(AgentParseError):
        parse_frontmatter("no frontmatter")


def test_parse_frontmatter_unclosed():
    with pytest.raises(AgentParseError):
        parse_frontmatter("---\nname: x\nbody without close")


def test_parse_frontmatter_non_dict():
    with pytest.raises(AgentParseError):
        parse_frontmatter("---\n- a\n- b\n---\nbody")


def test_parse_agent_file_valid(tmp_path):
    d = parse_agent_file(_write(tmp_path, _VALID), source="project")
    assert d.agent_type == "explore"
    assert d.when_to_use == "explore code"
    assert d.system_prompt.strip() == "You explore code."
    assert d.tools == ["ReadFile", "Grep", "Glob"]
    assert d.max_turns == 30
    assert d.model == "deepseek-chat"
    assert d.source == "project"
    assert d.file_path == _write(tmp_path, _VALID)


def test_parse_agent_file_mappings(tmp_path):
    raw = """---
name: plan
description: plan only
disallowedTools: [Agent, EditFile]
permissionMode: strict
background: true
---
Plan.
"""
    d = parse_agent_file(_write(tmp_path, raw))
    assert d.disallowed_tools == ["Agent", "EditFile"]
    assert d.permission_mode == "strict"
    assert d.background is True
    assert d.source == "builtin"


def test_parse_agent_file_missing_name(tmp_path):
    with pytest.raises(AgentParseError):
        parse_agent_file(_write(tmp_path, "---\ndescription: x\n---\nbody"))


def test_parse_agent_file_missing_description(tmp_path):
    with pytest.raises(AgentParseError):
        parse_agent_file(_write(tmp_path, "---\nname: x\n---\nbody"))


def test_parse_agent_file_invalid_model(tmp_path):
    raw = "---\nname: x\ndescription: d\nmodel: gpt-4\n---\nbody"
    with pytest.raises(AgentParseError):
        parse_agent_file(_write(tmp_path, raw))


def test_parse_agent_file_invalid_permission_mode(tmp_path):
    raw = "---\nname: x\ndescription: d\npermissionMode: nope\n---\nbody"
    with pytest.raises(AgentParseError):
        parse_agent_file(_write(tmp_path, raw))


def test_parse_agent_file_nonpositive_maxturns(tmp_path):
    raw = "---\nname: x\ndescription: d\nmaxTurns: 0\n---\nbody"
    with pytest.raises(AgentParseError):
        parse_agent_file(_write(tmp_path, raw))


def test_parse_agent_file_missing_file(tmp_path):
    with pytest.raises(AgentParseError):
        parse_agent_file(str(tmp_path / "nope.md"))


# --- T3: AgentLoader ---

from aixcode.agents.loader import (  # noqa: E402
    PROJECT_AGENTS_DIR,
    USER_AGENTS_DIR,
    AgentLoader,
)


def test_loader_builtins_present(tmp_path):
    loader = AgentLoader(str(tmp_path))
    agents = loader.load_all()
    assert set(agents) >= {"general-purpose", "plan", "explore"}
    assert loader.get("plan").disallowed_tools == ["Agent", "EditFile", "WriteFile"]
    assert loader.get("plan").model == "deepseek-pro"
    assert loader.get("explore").tools == ["ReadFile", "Grep", "Glob"]


def test_loader_dirs():
    assert PROJECT_AGENTS_DIR == ".aixcode/agents"
    assert USER_AGENTS_DIR == "~/.aixcode/agents"


def test_loader_project_overrides_builtin(tmp_path):
    proj = tmp_path / ".aixcode" / "agents"
    proj.mkdir(parents=True)
    (proj / "plan.md").write_text(
        "---\nname: plan\ndescription: my plan\n---\nMine.", encoding="utf-8"
    )
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    plan = loader.get("plan")
    assert plan.when_to_use == "my plan"
    assert plan.source == "project"


def test_loader_get_unknown(tmp_path):
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    assert loader.get("nope") is None


def test_loader_hot_reload(tmp_path):
    proj = tmp_path / ".aixcode" / "agents"
    proj.mkdir(parents=True)
    f = proj / "custom.md"
    f.write_text("---\nname: custom\ndescription: v1\n---\nBody.", encoding="utf-8")
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    assert loader.get("custom").when_to_use == "v1"
    f.write_text("---\nname: custom\ndescription: v2\n---\nBody.", encoding="utf-8")
    assert loader.get("custom").when_to_use == "v2"


def test_loader_hot_reload_fallback(tmp_path):
    proj = tmp_path / ".aixcode" / "agents"
    proj.mkdir(parents=True)
    f = proj / "custom.md"
    f.write_text("---\nname: custom\ndescription: v1\n---\nBody.", encoding="utf-8")
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    f.write_text("broken no frontmatter", encoding="utf-8")
    assert loader.get("custom").when_to_use == "v1"


def test_loader_skips_bad_file(tmp_path):
    proj = tmp_path / ".aixcode" / "agents"
    proj.mkdir(parents=True)
    (proj / "good.md").write_text(
        "---\nname: good\ndescription: ok\n---\nBody.", encoding="utf-8"
    )
    (proj / "bad.md").write_text("garbage", encoding="utf-8")
    loader = AgentLoader(str(tmp_path))
    agents = loader.load_all()
    assert "good" in agents
    assert "bad" not in agents


def test_loader_catalog(tmp_path):
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    catalog = loader.get_catalog()
    names = [n for n, _ in catalog]
    assert "explore" in names


def test_loader_source_label(tmp_path):
    loader = AgentLoader(str(tmp_path))
    loader.load_all()
    assert loader.get_source_label("plan") == "builtin"


# --- T4: 四层工具过滤 ---

from aixcode.agents.parser import AgentDef as _AD  # noqa: E402
from aixcode.agents.tool_filter import (  # noqa: E402
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    resolve_agent_tools,
)
from aixcode.tools import ToolRegistry  # noqa: E402
from aixcode.tools.base import Tool, ToolResult  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class _FakeParams(BaseModel):
    pass


def _make_tool(tool_name, cat="read"):
    class _T(Tool):
        name = tool_name
        description = tool_name
        params_model = _FakeParams
        category = cat

        async def execute(self, params):
            return ToolResult(tool_name)

    return _T()


def _full_registry():
    reg = ToolRegistry()
    for n in [
        "ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep",
        "ToolSearch", "AskUser", "LoadSkill", "Agent", "mcp_foo",
    ]:
        reg.register(_make_tool(n, "command" if n == "Bash" else "read"))
    return reg


def test_tool_filter_constants():
    assert ALL_AGENT_DISALLOWED_TOOLS == frozenset({"Agent", "AskUser"})
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == frozenset({"LoadSkill"})
    assert ASYNC_AGENT_ALLOWED_TOOLS == frozenset(
        {"ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep",
         "ToolSearch", "LoadSkill"}
    )


def test_filter_global_disallowed():
    d = _AD("x", "w", "s", source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert "Agent" not in names
    assert "AskUser" not in names
    assert "ReadFile" in names


def test_filter_mcp_passthrough():
    d = _AD("x", "w", "s", tools=["ReadFile"], source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert "mcp_foo" in names  # MCP 不受白名单约束
    assert "ReadFile" in names
    assert "Grep" not in names  # 白名单外被排除


def test_filter_definition_tools_whitelist():
    d = _AD("x", "w", "s", tools=["ReadFile", "Grep"], source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert names == {"ReadFile", "Grep", "mcp_foo"}


def test_filter_definition_disallowed():
    d = _AD("x", "w", "s", disallowed_tools=["WriteFile"], source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert "WriteFile" not in names
    assert "ReadFile" in names


def test_filter_background_whitelist():
    d = _AD("x", "w", "s", source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=True)
    names = {t.name for t in out.list_tools()}
    assert "ToolSearch" in names
    assert "mcp_foo" in names
    # AskUser 不在异步白名单（且被全局禁），且非白名单工具被排除
    assert "AskUser" not in names


def test_filter_custom_disallows_loadskill():
    d = _AD("x", "w", "s", source="project")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert "LoadSkill" not in names


def test_filter_builtin_keeps_loadskill():
    d = _AD("x", "w", "s", source="builtin")
    out = resolve_agent_tools(_full_registry(), d, is_background=False)
    names = {t.name for t in out.list_tools()}
    assert "LoadSkill" in names


def test_filter_returns_new_registry():
    reg = _full_registry()
    d = _AD("x", "w", "s", source="builtin")
    out = resolve_agent_tools(reg, d, is_background=False)
    assert out is not reg


# --- T5: Fork ---

from aixcode.agents.fork import (  # noqa: E402
    FORK_BOILERPLATE,
    FORK_BOILERPLATE_TAG,
    ForkError,
    build_forked_messages,
)
from aixcode.conversation import ConversationManager  # noqa: E402


def test_fork_constants():
    assert FORK_BOILERPLATE_TAG == "<fork_boilerplate>"
    assert FORK_BOILERPLATE_TAG in FORK_BOILERPLATE


def test_fork_basic_appends_task():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.add_assistant_message("hello")
    forked = build_forked_messages(conv, "do X")
    last = forked.history[-1]
    assert last.role == "user"
    assert "do X" in last.content
    assert FORK_BOILERPLATE_TAG in last.content


def test_fork_preserves_history():
    conv = ConversationManager()
    conv.add_user_message("hi")
    conv.add_assistant_message("hello")
    forked = build_forked_messages(conv, "task")
    assert forked.history[0].content == "hi"
    assert forked.history[1].content == "hello"


def test_fork_deepcopy_does_not_mutate_parent():
    conv = ConversationManager()
    conv.add_user_message("hi")
    before = len(conv.history)
    build_forked_messages(conv, "task")
    assert len(conv.history) == before


def test_fork_fills_interrupted_placeholder():
    conv = ConversationManager()
    conv.add_assistant_message(
        "calling", tool_calls=[{"id": "call_1", "type": "function",
                                "function": {"name": "Bash", "arguments": "{}"}}]
    )
    forked = build_forked_messages(conv, "task")
    tool_msgs = [m for m in forked.history if m.role == "tool"]
    assert any(m.tool_call_id == "call_1" and m.content == "interrupted"
               for m in tool_msgs)


def test_fork_nested_rejected():
    conv = ConversationManager()
    conv.add_user_message(f"earlier {FORK_BOILERPLATE_TAG} marker")
    with pytest.raises(ForkError):
        build_forked_messages(conv, "task")


# --- T6: TraceManager ---

from aixcode.agents.trace import TraceManager, TraceNode  # noqa: E402


def test_trace_create_generates_id():
    tm = TraceManager()
    node = tm.create("explore")
    assert isinstance(node, TraceNode)
    assert len(node.agent_id) == 12
    assert node.trace_id  # 自动生成
    assert node.agent_type == "explore"


def test_trace_create_inherits_trace_id():
    tm = TraceManager()
    root = tm.create("plan")
    child = tm.create("explore", parent_id=root.agent_id, trace_id=root.trace_id)
    assert child.trace_id == root.trace_id
    assert child.parent_id == root.agent_id


def test_trace_update():
    tm = TraceManager()
    node = tm.create("x")
    tm.update(node.agent_id, input_tokens=100, output_tokens=50)
    assert node.input_tokens == 100
    assert node.output_tokens == 50


def test_trace_complete_writes_end_time():
    tm = TraceManager()
    node = tm.create("x")
    assert node.end_time is None
    tm.complete(node.agent_id, "completed")
    assert node.status == "completed"
    assert node.end_time is not None


def test_trace_get_tree():
    tm = TraceManager()
    root = tm.create("plan")
    tm.create("explore", parent_id=root.agent_id, trace_id=root.trace_id)
    tm.create("other")  # 不同 trace
    tree = tm.get_tree(root.trace_id)
    assert len(tree) == 2


def test_trace_get_total_tokens():
    tm = TraceManager()
    root = tm.create("plan")
    tm.update(root.agent_id, input_tokens=10, output_tokens=5)
    child = tm.create("explore", parent_id=root.agent_id, trace_id=root.trace_id)
    tm.update(child.agent_id, input_tokens=20, output_tokens=7)
    assert tm.get_total_tokens(root.trace_id) == (30, 12)


def test_trace_noop_on_unknown():
    tm = TraceManager()
    tm.update("nope", input_tokens=1)  # no error
    tm.complete("nope", "completed")  # no error
    assert tm.get_tree("nope") == []
    assert tm.get_total_tokens("nope") == (0, 0)


# --- T7: TaskManager ---

from aixcode.agents.task_manager import BackgroundTask, TaskManager  # noqa: E402


def test_task_launch_completes():
    async def scenario():
        tm = TaskManager()

        async def work():
            return "done result"

        task_id = tm.launch(work, "explore")
        assert isinstance(task_id, str)
        await tm._async_tasks[task_id]
        task = tm.get(task_id)
        assert task.status == "completed"
        assert task.result == "done result"

    asyncio.run(scenario())


def test_task_launch_tuple_tokens():
    async def scenario():
        tm = TaskManager()

        async def work():
            return ("text", 12, 7)

        task_id = tm.launch(work, "explore")
        await tm._async_tasks[task_id]
        task = tm.get(task_id)
        assert task.result == "text"
        assert task.input_tokens == 12
        assert task.output_tokens == 7

    asyncio.run(scenario())


def test_task_poll_completed_drains():
    async def scenario():
        tm = TaskManager()

        async def work():
            return "r"

        tid = tm.launch(work, "x")
        await tm._async_tasks[tid]
        first = tm.poll_completed()
        assert len(first) == 1 and first[0].task_id == tid
        assert tm.poll_completed() == []  # 抽空

    asyncio.run(scenario())


def test_task_failed():
    async def scenario():
        tm = TaskManager()

        async def work():
            raise RuntimeError("boom")

        tid = tm.launch(work, "x")
        await tm._async_tasks[tid]
        task = tm.get(tid)
        assert task.status == "failed"
        assert "boom" in task.error

    asyncio.run(scenario())


def test_task_cancel():
    async def scenario():
        tm = TaskManager()

        async def work():
            await asyncio.sleep(10)
            return "never"

        tid = tm.launch(work, "x")
        await asyncio.sleep(0)  # 让任务起跑
        assert tm.cancel(tid) is True
        try:
            await tm._async_tasks[tid]
        except asyncio.CancelledError:
            pass
        assert tm.get(tid).status == "cancelled"

    asyncio.run(scenario())


def test_task_list_tasks():
    async def scenario():
        tm = TaskManager()

        async def work():
            return "r"

        tm.launch(work, "a")
        tm.launch(work, "b")
        assert isinstance(tm.list_tasks(), list)
        assert len(tm.list_tasks()) == 2

    asyncio.run(scenario())


def test_backgroundtask_fields():
    t = BackgroundTask(task_id="t1", agent_type="x", status="running")
    assert t.task_id == "t1"
    assert t.result is None
    assert t.error is None


# --- T8: notification ---

from aixcode.agents.notification import (  # noqa: E402
    MAX_NOTIFICATION_RESULT_LENGTH,
    format_task_notification,
    inject_task_notifications,
)


def test_notification_format_fields():
    t = BackgroundTask(
        task_id="abc123", agent_type="explore", status="completed",
        result="the findings", input_tokens=10, output_tokens=5,
        start_time=100.0, end_time=103.5,
    )
    out = format_task_notification(t)
    assert "<task-notification>" in out
    assert "</task-notification>" in out
    assert "abc123" in out
    assert "explore" in out
    assert "completed" in out
    assert "the findings" in out


def test_notification_truncates_long_result():
    t = BackgroundTask(
        task_id="t", agent_type="x", status="completed",
        result="A" * (MAX_NOTIFICATION_RESULT_LENGTH + 100),
    )
    out = format_task_notification(t)
    assert "(truncated)" in out
    assert len(out) < MAX_NOTIFICATION_RESULT_LENGTH + 500


def test_inject_task_notifications_appends():
    conv = ConversationManager()
    before = len(conv.history)
    tasks = [
        BackgroundTask(task_id="t1", agent_type="x", status="completed", result="r1"),
        BackgroundTask(task_id="t2", agent_type="y", status="failed", error="e"),
    ]
    inject_task_notifications(conv, tasks)
    assert len(conv.history) == before + 2
    assert conv.history[-1].role == "user"


# --- T9: AgentToolParams + AgentTool 壳 + 辅助 ---

from aixcode.agent import LoopComplete, StreamText  # noqa: E402
from aixcode.config import ProviderConfig  # noqa: E402
from aixcode.tools.agent_tool import (  # noqa: E402
    PERMISSION_MODE_MAP,
    AgentTool,
    AgentToolParams,
    run_to_completion,
)


def _provider():
    return ProviderConfig(
        protocol="openai", model="deepseek-chat",
        base_url="https://api.deepseek.com", api_key="sk-test",
    )


class _FakeLoader:
    def get_catalog(self):
        return [
            ("general-purpose", "general"),
            ("plan", "planning"),
            ("explore", "exploring"),
        ]

    def get(self, name):
        return None


def _make_agent_tool(enable_fork=False):
    return AgentTool(
        agent_loader=_FakeLoader(),
        task_manager=TaskManager(),
        trace_manager=TraceManager(),
        parent_agent=object(),
        provider_config=_provider(),
        enable_fork=enable_fork,
    )


def test_agenttoolparams_required():
    p = AgentToolParams(prompt="do it", description="desc")
    assert p.prompt == "do it"
    assert p.subagent_type == ""
    assert p.model == ""
    assert p.run_in_background is False


def test_agenttoolparams_missing_required():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentToolParams(prompt="only")


def test_agenttool_attributes():
    assert AgentTool.name == "Agent"
    assert AgentTool.category == "command"
    assert AgentTool.is_concurrency_safe is False


def test_agenttool_description_lists_types():
    tool = _make_agent_tool()
    assert "general-purpose" in tool.description
    assert "plan" in tool.description
    assert "explore" in tool.description


def test_permission_mode_map_reuses_parse():
    from aixcode.permissions import PermissionMode
    assert PERMISSION_MODE_MAP("strict") == PermissionMode.STRICT
    assert PERMISSION_MODE_MAP("bypass") == PermissionMode.BYPASS


def test_run_to_completion_returns_loopcomplete_text():
    class _StubAgent:
        async def run(self, conversation):
            yield StreamText("partial ")
            yield LoopComplete("final answer")

    async def scenario():
        conv = ConversationManager()
        return await run_to_completion(_StubAgent(), conv)

    assert asyncio.run(scenario()) == "final answer"


def test_select_model_priority():
    tool = _make_agent_tool()
    d_inherit = _AD("x", "w", "s", model="inherit")
    d_pro = _AD("x", "w", "s", model="deepseek-pro")
    # params.model 最高优先
    assert tool._select_model(
        AgentToolParams(prompt="p", description="d", model="deepseek-chat"), d_pro
    ) == "deepseek-chat"
    # 次：definition.model（非 inherit）
    assert tool._select_model(
        AgentToolParams(prompt="p", description="d"), d_pro
    ) == "deepseek-pro"
    # inherit → None
    assert tool._select_model(
        AgentToolParams(prompt="p", description="d"), d_inherit
    ) is None


def test_create_client_for_model_swaps_model():
    tool = _make_agent_tool()
    client = tool._create_client_for_model("deepseek-pro")
    assert client._model == "deepseek-pro"


# --- T10: AgentTool.execute 三路径 ---

import aixcode.tools.agent_tool as agent_tool_mod  # noqa: E402


class _Loader2:
    def __init__(self, agents):
        self._agents = agents

    def get_catalog(self):
        return [(n, "use") for n in self._agents]

    def get(self, name):
        return self._agents.get(name)


class _Parent:
    def __init__(self, registry, conv=None):
        self.registry = registry
        self.client = object()
        self.hook_engine = None
        self.work_dir = "."
        self.context_window = 1000
        self.permission_checker = None
        self.active_conversation = conv


def _tool_with(loader, parent, enable_fork=False):
    return AgentTool(
        agent_loader=loader,
        task_manager=TaskManager(),
        trace_manager=TraceManager(),
        parent_agent=parent,
        provider_config=_provider(),
        enable_fork=enable_fork,
    )


def test_execute_unknown_subagent_type():
    tool = _tool_with(_Loader2({"explore": _AD("explore", "w", "s")}),
                      _Parent(_full_registry()))

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="p", description="d", subagent_type="nope")
        )

    res = asyncio.run(scenario())
    assert res.is_error
    assert "explore" in res.output


def test_execute_fork_disabled():
    tool = _tool_with(_Loader2({}), _Parent(_full_registry()), enable_fork=False)

    async def scenario():
        return await tool.execute(AgentToolParams(prompt="p", description="d"))

    res = asyncio.run(scenario())
    assert res.is_error


def test_execute_sync_returns_text(monkeypatch):
    loader = _Loader2({"explore": _AD("explore", "w", "s", model="inherit")})
    tool = _tool_with(loader, _Parent(_full_registry()))
    monkeypatch.setattr(tool, "_build_sub_agent",
                        lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "SYNC TEXT"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="explore")
        )

    res = asyncio.run(scenario())
    assert not res.is_error
    assert "SYNC TEXT" in res.output


def test_execute_background_returns_task_id(monkeypatch):
    loader = _Loader2({"explore": _AD("explore", "w", "s")})
    tool = _tool_with(loader, _Parent(_full_registry()))
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "BG"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        res = await tool.execute(
            AgentToolParams(prompt="go", description="d",
                            subagent_type="explore", run_in_background=True)
        )
        await asyncio.sleep(0)
        return res

    res = asyncio.run(scenario())
    assert "Task ID:" in res.output


def test_execute_definition_background_forced(monkeypatch):
    loader = _Loader2({"bg": _AD("bg", "w", "s", background=True)})
    tool = _tool_with(loader, _Parent(_full_registry()))
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "x"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        res = await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="bg")
        )
        await asyncio.sleep(0)
        return res

    res = asyncio.run(scenario())
    assert "Task ID:" in res.output  # background=true 强制后台


def test_execute_sync_trace_completed(monkeypatch):
    loader = _Loader2({"explore": _AD("explore", "w", "s")})
    tool = _tool_with(loader, _Parent(_full_registry()))
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "t"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="explore")
        )

    asyncio.run(scenario())
    nodes = [n for tid in tool.trace_manager.list_traces()
             for n in tool.trace_manager.get_tree(tid)]
    assert any(n.status == "completed" for n in nodes)


def test_execute_fork_path(monkeypatch):
    conv = ConversationManager()
    conv.add_user_message("earlier context")
    tool = _tool_with(_Loader2({}), _Parent(_full_registry(), conv=conv),
                      enable_fork=True)
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "FORKED"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        res = await tool.execute(AgentToolParams(prompt="investigate", description="d"))
        await asyncio.sleep(0)
        return res

    res = asyncio.run(scenario())
    assert "Task ID:" in res.output  # fork 强制后台


class _StubSub:
    total_input_tokens = 3
    total_output_tokens = 1


# --- T11: /tasks + /trace 命令 ---

from aixcode.commands.handlers.tasks import TASKS_COMMAND  # noqa: E402
from aixcode.commands.handlers.trace import TRACE_COMMAND  # noqa: E402
from aixcode.commands.registry import CommandContext  # noqa: E402


class _CapUI:
    def __init__(self):
        self.messages = []

    def add_system_message(self, text):
        self.messages.append(text)

    async def send_user_message(self, text):
        pass

    def set_plan_mode(self, on):
        pass

    def get_token_count(self):
        return 0

    def refresh_status(self):
        pass


def _cmd_ctx(args, config):
    ui = _CapUI()
    ctx = CommandContext(
        args=args, agent=None, conversation=None, session=None,
        session_manager=None, memory_manager=None, ui=ui, config=config,
    )
    return ctx, ui


def test_commands_in_all_commands():
    from aixcode.commands.handlers import ALL_COMMANDS
    names = {c.name for c in ALL_COMMANDS}
    assert "tasks" in names
    assert "trace" in names


def test_tasks_list():
    tm = TaskManager()
    tm._tasks["t1"] = BackgroundTask(
        task_id="t1", agent_type="explore", status="completed",
        input_tokens=10, output_tokens=5,
    )
    ctx, ui = _cmd_ctx("list", {"task_manager": tm})
    asyncio.run(TASKS_COMMAND.handler(ctx))
    joined = "\n".join(ui.messages)
    assert "t1" in joined
    assert "explore" in joined


def test_tasks_view():
    tm = TaskManager()
    tm._tasks["t1"] = BackgroundTask(
        task_id="t1", agent_type="explore", status="completed", result="the result",
    )
    ctx, ui = _cmd_ctx("view t1", {"task_manager": tm})
    asyncio.run(TASKS_COMMAND.handler(ctx))
    assert "the result" in "\n".join(ui.messages)


def test_tasks_cancel():
    class _TM:
        def __init__(self):
            self.cancelled = None

        def cancel(self, tid):
            self.cancelled = tid
            return True

    tm = _TM()
    ctx, ui = _cmd_ctx("cancel t9", {"task_manager": tm})
    asyncio.run(TASKS_COMMAND.handler(ctx))
    assert tm.cancelled == "t9"


def test_tasks_missing_manager():
    ctx, ui = _cmd_ctx("list", {})
    asyncio.run(TASKS_COMMAND.handler(ctx))
    assert ui.messages  # 友好提示而非崩溃


def test_trace_lists_tree():
    tmgr = TraceManager()
    root = tmgr.create("plan")
    tmgr.update(root.agent_id, input_tokens=10, output_tokens=5)
    tmgr.create("explore", parent_id=root.agent_id, trace_id=root.trace_id)
    ctx, ui = _cmd_ctx(root.trace_id, {"trace_manager": tmgr})
    asyncio.run(TRACE_COMMAND.handler(ctx))
    joined = "\n".join(ui.messages)
    assert "plan" in joined
    assert "explore" in joined


def test_trace_no_arg_lists_recent():
    tmgr = TraceManager()
    tmgr.create("plan")
    ctx, ui = _cmd_ctx("", {"trace_manager": tmgr})
    asyncio.run(TRACE_COMMAND.handler(ctx))
    assert ui.messages


# --- T12: 接入 app.py + __main__.py ---

import io  # noqa: E402

from rich.console import Console  # noqa: E402

from aixcode.app import AixCodeApp  # noqa: E402


class _MiniAgent:
    def __init__(self):
        from aixcode.permissions import PermissionMode
        self.permission_mode = PermissionMode.DEFAULT
        self.memory_manager = None

        class _Reg:
            def list_tools(self):
                return []

        self.registry = _Reg()

    def set_permission_mode(self, mode):
        self.permission_mode = mode


def _app(task_manager=None, trace_manager=None):
    app = AixCodeApp(
        _MiniAgent(), ConversationManager(), model="deepseek-chat",
        task_manager=task_manager, trace_manager=trace_manager,
    )
    app.console = Console(file=io.StringIO(), record=True, width=120)
    return app


def test_app_stores_managers():
    tm, tr = TaskManager(), TraceManager()
    app = _app(tm, tr)
    assert app.task_manager is tm
    assert app.trace_manager is tr


def test_app_context_has_managers():
    tm, tr = TaskManager(), TraceManager()
    app = _app(tm, tr)
    ctx = app._build_command_context("")
    assert ctx.config["task_manager"] is tm
    assert ctx.config["trace_manager"] is tr


def test_app_backward_compatible_without_managers():
    app = _app()
    assert app.task_manager is None
    app._inject_completed_tasks()  # 不应抛


def test_app_inject_completed_tasks():
    async def scenario():
        tm = TaskManager()

        async def work():
            return "background done"

        tid = tm.launch(work, "explore")
        await tm._async_tasks[tid]
        app = _app(tm, None)
        app._inject_completed_tasks()
        return app

    app = asyncio.run(scenario())
    joined = "\n".join(m.content for m in app.conversation.history)
    assert "background done" in joined


def test_app_adopts_running_turn_on_interrupt():
    async def scenario():
        started = asyncio.Event()

        class _SlowAgent(_MiniAgent):
            async def run(self, conversation):
                started.set()
                await asyncio.sleep(10)
                yield  # 不会到这

        tm = TaskManager()
        app = AixCodeApp(_SlowAgent(), ConversationManager(),
                         task_manager=tm)
        app.console = Console(file=io.StringIO(), record=True)
        runner = asyncio.ensure_future(app._run_turn("go"))
        await started.wait()
        await asyncio.sleep(0)
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass
        # 中断后被 adopt 为后台任务而非杀掉
        adopted = tm.list_tasks()
        # 清理：取消挂起的后台任务
        for t in adopted:
            tm.cancel(t.task_id)
        return adopted

    adopted = asyncio.run(scenario())
    assert len(adopted) == 1
    assert adopted[0].agent_type == "main-turn"
