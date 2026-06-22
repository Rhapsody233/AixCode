import asyncio
import io

from rich.console import Console

from aixcode.agent import PermissionResponse
from aixcode.app import AixCodeApp, parse_permission_choice
from aixcode.conversation import ConversationManager
from aixcode.permissions import PermissionMode


def test_renderer_handles_compact_notification():
    from aixcode.agent import CompactNotification
    from aixcode.app import _Renderer

    renderer = _Renderer(Console())
    # 不应抛出
    renderer.render(CompactNotification(before_tokens=12345))


def test_run_turn_recovers_from_cancel():
    class CancelAgent:
        async def run(self, conversation):
            raise asyncio.CancelledError
            yield  # 使其成为 async generator

    conv = ConversationManager()
    app = AixCodeApp(CancelAgent(), conv, model="deepseek-chat")

    # 不应抛出：中断被捕获、本轮历史回退干净
    asyncio.run(app._run_turn("做点事"))

    assert conv.history == []


def test_summarize_tool():
    from aixcode.app import _summarize_tool

    assert _summarize_tool("ReadFile", {"file_path": "a.txt"}) == "Read a.txt"
    assert _summarize_tool("WriteFile", {"file_path": "b.txt", "content": "x\ny\n"}) == "Write b.txt (2 lines)"
    assert _summarize_tool("Grep", {"pattern": "foo"}) == "Grep foo"


def test_build_mcp_reminder_lists_servers_and_tools():
    from aixcode.app import _build_mcp_reminder

    text = _build_mcp_reminder(["context7"], ["mcp_context7_resolve_library_id"])
    assert "context7" in text
    assert "mcp_context7_resolve_library_id" in text


def test_app_without_mcp_servers_is_noop():
    # mcp_servers=None 时不应触发任何 MCP 行为；既有构造路径不变
    conv = ConversationManager()

    class _Agent:
        pass

    app = AixCodeApp(_Agent(), conv, model="deepseek-chat")
    assert app.mcp_servers is None


def test_parse_permission_choice():
    assert parse_permission_choice("1") is PermissionResponse.ALLOW
    assert parse_permission_choice("2") is PermissionResponse.ALLOW_SESSION
    assert parse_permission_choice("3") is PermissionResponse.ALLOW_ALWAYS
    assert parse_permission_choice("4") is PermissionResponse.DENY
    # 非法/空输入安全默认拒绝
    assert parse_permission_choice("") is PermissionResponse.DENY
    assert parse_permission_choice("x") is PermissionResponse.DENY


# --- T5: Slash Command 接入（registry + 分发）------------------------------


class _StatusAgent:
    """够 /status 与 _build_command_context 用的最小 agent。"""

    def __init__(self):
        self.permission_mode = PermissionMode.DEFAULT
        self.memory_manager = None

        class _Reg:
            def list_tools(self):
                return [1, 2, 3]

        self.registry = _Reg()

    def set_permission_mode(self, mode):
        self.permission_mode = mode


def _recording_app(agent=None):
    conv = ConversationManager()
    app = AixCodeApp(agent or _StatusAgent(), conv, model="deepseek-chat")
    app.console = Console(file=io.StringIO(), record=True, width=120)
    return app


def test_app_builds_command_registry():
    app = _recording_app()
    assert app.command_registry.find("help").name == "help"
    # ch10/11 的 11 个 + ch13 的 /tasks·/trace = 13（无 skill_loader 时不注册 skill 命令）
    assert len(app.command_registry.list_commands()) == 13


def test_dispatch_status_prints_fields():
    app = _recording_app()
    asyncio.run(app._dispatch_command("/status"))
    out = app.console.export_text()
    assert "模式" in out and "default" in out
    assert "工具" in out and "3" in out


def test_dispatch_unknown_command():
    app = _recording_app()
    asyncio.run(app._dispatch_command("/nope"))
    assert "未知命令" in app.console.export_text()


def test_dispatch_alias_resolves():
    app = _recording_app()
    asyncio.run(app._dispatch_command("/s"))  # /s == /status
    assert "模式" in app.console.export_text()


def test_dispatch_command_exception_is_caught():
    from aixcode.commands.registry import Command, CommandType

    app = _recording_app()

    async def boom(ctx):
        raise RuntimeError("炸了")

    app.command_registry.register_sync(
        Command(name="boom", description="b", handler=boom, type=CommandType.LOCAL)
    )
    # 不应抛出
    asyncio.run(app._dispatch_command("/boom"))
    assert "执行失败" in app.console.export_text()


def test_set_plan_mode_toggles_permission():
    app = _recording_app()
    app.set_plan_mode(True)
    assert app.agent.permission_mode is PermissionMode.PLAN
    app.set_plan_mode(False)
    assert app.agent.permission_mode is PermissionMode.DEFAULT


def test_dispatch_help_does_not_crash_on_bracket_output():
    # /help 列表含别名展示如 "[/cls]"，不应被当 rich markup 解析而崩溃
    app = _recording_app()
    asyncio.run(app._dispatch_command("/help"))
    out = app.console.export_text()
    assert "/clear" in out and "/cls" in out


def test_dispatch_error_message_with_brackets_does_not_crash():
    from aixcode.commands.registry import Command, CommandType

    app = _recording_app()

    async def boom(ctx):
        raise RuntimeError("出错了 [/oops] 含方括号")

    app.command_registry.register_sync(
        Command(name="boom", description="b", handler=boom, type=CommandType.LOCAL)
    )
    asyncio.run(app._dispatch_command("/boom"))  # 不应抛出
    assert "执行失败" in app.console.export_text()


def test_add_system_message_keeps_literal_brackets():
    app = _recording_app()
    app.add_system_message("路径 [project] 与 [/x] 应原样显示")
    out = app.console.export_text()
    assert "[project]" in out and "[/x]" in out
