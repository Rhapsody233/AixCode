"""ch15 AgentTeam 系统测试（纯 pytest 函数 + asyncio.run，不用测试类）。"""

import asyncio

import pytest

# --- T1: 核心模型 -----------------------------------------------------------

from aixcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    _sanitize_name,
    resolve_team_dir,
    unique_team_name,
)


def test_backend_type_values():
    assert BackendType.TMUX.value == "tmux"
    assert BackendType.ITERM2.value == "iterm2"
    assert BackendType.IN_PROCESS.value == "in-process"


def test_teammate_info_tristate_default():
    t = TeammateInfo(name="alice", agent_id="a1")
    assert t.is_active is None
    assert t.agent_type == ""
    assert t.model == ""
    assert t.worktree_path == ""
    assert t.backend_type == ""


def test_teammate_info_all_fields():
    t = TeammateInfo(
        name="bob", agent_id="b1", agent_type="explore", model="deepseek-chat",
        worktree_path="/tmp/wt", backend_type="in-process", is_active=False,
    )
    assert t.is_active is False
    assert t.worktree_path == "/tmp/wt"


def test_agentteam_get_member_by_name_and_id():
    team = AgentTeam(name="t", lead_agent_id="lead")
    team.add_member(TeammateInfo(name="alice", agent_id="a1"))
    assert team.get_member("alice").agent_id == "a1"
    assert team.get_member("a1").name == "alice"
    assert team.get_member("nope") is None


def test_agentteam_set_active_and_idle():
    team = AgentTeam(name="t", lead_agent_id="lead")
    team.add_member(TeammateInfo(name="alice", agent_id="a1"))
    team.add_member(TeammateInfo(name="bob", agent_id="b1"))
    assert team.all_idle() is False  # 默认 None 视为 active
    assert len(team.active_members()) == 2
    team.set_member_active("alice", False)
    team.set_member_active("bob", False)
    assert team.all_idle() is True
    assert team.active_members() == []


def test_agentteam_remove_member_no_tombstone():
    team = AgentTeam(name="t", lead_agent_id="lead")
    team.add_member(TeammateInfo(name="alice", agent_id="a1"))
    team.remove_member("alice")
    assert team.members == []
    assert team.get_member("alice") is None


def test_agentteam_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    cfg = resolve_team_dir("My Team") / "config.json"
    team = AgentTeam(
        name="my-team", lead_agent_id="lead", config_path=str(cfg),
        description="desc",
    )
    team.add_member(TeammateInfo(name="alice", agent_id="a1", is_active=False))
    team.save()
    loaded = AgentTeam.load(str(cfg))
    assert loaded.name == "my-team"
    assert loaded.lead_agent_id == "lead"
    assert loaded.description == "desc"
    assert len(loaded.members) == 1
    assert loaded.members[0].name == "alice"
    assert loaded.members[0].is_active is False


def test_sanitize_name():
    assert _sanitize_name("My Team!") == "my-team"
    assert _sanitize_name("refactor-X") == "refactor-x"


def test_resolve_team_dir_uses_home(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    d = resolve_team_dir("refactor X")
    assert d == tmp_path / ".aixcode" / "teams" / "refactor-x"


def test_unique_team_name_adds_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    assert unique_team_name("alpha") == "alpha"
    (tmp_path / ".aixcode" / "teams" / "alpha").mkdir(parents=True)
    assert unique_team_name("alpha") == "alpha-2"
    (tmp_path / ".aixcode" / "teams" / "alpha-2").mkdir(parents=True)
    assert unique_team_name("alpha") == "alpha-3"


# --- T2: Mailbox + MailboxMessage + create_message --------------------------

from aixcode.teams.mailbox import Mailbox, MailboxMessage, create_message


def test_create_message_autofills():
    m = create_message("alice", "bob", "hello", summary="greeting")
    assert len(m.id) == 12
    assert m.timestamp > 0
    assert m.from_agent == "alice"
    assert m.to_agent == "bob"
    assert m.content == "hello"
    assert m.summary == "greeting"
    assert m.message_type == "text"
    assert m.metadata == {}


def test_mailbox_write_read_roundtrip(tmp_path):
    mb = Mailbox(str(tmp_path / "mailbox"))
    msg = create_message("alice", "b1", "hi there", summary="s")
    mb.write("b1", msg)
    got = mb.read("b1")
    assert len(got) == 1
    assert got[0].content == "hi there"
    assert got[0].id == msg.id


def test_mailbox_consume_fifo_and_delete(tmp_path):
    mb = Mailbox(str(tmp_path / "mailbox"))
    mb.write("b1", create_message("a", "b1", "first", summary="s"))
    mb.write("b1", create_message("a", "b1", "second", summary="s"))
    consumed = mb.consume("b1")
    assert [m.content for m in consumed] == ["first", "second"]
    assert mb.read("b1") == []  # consume 后清空


def test_mailbox_broadcast_excludes(tmp_path):
    mb = Mailbox(str(tmp_path / "mailbox"))
    msg = create_message("alice", "*", "all hands", summary="s")
    mb.broadcast(["a1", "b1", "c1"], msg, exclude="a1")
    assert mb.read("a1") == []
    assert len(mb.read("b1")) == 1
    assert len(mb.read("c1")) == 1


def test_mailbox_cleanup(tmp_path):
    mb = Mailbox(str(tmp_path / "mailbox"))
    mb.write("b1", create_message("a", "b1", "x", summary="s"))
    mb.write("c1", create_message("a", "c1", "y", summary="s"))
    mb.cleanup("b1")
    assert mb.read("b1") == []
    assert len(mb.read("c1")) == 1
    mb.cleanup_all()
    assert mb.read("c1") == []


# --- T3: detect_backend 优先级链 -------------------------------------------

from aixcode.teams import backend_detect
from aixcode.teams.backend_detect import BackendDetectionError, detect_backend


def _clear_backend_env(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "")
    monkeypatch.setattr(backend_detect.shutil, "which", lambda name: None)


def test_detect_in_process_via_mode(monkeypatch):
    _clear_backend_env(monkeypatch)
    assert detect_backend("in-process", True) == BackendType.IN_PROCESS


def test_detect_in_process_via_noninteractive(monkeypatch):
    _clear_backend_env(monkeypatch)
    assert detect_backend("", False) == BackendType.IN_PROCESS


def test_detect_tmux_env(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    assert detect_backend("", True) == BackendType.TMUX


def test_detect_iterm2(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(
        backend_detect.shutil, "which", lambda name: "/usr/bin/it2" if name == "it2" else None
    )
    assert detect_backend("", True) == BackendType.ITERM2


def test_detect_tmux_installed(monkeypatch):
    _clear_backend_env(monkeypatch)
    monkeypatch.setattr(
        backend_detect.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None
    )
    assert detect_backend("", True) == BackendType.TMUX


def test_detect_raises_when_nothing(monkeypatch):
    _clear_backend_env(monkeypatch)
    with pytest.raises(BackendDetectionError) as ei:
        detect_backend("", True)
    assert "in-process" in str(ei.value)


# --- T4: SharedTaskStore + SharedTask ---------------------------------------

from aixcode.teams.shared_task import SharedTask, SharedTaskStore


def test_sharedtask_defaults():
    t = SharedTask(id=1, title="x")
    assert t.status == "pending"
    assert t.blocks == []
    assert t.blocked_by == []
    assert t.assignee == ""
    assert t.created_by == ""


def test_store_create_autoincrement(tmp_path):
    s = SharedTaskStore(str(tmp_path / "tasks.json"))
    s.init_empty()
    a = s.create("first", created_by="lead")
    b = s.create("second", created_by="lead")
    assert a.id == 1
    assert b.id == 2
    assert a.created_by == "lead"


def test_store_get_hit_miss(tmp_path):
    s = SharedTaskStore(str(tmp_path / "tasks.json"))
    s.init_empty()
    t = s.create("x")
    assert s.get(t.id).title == "x"
    assert s.get(999) is None


def test_store_list_filters(tmp_path):
    s = SharedTaskStore(str(tmp_path / "tasks.json"))
    s.init_empty()
    s.create("a", assignee="alice")
    s.create("b", assignee="bob")
    t = s.create("c", assignee="alice")
    s.update(t.id, status="in_progress")
    assert len(s.list_tasks()) == 3
    assert len(s.list_tasks(assignee="alice")) == 2
    assert len(s.list_tasks(status="in_progress")) == 1
    assert len(s.list_tasks(status="in_progress", assignee="alice")) == 1
    assert len(s.list_tasks(status="in_progress", assignee="bob")) == 0


def test_store_update_status_and_add_blocks(tmp_path):
    s = SharedTaskStore(str(tmp_path / "tasks.json"))
    s.init_empty()
    t = s.create("x")
    s.update(t.id, status="completed", add_blocks=[2, 3])
    s.update(t.id, add_blocks=[3, 4])  # 去重追加
    got = s.get(t.id)
    assert got.status == "completed"
    assert got.blocks == [2, 3, 4]


def test_store_init_empty_resets(tmp_path):
    s = SharedTaskStore(str(tmp_path / "tasks.json"))
    s.init_empty()
    s.create("x")
    s.init_empty()
    assert s.list_tasks() == []
    assert s.create("y").id == 1  # next_id 重置


def test_store_persists_across_instances(tmp_path):
    path = str(tmp_path / "tasks.json")
    s1 = SharedTaskStore(path)
    s1.init_empty()
    s1.create("persisted")
    s2 = SharedTaskStore(path)
    assert len(s2.list_tasks()) == 1
    assert s2.list_tasks()[0].title == "persisted"


# --- T5: AgentNameRegistry 单例 ---------------------------------------------

from aixcode.teams.registry import AgentNameRegistry


@pytest.fixture(autouse=True)
def _reset_name_registry():
    """每个用例前清单例，避免 register 状态跨用例泄漏。"""
    AgentNameRegistry.reset()
    yield
    AgentNameRegistry.reset()


def test_registry_register_resolve_by_name():
    r = AgentNameRegistry.instance()
    r.register("alice", "a1")
    assert r.resolve("alice") == "a1"


def test_registry_resolve_by_id_reverse():
    r = AgentNameRegistry.instance()
    r.register("alice", "a1")
    assert r.resolve("a1") == "a1"  # 按 agent_id 反查命中


def test_registry_resolve_unknown_none():
    r = AgentNameRegistry.instance()
    assert r.resolve("nope") is None


def test_registry_unregister():
    r = AgentNameRegistry.instance()
    r.register("alice", "a1")
    r.unregister("alice")
    assert r.resolve("alice") is None


def test_registry_reset_clears():
    r = AgentNameRegistry.instance()
    r.register("alice", "a1")
    AgentNameRegistry.reset()
    assert AgentNameRegistry.instance().resolve("alice") is None


def test_registry_instance_singleton():
    assert AgentNameRegistry.instance() is AgentNameRegistry.instance()


def test_registry_list_all():
    r = AgentNameRegistry.instance()
    r.register("alice", "a1")
    r.register("bob", "b1")
    assert r.list_all() == {"alice": "a1", "bob": "b1"}


# --- T6: spawn_inprocess_teammate + InProcessTeammateHandle -----------------

from aixcode.agent import LoopComplete, StreamText
from aixcode.teams.spawn_inprocess import (
    InProcessTeammateHandle,
    spawn_inprocess_teammate,
)


class _DoneAgent:
    async def run(self, conversation):
        yield StreamText("working ")
        yield LoopComplete("done")


class _SleepAgent:
    async def run(self, conversation):
        await asyncio.sleep(10)
        yield LoopComplete("never")


def test_spawn_inprocess_completes():
    async def scenario():
        agent = _DoneAgent()
        handle = spawn_inprocess_teammate(agent, "do work", "alice")
        assert isinstance(handle, InProcessTeammateHandle)
        assert handle.name == "alice"
        await handle.task
        return handle

    handle = asyncio.run(scenario())
    assert handle.done is True
    assert handle.result == "done"


def test_spawn_inprocess_cancel():
    async def scenario():
        handle = spawn_inprocess_teammate(_SleepAgent(), "p", "bob")
        await asyncio.sleep(0)  # 让任务起跑
        handle.cancel()
        try:
            await handle.task
        except asyncio.CancelledError:
            pass
        return handle

    handle = asyncio.run(scenario())
    assert handle.done is True
    assert handle.result is None  # 取消后安全取结果返 None


# --- T7: spawn_tmux + build_cli_command（mock 测试）-------------------------

import aixcode.teams.spawn_tmux as spawn_tmux
from aixcode.teams.spawn_tmux import build_cli_command


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_cli_command_basic():
    cmd = build_cli_command("refactor-x", "alice", "/mb", "/wt", "do 'it' now")
    assert "AIXCODE_TEAM_NAME=refactor-x" in cmd
    assert "AIXCODE_TEAMMATE_NAME=alice" in cmd
    assert "AIXCODE_MAILBOX_DIR=/mb" in cmd
    assert "python -m aixcode -p" in cmd
    assert "--work-dir /wt" in cmd
    assert "'\\''" in cmd  # 单引号转义为 '\''


def test_build_cli_command_with_flags():
    cmd = build_cli_command(
        "t", "a", "/mb", "/wt", "p", agent_type="explore", model="deepseek-pro"
    )
    assert "--agent-type explore" in cmd
    assert "--model deepseek-pro" in cmd


def test_spawn_tmux_fallback_to_new_window(monkeypatch):
    seq = []

    def fake_run(args):
        verb = args[0]
        seq.append(verb)
        if verb == "split-window":
            if seq.count("split-window") == 1:
                return _FakeProc(returncode=1, stderr="can't find session")
            return _FakeProc(returncode=0, stdout="%2\n")
        if verb == "new-window":
            return _FakeProc(returncode=0, stdout="%1\n")
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(spawn_tmux, "_run_tmux", fake_run)
    info = spawn_tmux.spawn_tmux_teammate("refactor-x", "alice", "/mb", "/wt", "prompt")
    assert info.pane_id == "%2"
    assert seq[0] == "split-window"
    assert seq[1] == "new-window"
    assert seq[2] == "split-window"
    assert "send-keys" in seq


def test_kill_pane_swallows_error(monkeypatch):
    def fake_run(args):
        raise RuntimeError("boom")

    monkeypatch.setattr(spawn_tmux, "_run_tmux", fake_run)
    spawn_tmux.kill_pane("%9")  # 不应抛
    spawn_tmux.send_keys_to_pane("%9", "")  # 不应抛


# --- T8: spawn_iterm2（mock 测试）------------------------------------------

import aixcode.teams.spawn_iterm2 as spawn_iterm2


def test_spawn_iterm2_success(monkeypatch):
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return _FakeProc(returncode=0, stdout="session-abc\n")

    monkeypatch.setattr(spawn_iterm2, "_run_it2", fake_run)
    info = spawn_iterm2.spawn_iterm2_teammate("t", "alice", "/mb", "/wt", "do work")
    assert info.session_id == "session-abc"
    assert "split-pane" in captured["args"]
    joined = " ".join(captured["args"])
    assert "python -m aixcode -p" in joined


def test_spawn_iterm2_failure(monkeypatch):
    def fake_run(args):
        return _FakeProc(returncode=1, stderr="no iterm")

    monkeypatch.setattr(spawn_iterm2, "_run_it2", fake_run)
    with pytest.raises(spawn_iterm2.ITermSpawnError):
        spawn_iterm2.spawn_iterm2_teammate("t", "a", "/mb", "/wt", "p")


# --- T9: transcript 持久化（扁平 Message）----------------------------------

from aixcode.conversation import ConversationManager, Message
from aixcode.teams.transcript import load_transcript, save_transcript


def test_transcript_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    conv = ConversationManager()
    conv.add_user_message("hello")
    conv.add_assistant_message(
        "calling tool",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "Bash", "arguments": "{}"}}],
    )
    conv.add_tool_result("c1", "tool output")
    save_transcript("refactor-x", "a1", conv)

    loaded = load_transcript("refactor-x", "a1")
    assert loaded is not None
    assert len(loaded.history) == 3
    assert loaded.history[0].role == "user"
    assert loaded.history[0].content == "hello"
    assert loaded.history[1].tool_calls[0]["id"] == "c1"
    assert loaded.history[2].role == "tool"
    assert loaded.history[2].tool_call_id == "c1"
    assert loaded.env_injected is True
    assert loaded.ltm_injected is True


def test_transcript_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    assert load_transcript("nope", "missing") is None


# --- T10: TeamManager -------------------------------------------------------

from aixcode.teams.manager import TeamError, TeamManager


def test_create_team_persists_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    team = tm.create_team("refactor X", lead_agent_id="lead", teammate_mode="in-process")
    team_dir = tmp_path / ".aixcode" / "teams" / "refactor-x"
    assert (team_dir / "config.json").is_file()
    assert (team_dir / "tasks.json").is_file()
    assert (team_dir / "mailbox").is_dir()
    assert tm.get_team("refactor-x") is team
    assert tm.get_task_store("refactor-x") is not None
    assert tm.get_mailbox("refactor-x") is not None


def test_manager_detect_backend_cached():
    tm = TeamManager()
    assert tm.detect_backend("in-process", True) == BackendType.IN_PROCESS
    # 第二次即便参数变了也返回缓存值，不再探测
    assert tm.detect_backend("", True) == BackendType.IN_PROCESS


def test_register_member_reverse_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))
    team = tm.get_team_for_teammate("a1")
    assert team is not None and team.name == "t"
    assert AgentNameRegistry.instance().resolve("alice") == "a1"


def test_set_member_idle_writes_lead_mailbox(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))
    tm.set_member_idle("t", "alice")
    assert tm.get_team("t").get_member("alice").is_active is False
    lead_msgs = tm.get_mailbox("t").read("lead")
    assert len(lead_msgs) == 1
    assert "idle" in lead_msgs[0].content.lower()


def test_on_teammate_completed_marks_idle(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))
    tm.on_teammate_completed("a1")
    assert tm.get_team("t").get_member("alice").is_active is False


def test_delete_team_rejects_active(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))  # 默认 active
    with pytest.raises(TeamError):
        asyncio.run(tm.delete_team("t"))


def test_delete_team_clears_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    calls = []

    class _FakeWT:
        async def _remove_worktree(self, slug):
            calls.append(slug)

    class _FakeTrace:
        def complete(self, agent_id, status):
            calls.append(("trace", agent_id))

    tm = TeamManager(worktree_manager=_FakeWT(), trace_manager=_FakeTrace())
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))
    tm.set_member_idle("t", "alice")
    team_dir = tmp_path / ".aixcode" / "teams" / "t"
    assert team_dir.is_dir()

    asyncio.run(tm.delete_team("t"))
    assert tm.get_team("t") is None
    assert tm.get_task_store("t") is None
    assert tm.get_mailbox("t") is None
    assert not team_dir.exists()
    assert "team-t/alice" in calls
    assert AgentNameRegistry.instance().resolve("alice") is None


# --- T11: coordinator + tool_filter 扩展 ------------------------------------

from aixcode.agents.tool_filter import (
    COORDINATOR_MODE_ALLOWED_TOOLS,
    IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
    TEAMMATE_COORDINATION_TOOLS,
    apply_coordinator_filter,
    build_teammate_tools,
)
from aixcode.teams.coordinator import get_coordinator_system_prompt, is_coordinator_mode
from aixcode.tools import ToolRegistry
from aixcode.tools.base import Tool, ToolResult
from pydantic import BaseModel as _BaseModel


class _NoParams(_BaseModel):
    pass


def _mk_tool(tool_name, cat="read"):
    class _T(Tool):
        name = tool_name
        description = tool_name
        params_model = _NoParams
        category = cat

        async def execute(self, params):
            return ToolResult(tool_name)

    return _T()


def _team_registry():
    reg = ToolRegistry()
    for n in [
        "ReadFile", "WriteFile", "EditFile", "Bash", "Glob", "Grep", "ToolSearch",
        "LoadSkill", "AskUser", "Agent", "SendMessage", "TaskCreate", "TaskGet",
        "TaskList", "TaskUpdate", "TeamCreate", "TeamDelete", "mcp_foo",
    ]:
        reg.register(_mk_tool(n, "command" if n == "Bash" else "read"))
    return reg


def test_coordinator_tool_constants():
    assert COORDINATOR_MODE_ALLOWED_TOOLS == frozenset({
        "Agent", "SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
        "TeamCreate", "TeamDelete", "ReadFile", "Glob", "Grep", "Bash",
    })
    assert TEAMMATE_COORDINATION_TOOLS == frozenset({
        "SendMessage", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
    })
    assert "CronCreate" not in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS
    assert "SendMessage" in IN_PROCESS_TEAMMATE_ALLOWED_TOOLS


def test_is_coordinator_mode_double_switch(monkeypatch):
    monkeypatch.setenv("AIXCODE_COORDINATOR_MODE", "1")
    assert is_coordinator_mode(False) is False  # flag 关，恒 False
    assert is_coordinator_mode(True) is True
    monkeypatch.delenv("AIXCODE_COORDINATOR_MODE", raising=False)
    assert is_coordinator_mode(True) is False  # env 缺，False


def test_coordinator_prompt_has_phases():
    p = get_coordinator_system_prompt()
    for kw in ("Research", "Synthesis", "Implementation", "Verification"):
        assert kw in p
    assert "based on your findings" in p


def test_apply_coordinator_filter_whitelist():
    out = apply_coordinator_filter(_team_registry())
    names = {t.name for t in out.list_tools()}
    assert "WriteFile" not in names
    assert "EditFile" not in names
    assert "ReadFile" in names
    assert "mcp_foo" in names  # MCP 直通
    assert names - {"mcp_foo"} <= COORDINATOR_MODE_ALLOWED_TOOLS


def test_build_teammate_tools_in_process():
    out = build_teammate_tools(_team_registry(), BackendType.IN_PROCESS)
    names = {t.name for t in out.list_tools()}
    assert "SendMessage" in names
    assert "TaskCreate" in names
    assert "Agent" not in names
    assert "AskUser" not in names
    assert "mcp_foo" in names


def test_build_teammate_tools_pane():
    out = build_teammate_tools(_team_registry(), BackendType.TMUX)
    names = {t.name for t in out.list_tools()}
    assert "WriteFile" in names  # pane 模式保留写工具
    assert "TeamCreate" not in names
    assert "TeamDelete" not in names


# --- T12: 共享任务工具四件 --------------------------------------------------

from aixcode.tools.task_create import TaskCreateTool
from aixcode.tools.task_get import TaskGetTool
from aixcode.tools.task_list import TaskListTool
from aixcode.tools.task_update import TaskUpdateTool


class _TaskTM:
    def __init__(self, store):
        self._store = store

    def get_task_store(self, team_name):
        return self._store


class _TaskParent:
    def __init__(self, team_name="t", agent_id="lead"):
        self.team_name = team_name
        self.agent_id = agent_id


def _task_tools(tmp_path, team_name="t"):
    store = SharedTaskStore(str(tmp_path / "tasks.json"))
    store.init_empty()
    tm = _TaskTM(store)
    parent = _TaskParent(team_name=team_name)
    return (
        TaskCreateTool(tm, parent),
        TaskGetTool(tm, parent),
        TaskListTool(tm, parent),
        TaskUpdateTool(tm, parent),
        store,
    )


def test_task_create_then_get(tmp_path):
    create, get, _list, _update, _store = _task_tools(tmp_path)

    async def scenario():
        r = await create.execute(create.params_model(title="build X", assignee="alice"))
        assert not r.is_error
        # 任务 id 1
        g = await get.execute(get.params_model(task_id=1))
        return g

    g = asyncio.run(scenario())
    assert not g.is_error
    assert "build X" in g.output
    assert "alice" in g.output


def test_task_create_sets_created_by(tmp_path):
    create, _get, _list, _update, store = _task_tools(tmp_path)

    async def scenario():
        await create.execute(create.params_model(title="x"))

    asyncio.run(scenario())
    assert store.get(1).created_by == "lead"


def test_task_list_filter(tmp_path):
    create, _get, list_tool, update, _store = _task_tools(tmp_path)

    async def scenario():
        await create.execute(create.params_model(title="alpha-task", assignee="alice"))
        await create.execute(create.params_model(title="beta-task", assignee="bob"))
        await update.execute(update.params_model(task_id=1, status="in_progress"))
        return await list_tool.execute(list_tool.params_model(status="in_progress"))

    r = asyncio.run(scenario())
    assert not r.is_error
    assert "alpha-task" in r.output
    assert "beta-task" not in r.output


def test_task_update_changes_status(tmp_path):
    create, get, _list, update, store = _task_tools(tmp_path)

    async def scenario():
        await create.execute(create.params_model(title="x"))
        await update.execute(update.params_model(task_id=1, status="completed"))

    asyncio.run(scenario())
    assert store.get(1).status == "completed"


def test_task_get_missing(tmp_path):
    _create, get, _list, _update, _store = _task_tools(tmp_path)

    async def scenario():
        return await get.execute(get.params_model(task_id=999))

    r = asyncio.run(scenario())
    assert r.is_error


def test_task_tools_no_team(tmp_path):
    create, get, list_tool, update, _store = _task_tools(tmp_path, team_name="")

    async def scenario():
        return [
            await create.execute(create.params_model(title="x")),
            await get.execute(get.params_model(task_id=1)),
            await list_tool.execute(list_tool.params_model()),
            await update.execute(update.params_model(task_id=1, status="done")),
        ]

    results = asyncio.run(scenario())
    assert all(r.is_error for r in results)


def test_task_tool_categories():
    assert TaskCreateTool.category == "write"
    assert TaskUpdateTool.category == "write"
    assert TaskGetTool.category == "read"
    assert TaskListTool.category == "read"


# --- T13: SendMessage / TeamCreate / TeamDelete -----------------------------

from aixcode.tools.send_message import VALID_MESSAGE_TYPES, SendMessageTool
from aixcode.tools.team_create import TeamCreateTool
from aixcode.tools.team_delete import TeamDeleteTool


class _LeadParent:
    def __init__(self, agent_id="lead", registry=None, team_name=""):
        self.agent_id = agent_id
        self.registry = registry
        self.team_name = team_name
        self.coordinator_mode = False


def test_send_message_types_constant():
    assert VALID_MESSAGE_TYPES == {"text", "shutdown_request", "shutdown_response"}


def _send_setup(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))
    tm.register_member("t", TeammateInfo(name="bob", agent_id="b1"))
    parent = _LeadParent(agent_id="lead", team_name="t")
    return tm, SendMessageTool(tm, parent)


def test_send_message_text_requires_summary(tmp_path, monkeypatch):
    tm, tool = _send_setup(tmp_path, monkeypatch)

    async def scenario():
        return await tool.execute(tool.params_model(to="alice", message="hi", summary=""))

    assert asyncio.run(scenario()).is_error


def test_send_message_invalid_type(tmp_path, monkeypatch):
    tm, tool = _send_setup(tmp_path, monkeypatch)

    async def scenario():
        return await tool.execute(
            tool.params_model(to="alice", message="hi", summary="s", message_type="bogus")
        )

    assert asyncio.run(scenario()).is_error


def test_send_message_to_name(tmp_path, monkeypatch):
    tm, tool = _send_setup(tmp_path, monkeypatch)

    async def scenario():
        return await tool.execute(tool.params_model(to="alice", message="hey", summary="s"))

    r = asyncio.run(scenario())
    assert not r.is_error
    msgs = tm.get_mailbox("t").read("a1")
    assert len(msgs) == 1 and msgs[0].content == "hey"


def test_send_message_unknown_recipient(tmp_path, monkeypatch):
    tm, tool = _send_setup(tmp_path, monkeypatch)

    async def scenario():
        return await tool.execute(tool.params_model(to="ghost", message="hi", summary="s"))

    r = asyncio.run(scenario())
    assert r.is_error
    assert "ghost" in r.output


def test_send_message_broadcast(tmp_path, monkeypatch):
    tm, tool = _send_setup(tmp_path, monkeypatch)

    async def scenario():
        return await tool.execute(tool.params_model(to="*", message="all", summary="s"))

    r = asyncio.run(scenario())
    assert not r.is_error
    assert len(tm.get_mailbox("t").read("a1")) == 1
    assert len(tm.get_mailbox("t").read("b1")) == 1
    assert tm.get_mailbox("t").read("lead") == []  # 发送者 lead 被排除


def test_send_message_no_team(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tool = SendMessageTool(tm, _LeadParent(agent_id="lead", team_name=""))

    async def scenario():
        return await tool.execute(tool.params_model(to="alice", message="hi", summary="s"))

    assert asyncio.run(scenario()).is_error


def test_team_create_sets_team_name(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    parent = _LeadParent(agent_id="lead", registry=ToolRegistry())
    tool = TeamCreateTool(tm, parent, teammate_mode="in-process")

    async def scenario():
        return await tool.execute(tool.params_model(team_name="refactor-x"))

    r = asyncio.run(scenario())
    assert not r.is_error
    assert parent.team_name == "refactor-x"
    assert tm.get_team("refactor-x") is not None
    assert "in-process" in r.output


def test_team_create_coordinator_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    monkeypatch.setenv("AIXCODE_COORDINATOR_MODE", "1")
    tm = TeamManager()
    parent = _LeadParent(agent_id="lead", registry=_team_registry())
    tool = TeamCreateTool(
        tm, parent, teammate_mode="in-process", enable_coordinator_mode=True
    )

    async def scenario():
        return await tool.execute(tool.params_model(team_name="t"))

    r = asyncio.run(scenario())
    assert parent.coordinator_mode is True
    assert parent._full_registry is not None
    names = {t.name for t in parent.registry.list_tools()}
    assert "WriteFile" not in names
    assert "ReadFile" in names
    assert "coordinator" in r.output.lower()


def test_team_delete_restores_registry(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    monkeypatch.setenv("AIXCODE_COORDINATOR_MODE", "1")
    tm = TeamManager()
    parent = _LeadParent(agent_id="lead", registry=_team_registry())
    create = TeamCreateTool(
        tm, parent, teammate_mode="in-process", enable_coordinator_mode=True
    )
    delete = TeamDeleteTool(tm, parent)

    async def scenario():
        await create.execute(create.params_model(team_name="t"))
        full = parent._full_registry
        r = await delete.execute(delete.params_model(team_name="t"))
        return r, full

    r, full = asyncio.run(scenario())
    assert not r.is_error
    assert parent.registry is full
    assert parent.coordinator_mode is False
    assert parent.team_name == ""


def test_team_delete_active_member_error(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    parent = _LeadParent(agent_id="lead", registry=ToolRegistry())
    create = TeamCreateTool(tm, parent, teammate_mode="in-process")
    delete = TeamDeleteTool(tm, parent)

    async def scenario():
        await create.execute(create.params_model(team_name="t"))
        tm.register_member("t", TeammateInfo(name="alice", agent_id="a1"))  # active
        return await delete.execute(delete.params_model(team_name="t"))

    assert asyncio.run(scenario()).is_error


# --- T14: AgentTool._execute_as_teammate ------------------------------------

from aixcode.agents.task_manager import TaskManager
from aixcode.agents.trace import TraceManager
from aixcode.config import ProviderConfig
from aixcode.tools.agent_tool import AgentTool, AgentToolParams


class _StubTeammate:
    total_input_tokens = 0
    total_output_tokens = 0

    async def run(self, conversation):
        yield LoopComplete("teammate done")


class _FakeWorktree:
    def __init__(self, path):
        self.path = path
        self.head_commit = "deadbeef"


class _FakeWTM:
    def __init__(self, base):
        self.base = base
        self.created = []

    async def create(self, slug, base_branch="HEAD"):
        self.created.append(slug)
        return _FakeWorktree(self.base)


class _FakeAgentLoader:
    def get_catalog(self):
        return [("general-purpose", "g")]

    def get(self, name):
        return None


class _LeadAgent2:
    def __init__(self, registry):
        self.registry = registry
        self.agent_id = "lead"
        self.work_dir = "."
        self.client = object()
        self.hook_engine = None
        self.context_window = 1000
        self.permission_checker = None
        self.active_conversation = None


def _provider():
    return ProviderConfig(
        protocol="openai", model="deepseek-chat",
        base_url="https://api.deepseek.com", api_key="sk-test",
    )


def test_execute_as_teammate(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    tm.create_team("t", lead_agent_id="lead", teammate_mode="in-process")
    parent = _LeadAgent2(_team_registry())
    wtm = _FakeWTM(str(tmp_path / "wt"))
    tool = AgentTool(
        agent_loader=_FakeAgentLoader(),
        task_manager=TaskManager(),
        trace_manager=TraceManager(),
        parent_agent=parent,
        provider_config=_provider(),
        enable_fork=False,
        worktree_manager=wtm,
        team_manager=tm,
    )
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubTeammate())

    async def scenario():
        r1 = await tool.execute(
            AgentToolParams(prompt="do data", description="d", team_name="t", name="alice")
        )
        r2 = await tool.execute(
            AgentToolParams(prompt="do api", description="d", team_name="t", name="alice")
        )
        for h in list(tm._inprocess_handles.values()):
            try:
                await h.task
            except Exception:
                pass
        return r1, r2

    r1, r2 = asyncio.run(scenario())
    assert not r1.is_error
    assert "alice" in r1.output
    team = tm.get_team("t")
    assert team.get_member("alice") is not None
    assert (
        AgentNameRegistry.instance().resolve("alice")
        == team.get_member("alice").agent_id
    )
    assert team.get_member("alice-2") is not None  # 同名冲突自动加后缀
    assert "team-t/alice" in wtm.created


def test_execute_as_teammate_unknown_team(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    tm = TeamManager()
    parent = _LeadAgent2(_team_registry())
    tool = AgentTool(
        agent_loader=_FakeAgentLoader(),
        task_manager=TaskManager(),
        trace_manager=TraceManager(),
        parent_agent=parent,
        provider_config=_provider(),
        worktree_manager=_FakeWTM(str(tmp_path / "wt")),
        team_manager=tm,
    )

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="p", description="d", team_name="ghost", name="x")
        )

    assert asyncio.run(scenario()).is_error


def test_teammate_branch_not_triggered_without_team_name():
    parent = _LeadAgent2(_team_registry())
    tool = AgentTool(
        agent_loader=_FakeAgentLoader(),
        task_manager=TaskManager(),
        trace_manager=TraceManager(),
        parent_agent=parent,
        provider_config=_provider(),
        enable_fork=False,
        team_manager=None,
    )

    async def scenario():
        # 无 team_name、无 subagent_type、未启用 fork → 走 ch13 原路径（fork disabled 报错）
        return await tool.execute(AgentToolParams(prompt="p", description="d"))

    r = asyncio.run(scenario())
    assert r.is_error


# --- T15: Agent 接入 + build_system_prompt + config -------------------------

from aixcode.agent import Agent
from aixcode.config import load_team_settings
from aixcode.prompts import build_system_prompt


def test_agent_has_team_fields(tmp_path):
    a = Agent(object(), ToolRegistry(), work_dir=str(tmp_path))
    assert a.agent_id and len(a.agent_id) == 12
    assert a.team_name == ""
    assert a.coordinator_mode is False
    assert a._team_manager is None


def test_agent_consume_mailbox_injects(tmp_path, monkeypatch):
    monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)
    a = Agent(object(), ToolRegistry(), work_dir=str(tmp_path))
    tm = TeamManager()
    tm.create_team("t", lead_agent_id=a.agent_id, teammate_mode="in-process")
    a.team_name = "t"
    a._team_manager = tm
    mb = tm.get_mailbox("t")
    mb.write(a.agent_id, create_message("alice", a.agent_id, "hello lead", summary="s"))
    mb.write(
        a.agent_id,
        create_message("alice", a.agent_id, "stop now", summary="s",
                       message_type="shutdown_request"),
    )
    conv = ConversationManager()
    asyncio.run(a._consume_mailbox(conv))
    contents = [m.content for m in conv.history]
    assert "[Message from alice] hello lead" in contents
    assert "[shutdown_request from alice] stop now" in contents
    # consume 后再调用不再注入
    asyncio.run(a._consume_mailbox(conv))
    assert len(conv.history) == 2


def test_agent_consume_mailbox_noop_without_team(tmp_path):
    a = Agent(object(), ToolRegistry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    asyncio.run(a._consume_mailbox(conv))  # 不抛
    assert conv.history == []


def test_build_system_prompt_coordinator():
    p = build_system_prompt(coordinator_mode=True)
    assert "Coordinator Mode" in p
    assert "Coordinator Mode" not in build_system_prompt()


def test_load_team_settings(tmp_path):
    assert load_team_settings(str(tmp_path / "nope.yaml")) == ("", False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "teammate_mode: in-process\nenable_coordinator_mode: true\n", encoding="utf-8"
    )
    assert load_team_settings(str(cfg)) == ("in-process", True)
    cfg.write_text("protocol: openai\n", encoding="utf-8")
    assert load_team_settings(str(cfg)) == ("", False)
    cfg.write_text("teammate_mode: tmux\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_team_settings(str(cfg))
