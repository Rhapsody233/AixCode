"""ch10 Slash Command 框架：注册中心 + 解析（T1）。"""

import asyncio

import pytest

from aixcode.commands.parser import complete, parse_command
from aixcode.commands.registry import (
    Command,
    CommandContext,
    CommandRegistry,
    CommandType,
    UIController,
)


def _cmd(name, *, aliases=None, hidden=False):
    async def _handler(ctx):
        return None

    return Command(
        name=name,
        description=f"desc of {name}",
        handler=_handler,
        type=CommandType.LOCAL,
        aliases=aliases or [],
        hidden=hidden,
    )


# --- CommandType ---

def test_command_type_three_states():
    assert {m.name for m in CommandType} == {"LOCAL", "LOCAL_UI", "PROMPT"}


# --- Command dataclass ---

def test_command_defaults():
    c = _cmd("help")
    assert c.aliases == []
    assert c.usage == ""
    assert c.arg_prompt == ""
    assert c.hidden is False


# --- CommandRegistry: register_sync / find / list ---

def test_register_sync_find_by_name():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help"))
    assert reg.find("help").name == "help"
    assert reg.find("missing") is None


def test_find_by_alias():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help", aliases=["h", "?"]))
    assert reg.find("h").name == "help"
    assert reg.find("?").name == "help"


def test_list_commands_returns_all():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help"))
    reg.register_sync(_cmd("clear"))
    assert {c.name for c in reg.list_commands()} == {"help", "clear"}


def test_duplicate_name_raises():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help"))
    with pytest.raises(ValueError):
        reg.register_sync(_cmd("help"))


def test_alias_conflict_raises():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help", aliases=["h"]))
    with pytest.raises(ValueError):
        reg.register_sync(_cmd("hello", aliases=["h"]))


def test_alias_conflicts_with_existing_name_raises():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help"))
    with pytest.raises(ValueError):
        reg.register_sync(_cmd("other", aliases=["help"]))


def test_unregister_removes_name_and_aliases():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help", aliases=["h"]))
    reg.unregister("help")
    assert reg.find("help") is None
    assert reg.find("h") is None
    # 注销后可重新注册同名
    reg.register_sync(_cmd("help", aliases=["h"]))
    assert reg.find("h").name == "help"


def test_register_async_is_concurrency_safe():
    reg = CommandRegistry()

    async def go():
        await asyncio.gather(
            reg.register(_cmd("a")),
            reg.register(_cmd("b")),
            reg.register(_cmd("c")),
        )

    asyncio.run(go())
    assert {c.name for c in reg.list_commands()} == {"a", "b", "c"}


# --- CommandContext dataclass ---

def test_command_context_fields():
    ctx = CommandContext(
        args="x",
        agent=object(),
        conversation=object(),
        session=object(),
        session_manager=object(),
        memory_manager=object(),
        ui=object(),
        config={},
    )
    assert ctx.args == "x"
    assert ctx.config == {}


# --- UIController Protocol ---

def test_ui_controller_is_protocol():
    # 鸭子类型实现满足 Protocol（运行时可 isinstance 需 runtime_checkable）
    class FakeUI:
        def add_system_message(self, text): ...
        async def send_user_message(self, text): ...
        def set_plan_mode(self, on): ...
        def get_token_count(self): return 0
        def refresh_status(self): ...

    ui: UIController = FakeUI()
    assert ui.get_token_count() == 0


# --- parse_command ---

def test_parse_non_slash_is_not_command():
    assert parse_command("hello world") == ("", "", False)


def test_parse_bare_slash():
    assert parse_command("/") == ("", "", True)


def test_parse_name_and_args_lowercased():
    assert parse_command("/Foo bar baz") == ("foo", "bar baz", True)


def test_parse_name_only():
    assert parse_command("/help") == ("help", "", True)


def test_parse_does_not_raise_on_edges():
    # 空串 / 纯空白 / 前导空白 / 连续空格 都返回稳定三元组、不抛
    assert parse_command("") == ("", "", False)
    assert parse_command("   ") == ("", "", False)
    assert parse_command("  /help  arg") == ("help", "arg", True)
    assert parse_command("/mode   bypass") == ("mode", "bypass", True)


# --- complete ---

def _completion_registry():
    reg = CommandRegistry()
    reg.register_sync(_cmd("help", aliases=["h", "?"]))
    reg.register_sync(_cmd("history"))
    reg.register_sync(_cmd("clear", aliases=["cls"]))
    reg.register_sync(_cmd("secret", hidden=True))
    return reg


def test_complete_prefix_match_sorted():
    reg = _completion_registry()
    assert complete(reg, "/h") == ["/h", "/help", "/history"]


def test_complete_bare_slash_returns_all_visible():
    reg = _completion_registry()
    got = complete(reg, "/")
    assert "/help" in got and "/clear" in got and "/cls" in got
    assert "/secret" not in got
    assert got == sorted(got)


def test_complete_excludes_hidden():
    reg = _completion_registry()
    assert complete(reg, "/sec") == []


def test_complete_no_match():
    reg = _completion_registry()
    assert complete(reg, "/zzz") == []


def test_complete_dedup():
    reg = _completion_registry()
    # 别名与名都以 c 开头时不重复
    assert complete(reg, "/c") == ["/clear", "/cls"]


# ======================================================================
# T2: 10 个内置 handler
# ======================================================================

from datetime import datetime

from aixcode.permissions import PermissionMode


class FakeUI:
    def __init__(self, token_count=0):
        self.system_messages: list[str] = []
        self.sent: list[str] = []
        self.plan_calls: list[bool] = []
        self.refreshed = 0
        self._tokens = token_count

    def add_system_message(self, text):
        self.system_messages.append(text)

    async def send_user_message(self, text):
        self.sent.append(text)

    def set_plan_mode(self, on):
        self.plan_calls.append(on)

    def get_token_count(self):
        return self._tokens

    def refresh_status(self):
        self.refreshed += 1

    @property
    def last(self):
        return self.system_messages[-1] if self.system_messages else ""


class _FakeRegistryView:
    def __init__(self, tool_count=3):
        self._n = tool_count

    def list_tools(self):
        return list(range(self._n))


class FakeAgent:
    def __init__(self, mode=PermissionMode.DEFAULT, compact_result=None, tool_count=3):
        self.permission_mode = mode
        self.set_calls: list = []
        self.registry = _FakeRegistryView(tool_count)
        self._compact_result = compact_result
        self.compact_called = False
        self._loop_count = 7

    def set_permission_mode(self, mode):
        self.set_calls.append(mode)
        self.permission_mode = mode

    async def manual_compact(self, conversation):
        self.compact_called = True
        return self._compact_result


class _FakeMM:
    def __init__(self, display="记忆展示文本"):
        self.user_path = "/u/memories.md"
        self.project_path = "/p/memories.md"
        self.cleared = False
        self._display = display

    def get_display_text(self):
        return self._display

    def clear(self):
        self.cleared = True


class _Conv:
    def __init__(self, tokens=0):
        self.last_input_tokens = tokens


class _Meta:
    def __init__(self):
        self.id = "sess-123"
        self.title = "我的会话"
        self.message_count = 4
        self.last_active = datetime(2026, 6, 21, 10, 30)


class _Session:
    meta = _Meta()


def _make_ctx(args="", *, ui=None, agent=None, memory_manager=None,
              conversation=None, session=None, session_manager=None, config=None):
    return CommandContext(
        args=args,
        agent=agent or FakeAgent(),
        conversation=conversation or _Conv(),
        session=session if session is not None else _Session(),
        session_manager=session_manager,
        memory_manager=memory_manager,
        ui=ui or FakeUI(),
        config=config or {},
    )


def _run(coro):
    return asyncio.run(coro)


# --- help ---

def test_help_lists_all():
    from aixcode.commands.handlers import help as help_h

    reg = CommandRegistry()
    reg.register_sync(_cmd("help", aliases=["h"]))
    reg.register_sync(_cmd("clear"))
    reg.register_sync(_cmd("secret", hidden=True))
    ui = FakeUI()
    _run(help_h.handle_help(_make_ctx("", ui=ui, config={"registry": reg})))
    out = ui.last
    assert "/help" in out and "/clear" in out
    assert "/h" in out  # 别名展示
    assert "secret" not in out  # hidden 不列


def test_help_single_command():
    from aixcode.commands.handlers import help as help_h

    reg = CommandRegistry()
    reg.register_sync(_cmd("clear", aliases=["cls"]))
    ui = FakeUI()
    _run(help_h.handle_help(_make_ctx("clear", ui=ui, config={"registry": reg})))
    assert "clear" in ui.last


def test_help_unknown():
    from aixcode.commands.handlers import help as help_h

    reg = CommandRegistry()
    ui = FakeUI()
    _run(help_h.handle_help(_make_ctx("nope", ui=ui, config={"registry": reg})))
    assert "未知" in ui.last


def test_help_command_type():
    from aixcode.commands.handlers.help import HELP_COMMAND

    assert HELP_COMMAND.type is CommandType.LOCAL
    assert set(HELP_COMMAND.aliases) == {"h", "?"}


# --- clear ---

def test_clear_calls_closure():
    from aixcode.commands.handlers.clear import CLEAR_COMMAND, handle_clear

    called = []
    ui = FakeUI()
    _run(handle_clear(_make_ctx("", ui=ui, config={"clear_chat": lambda: called.append(True)})))
    assert called == [True]
    assert CLEAR_COMMAND.type is CommandType.LOCAL_UI
    assert "cls" in CLEAR_COMMAND.aliases


# --- status ---

def test_status_outputs_fields():
    from aixcode.commands.handlers.status import STATUS_COMMAND, handle_status

    ui = FakeUI()
    agent = FakeAgent(mode=PermissionMode.DEFAULT, tool_count=6)
    ctx = _make_ctx(
        "", ui=ui, agent=agent, conversation=_Conv(tokens=1234),
        memory_manager=_FakeMM(), config={"version": "0.1.0"},
    )
    _run(handle_status(ctx))
    out = ui.last
    assert "default" in out  # 模式
    assert "sess-123" in out  # 会话
    assert "1234" in out  # token
    assert "6" in out  # 工具数
    assert "0.1.0" in out  # 版本
    assert STATUS_COMMAND.type is CommandType.LOCAL


# --- compact ---

def test_compact_below_threshold():
    from aixcode.commands.handlers.compact import handle_compact

    ui = FakeUI()
    agent = FakeAgent()
    _run(handle_compact(_make_ctx("", ui=ui, agent=agent, conversation=_Conv(tokens=100))))
    assert "无需压缩" in ui.last
    assert agent.compact_called is False


def test_compact_runs():
    from aixcode.commands.handlers.compact import handle_compact

    class _Notif:
        before_tokens = 9999

    ui = FakeUI()
    agent = FakeAgent(compact_result=_Notif())
    _run(handle_compact(_make_ctx("", ui=ui, agent=agent, conversation=_Conv(tokens=8000))))
    assert agent.compact_called is True
    assert "9999" in ui.last


# --- plan / do ---

def test_plan_sets_mode_and_optionally_sends():
    from aixcode.commands.handlers.plan import PLAN_COMMAND, handle_plan

    ui = FakeUI()
    _run(handle_plan(_make_ctx("", ui=ui)))
    assert ui.plan_calls == [True]
    assert ui.sent == []

    ui2 = FakeUI()
    _run(handle_plan(_make_ctx("设计登录", ui=ui2)))
    assert ui2.plan_calls == [True]
    assert ui2.sent == ["设计登录"]
    assert PLAN_COMMAND.type is CommandType.LOCAL_UI


def test_do_sets_mode_off():
    from aixcode.commands.handlers.do import handle_do

    ui = FakeUI()
    _run(handle_do(_make_ctx("", ui=ui)))
    assert ui.plan_calls == [False]


# --- mode ---

def test_mode_valid():
    from aixcode.commands.handlers.mode import handle_mode

    ui = FakeUI()
    agent = FakeAgent()
    _run(handle_mode(_make_ctx("bypass", ui=ui, agent=agent)))
    assert agent.set_calls == [PermissionMode.BYPASS]


def test_mode_valid_with_trailing_message():
    from aixcode.commands.handlers.mode import handle_mode

    ui = FakeUI()
    agent = FakeAgent()
    _run(handle_mode(_make_ctx("strict 顺便干点活", ui=ui, agent=agent)))
    assert agent.set_calls == [PermissionMode.STRICT]
    assert ui.sent == ["顺便干点活"]


def test_mode_invalid():
    from aixcode.commands.handlers.mode import handle_mode

    ui = FakeUI()
    agent = FakeAgent()
    _run(handle_mode(_make_ctx("nonsense", ui=ui, agent=agent)))
    assert agent.set_calls == []
    assert "用法" in ui.last


def test_parse_mode_name_in_handler():
    from aixcode.commands.handlers.mode import parse_mode_name

    assert parse_mode_name("bypass") is PermissionMode.BYPASS
    assert parse_mode_name("nope") is None


# --- memory ---

def test_memory_list():
    from aixcode.commands.handlers.memory import MEMORY_COMMAND, handle_memory

    ui = FakeUI()
    _run(handle_memory(_make_ctx("list", ui=ui, memory_manager=_FakeMM())))
    assert ui.last == "记忆展示文本"
    assert MEMORY_COMMAND.type is CommandType.LOCAL


def test_memory_clear():
    from aixcode.commands.handlers.memory import handle_memory

    ui = FakeUI()
    mm = _FakeMM()
    _run(handle_memory(_make_ctx("clear", ui=ui, memory_manager=mm)))
    assert mm.cleared is True
    assert "已清空" in ui.last


def test_memory_edit():
    from aixcode.commands.handlers.memory import handle_memory

    ui = FakeUI()
    _run(handle_memory(_make_ctx("edit", ui=ui, memory_manager=_FakeMM())))
    assert "/u/memories.md" in ui.last and "/p/memories.md" in ui.last


def test_render_memory_pure():
    from aixcode.commands.handlers.memory import render_memory

    assert render_memory(_FakeMM(), "list") == "记忆展示文本"
    assert "未初始化" in render_memory(None, "list")


# --- session ---

class _FakeSM:
    def __init__(self):
        self.deleted = None
        self.created = False
        self._metas = [_Meta()]

    def list(self):
        return self._metas

    def resume(self, sid):
        if sid == "missing":
            return None
        class _R:
            session = _Session()
            messages = ["m1", "m2"]
            last_active = datetime(2026, 6, 20, 9, 0)
        return _R()

    def create(self):
        self.created = True
        return _Session()

    def delete(self, sid):
        self.deleted = sid
        return sid != "missing"


def test_session_list():
    from aixcode.commands.handlers.session import handle_session

    ui = FakeUI()
    _run(handle_session(_make_ctx("list", ui=ui, session_manager=_FakeSM())))
    assert "sess-123" in ui.last


def test_session_resume_applies():
    from aixcode.commands.handlers.session import handle_session

    ui = FakeUI()
    applied = {}
    cfg = {"set_session": lambda session, messages, last_active: applied.update(
        session=session, messages=messages, last_active=last_active)}
    _run(handle_session(_make_ctx("resume sess-123", ui=ui, session_manager=_FakeSM(), config=cfg)))
    assert applied["messages"] == ["m1", "m2"]


def test_session_resume_missing():
    from aixcode.commands.handlers.session import handle_session

    ui = FakeUI()
    cfg = {"set_session": lambda *a, **k: None}
    _run(handle_session(_make_ctx("resume missing", ui=ui, session_manager=_FakeSM(), config=cfg)))
    assert "未找到" in ui.last


def test_session_new():
    from aixcode.commands.handlers.session import handle_session

    ui = FakeUI()
    sm = _FakeSM()
    applied = {}
    cfg = {"set_session": lambda session, messages, last_active: applied.update(messages=messages)}
    _run(handle_session(_make_ctx("new", ui=ui, session_manager=sm, config=cfg)))
    assert sm.created is True
    assert applied["messages"] == []


def test_session_delete():
    from aixcode.commands.handlers.session import handle_session

    ui = FakeUI()
    sm = _FakeSM()
    _run(handle_session(_make_ctx("delete sess-9", ui=ui, session_manager=sm)))
    assert sm.deleted == "sess-9"


# --- review ---

def test_review_sends_prompt():
    from aixcode.commands.handlers.review import REVIEW_PROMPT, REVIEW_COMMAND, handle_review

    ui = FakeUI()
    _run(handle_review(_make_ctx("", ui=ui)))
    assert ui.sent and ui.sent[0] == REVIEW_PROMPT
    assert REVIEW_COMMAND.type is CommandType.PROMPT


def test_review_with_args():
    from aixcode.commands.handlers.review import REVIEW_PROMPT, handle_review

    ui = FakeUI()
    _run(handle_review(_make_ctx("修复并发问题", ui=ui)))
    assert REVIEW_PROMPT in ui.sent[0]
    assert "修复并发问题" in ui.sent[0]


def test_review_prompt_has_four_aspects():
    from aixcode.commands.handlers.review import REVIEW_PROMPT

    for kw in ("逻辑", "安全", "性能", "风格"):
        assert kw in REVIEW_PROMPT


# ======================================================================
# T3: register_all_commands 聚合入口
# ======================================================================

def test_all_commands_has_eleven():
    from aixcode.commands.handlers import ALL_COMMANDS

    names = {c.name for c in ALL_COMMANDS}
    assert names == {
        "help", "clear", "status", "compact", "plan",
        "do", "mode", "session", "memory", "review", "skill",
        "tasks", "trace",
    }


def test_register_all_commands_registers_eleven():
    from aixcode.commands.handlers import register_all_commands

    reg = CommandRegistry()
    register_all_commands(reg)
    assert len(reg.list_commands()) == 13


def test_register_all_aliases_findable():
    from aixcode.commands.handlers import register_all_commands

    reg = CommandRegistry()
    register_all_commands(reg)
    assert reg.find("h").name == "help"
    assert reg.find("?").name == "help"
    assert reg.find("cls").name == "clear"
    assert reg.find("s").name == "status"
    assert reg.find("c").name == "compact"
    assert reg.find("p").name == "plan"


def test_register_all_no_conflict():
    from aixcode.commands.handlers import register_all_commands

    # 不应抛 ValueError（无 name/alias 冲突）
    register_all_commands(CommandRegistry())


# ======================================================================
# T4: prompt_toolkit Tab 补全
# ======================================================================

def _completer():
    from aixcode.commands.completion import SlashCommandCompleter
    from aixcode.commands.handlers import register_all_commands

    reg = CommandRegistry()
    register_all_commands(reg)
    reg.register_sync(_cmd("secret", hidden=True))
    return SlashCommandCompleter(reg)


def _complete_texts(completer, text):
    from prompt_toolkit.document import Document

    return [c.text for c in completer.get_completions(Document(text), None)]


def test_completer_suggests_on_prefix():
    texts = _complete_texts(_completer(), "/he")
    assert "/help" in texts


def test_completer_start_position():
    from prompt_toolkit.document import Document

    completer = _completer()
    comps = list(completer.get_completions(Document("/he"), None))
    help_comp = next(c for c in comps if c.text == "/help")
    assert help_comp.start_position == -3  # 替换已输入的 "/he"


def test_completer_no_suggest_after_space():
    assert _complete_texts(_completer(), "/plan foo") == []


def test_completer_ignores_non_slash():
    assert _complete_texts(_completer(), "hello") == []


def test_completer_excludes_hidden():
    assert "/secret" not in _complete_texts(_completer(), "/sec")
