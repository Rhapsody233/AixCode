"""终端 UI：Claude-Code 风格——banner、滚动 transcript、底部输入框与状态栏。"""

from __future__ import annotations

import asyncio
import os
import shutil

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markup import escape

from aixcode.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionMode,
    PermissionRequest,
    PermissionResponse,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)
from aixcode.client import LLMError
from aixcode.commands.completion import SlashCommandCompleter
from aixcode.commands.handlers import register_all_commands
from aixcode.commands.handlers.skill_register import register_skill_commands
from aixcode.commands.parser import parse_command
from aixcode.commands.registry import CommandContext, CommandRegistry
from aixcode.conversation import ConversationManager
from aixcode.mcp import MCPManager
from aixcode.memory import SessionManager, build_time_gap_message

# HITL 4 选项 → 回应
_CHOICE_MAP = {
    "1": PermissionResponse.ALLOW,
    "2": PermissionResponse.ALLOW_SESSION,
    "3": PermissionResponse.ALLOW_ALWAYS,
    "4": PermissionResponse.DENY,
}

_EXIT_COMMANDS = ("/exit", "/quit")
_VERSION = "0.1.0"

# worktree 后台过期清理节奏
_STALE_CLEANUP_INTERVAL = 3600.0  # 每小时扫一轮
_STALE_CUTOFF_HOURS = 24.0  # 24 小时未动的孤儿才清

_LOGO = r"""
  /\_/\     AixCode v{version}
 ( o.o )    {model}
  > ^ <     {cwd}
"""


def parse_permission_choice(choice: str) -> PermissionResponse:
    """把用户输入的 1/2/3/4 解析成回应；非法/空输入安全默认拒绝。"""
    return _CHOICE_MAP.get(choice.strip(), PermissionResponse.DENY)


def _build_mcp_reminder(server_names: list[str], tool_names: list[str]) -> str:
    """构造一条系统提醒，告诉模型已接入哪些 MCP server 与可用工具。"""
    servers = "、".join(server_names) if server_names else "（无）"
    tools = "\n".join(f"- {t}" for t in tool_names) if tool_names else "（无）"
    return (
        f"已接入 MCP server：{servers}。以下远端工具可用（按需用 ToolSearch 取出后调用）：\n"
        f"{tools}"
    )


def _build_mcp_resource_catalog(resources: list[tuple]) -> str:
    """构造一条系统提醒，列出可用 MCP 资源（按需用 ReadMcpResource 读取）。"""
    lines = "\n".join(
        f"- {uri}" + (f"（{desc}）" if desc else "")
        for _server, uri, _name, desc in resources
    )
    return (
        "以下 MCP 资源可用（需要时用 ReadMcpResource 按 uri 读取）：\n"
        f"{lines}"
    )


def _summarize_tool(name: str, args: dict) -> str:
    """把一次工具调用渲染成简短摘要，如 'Write hello.txt (2 lines)'。"""
    file_path = args.get("file_path") or args.get("path") or ""
    if name == "WriteFile":
        lines = len((args.get("content") or "").splitlines())
        return f"Write {file_path} ({lines} lines)"
    if name == "ReadFile":
        return f"Read {file_path}"
    if name == "EditFile":
        return f"Edit {file_path}"
    if name == "Bash":
        cmd = (args.get("command") or "").strip().replace("\n", " ")
        return f"Bash {cmd[:48]}"
    if name == "Glob":
        return f"Glob {args.get('pattern', '')}"
    if name == "Grep":
        return f"Grep {args.get('pattern', '')}"
    return name


class _Renderer:
    """把 AgentEvent 渲染到终端（✓ 工具摘要 / ● 最终回复 / 暗色思考）。"""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.in_thinking = False
        self.in_text = False

    def _flush_line(self) -> None:
        if self.in_text or self.in_thinking:
            self.console.print()
        self.in_thinking = False
        self.in_text = False

    def render(self, event) -> None:
        if isinstance(event, ThinkingText):
            if not self.in_thinking:
                self.console.print("[dim]思考中…[/dim]")
                self.in_thinking = True
            self.console.print(event.text, end="", style="dim", markup=False)
        elif isinstance(event, StreamText):
            if not self.in_text:
                if self.in_thinking:
                    self.console.print()
                self.console.print("[magenta]●[/magenta] ", end="")
                self.in_text = True
            self.console.print(event.text, end="", markup=False)
        elif isinstance(event, ToolUseEvent):
            self._flush_line()
        elif isinstance(event, ToolResultEvent):
            summary = _summarize_tool(event.tool_name, event.arguments)
            if event.is_error:
                self.console.print(
                    f"  [red]✗ {summary}[/red]", markup=True
                )
                self.console.print(f"    [red]{event.output.strip()}[/red]", markup=False)
            else:
                self.console.print(
                    f"  [green]✓[/green] {summary} [dim]({event.duration:.1f}s)[/dim]"
                )
        elif isinstance(event, UsageEvent):
            self._flush_line()
            if event.cache_hit_tokens:
                self.console.print(
                    f"[dim]  (cached {event.cache_hit_tokens} tokens)[/dim]"
                )
        elif isinstance(event, TurnComplete):
            pass
        elif isinstance(event, LoopComplete):
            self._flush_line()
        elif isinstance(event, CompactNotification):
            self._flush_line()
            self.console.print(
                f"[cyan]上下文已压缩（压缩前 {event.before_tokens} tokens）[/cyan]"
            )
        elif isinstance(event, HookEvent):
            self._flush_line()
            self.console.print(
                f"[hook {event.hook_id}] {event.output}", style="dim", markup=False
            )
        elif isinstance(event, ErrorEvent):
            self._flush_line()
            self.console.print(f"[red]错误：{event.message}[/red]")


class AixCodeApp:
    """对话主循环（Claude-Code 风格 UI）。"""

    def __init__(
        self,
        agent: Agent,
        conversation: ConversationManager,
        model: str = "",
        mcp_servers=None,
        skill_loader=None,
        skill_executor=None,
        hook_engine=None,
        task_manager=None,
        trace_manager=None,
        worktree_manager=None,
    ) -> None:
        self.agent = agent
        self.conversation = conversation
        self.model = model
        self.mcp_servers = mcp_servers
        self.skill_loader = skill_loader
        self.skill_executor = skill_executor
        self.hook_engine = hook_engine
        self.task_manager = task_manager
        self.trace_manager = trace_manager
        self.worktree_manager = worktree_manager
        self._stale_cleanup_task = None
        self._mcp_manager: MCPManager | None = None
        self.session_manager: SessionManager | None = None
        self.session = None
        self._archived_count = 0
        self.console = Console()
        self.command_registry = CommandRegistry()
        register_all_commands(self.command_registry)
        if skill_loader is not None and skill_executor is not None:
            register_skill_commands(
                self.command_registry, skill_loader, skill_executor
            )
        if worktree_manager is not None:
            from aixcode.commands.handlers.worktree import create_worktree_command

            self.command_registry.register_sync(
                create_worktree_command(worktree_manager)
            )
            self._register_worktree_cache_clear()

    def _register_worktree_cache_clear(self) -> None:
        """切 worktree 时同步 Agent 的 work_dir/沙箱、清文件读快照并重载项目指令，
        防用旧目录内容做决策。"""
        agent = self.agent

        def _set_work_dir(path: str) -> None:
            agent.work_dir = path
            checker = getattr(agent, "permission_checker", None)
            if checker is not None:
                from aixcode.permissions import PathSandbox

                checker.sandbox = PathSandbox(project_root=path)

        def _clear() -> None:
            from aixcode.context import RecoveryState
            from aixcode.memory import load_instructions

            agent.recovery_state = RecoveryState()
            agent.instructions_content = load_instructions(agent.work_dir)

        self.worktree_manager.add_work_dir_callback(_set_work_dir)
        self.worktree_manager.add_cache_clear_callback(_clear)

    def _start_worktree_cleanup(self) -> None:
        """启动孤儿 worktree 后台过期清理 task（manager 非空时）。"""
        if self.worktree_manager is None:
            return
        from aixcode.worktree import start_stale_cleanup_task

        self._stale_cleanup_task = asyncio.create_task(
            start_stale_cleanup_task(
                self.worktree_manager,
                _STALE_CLEANUP_INTERVAL,
                _STALE_CUTOFF_HOURS,
            )
        )

    def _stop_worktree_cleanup(self) -> None:
        if self._stale_cleanup_task is not None:
            self._stale_cleanup_task.cancel()

    def _print_banner(self) -> None:
        self.console.print(
            _LOGO.format(version=_VERSION, model=self.model, cwd=os.getcwd()),
            style="cyan",
            highlight=False,
        )
        n = len(self.agent.registry.list_tools())
        self.console.print(f"  [dim]{n} tools registered[/dim]\n")

    def _bottom_toolbar(self) -> HTML:
        mode = self.agent.permission_mode.value
        width = shutil.get_terminal_size((80, 24)).columns
        left = f" {mode}"
        right = f"{self.model} "
        pad = max(1, width - len(left) - len(right))
        return HTML(f"{left}{' ' * pad}{right}")

    async def run(self) -> None:
        self._print_banner()
        await self._init_mcp()
        self._init_session()
        await self._emit_app_hooks("startup")
        self._start_worktree_cleanup()
        try:
            await self._repl_loop()
        finally:
            self._stop_worktree_cleanup()
            await self._emit_app_hooks("shutdown")
            await self._shutdown_mcp()
            if self.session is not None:
                self.session.close()

    async def _emit_app_hooks(self, event: str) -> None:
        """会话级 startup/shutdown 钩子（engine 为 None 时 no-op）。"""
        if self.hook_engine is None:
            return
        from aixcode.hooks import HookContext

        await self.hook_engine.run_hooks(event, HookContext(event_name=event))
        for n in self.hook_engine.drain_notifications():
            self.console.print(
                f"[hook {n.hook_id}] {n.output}", style="dim", markup=False
            )

    def _init_session(self) -> None:
        """启动时清理过期会话并新建一个活跃会话。"""
        try:
            self.session_manager = SessionManager(os.getcwd())
            self.session_manager.cleanup()
            self.session = self.session_manager.create()
        except OSError as e:
            self.console.print(f"[yellow]会话存档不可用：{e}[/yellow]")

    def _archive_new_messages(self) -> None:
        """把对话中尚未存档的新消息追加写入会话 jsonl。"""
        if self.session is None:
            return
        for msg in self.conversation.history[self._archived_count:]:
            self.session.append(msg)
        self._archived_count = len(self.conversation.history)

    async def _init_mcp(self) -> None:
        """启动时按配置连接 MCP server，把工具注册进 registry 并注入一条系统提醒。"""
        if not self.mcp_servers:
            return
        manager = MCPManager()
        manager.load_configs(self.mcp_servers)
        errors = await manager.register_all_tools(self.agent.registry)
        self._mcp_manager = manager
        mcp_tools = [
            t.name for t in self.agent.registry.list_tools() if t.name.startswith("mcp_")
        ]
        connected = len(self.mcp_servers) - len(errors)
        self.console.print(
            f"[green]Connected to {connected} MCP server(s), "
            f"{len(mcp_tools)} tools registered[/green]"
        )
        for err in errors:
            self.console.print(f"[yellow]MCP 连接失败：{err}[/yellow]")
        if mcp_tools:
            server_names = [s.name for s in self.mcp_servers]
            self.conversation.add_system_reminder(
                _build_mcp_reminder(server_names, mcp_tools)
            )

        # ch16：资源（ReadMcpResource + catalog）与提示（slash command）
        from aixcode.commands.handlers.mcp_prompt import register_mcp_prompts
        from aixcode.tools.read_mcp_resource import ReadMcpResource

        resources = await manager.register_all_resources()
        self.agent.registry.register(ReadMcpResource(manager))
        if resources:
            self.conversation.add_system_reminder(_build_mcp_resource_catalog(resources))
        await register_mcp_prompts(self.command_registry, manager)

    async def _shutdown_mcp(self) -> None:
        if self._mcp_manager is not None:
            await self._mcp_manager.shutdown()

    async def _repl_loop(self) -> None:
        session: PromptSession = PromptSession(
            completer=SlashCommandCompleter(self.command_registry)
        )
        placeholder = HTML('<style fg="#6b7280">Send a message…</style>')

        while True:
            try:
                with patch_stdout():
                    user_input = await session.prompt_async(
                        HTML("<ansicyan>❯ </ansicyan>"),
                        placeholder=placeholder,
                        bottom_toolbar=self._bottom_toolbar,
                    )
            except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
                self.console.print("再见。")
                return

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped in _EXIT_COMMANDS:
                self.console.print("再见。")
                return

            _, _, is_command = parse_command(user_input)
            if is_command:
                await self._dispatch_command(user_input)
                continue

            self._inject_completed_tasks()
            await self._run_turn(stripped)
            self._archive_new_messages()

    def _inject_completed_tasks(self) -> None:
        """每轮前抽空后台任务通知，把 <task-notification> 灌进对话（ch13）。"""
        if self.task_manager is None:
            return
        completed = self.task_manager.poll_completed()
        if not completed:
            return
        from aixcode.agents.notification import inject_task_notifications

        inject_task_notifications(self.conversation, completed)
        for task in completed:
            self.console.print(
                f"[cyan]后台任务 {task.task_id}（{task.agent_type}）已 {task.status}[/cyan]"
            )

    # --- UIController：供命令 handler 经 ctx.ui 改 UI 状态 / 回投消息 ---

    def add_system_message(self, text: str) -> None:
        # handler 产出纯文本（含路径 / 别名 / 标题等字面方括号），不走 rich markup 解析。
        self.console.print(text, markup=False)

    async def send_user_message(self, text: str) -> None:
        await self._run_turn(text)
        self._archive_new_messages()

    def set_plan_mode(self, on: bool) -> None:
        self.agent.set_permission_mode(
            PermissionMode.PLAN if on else PermissionMode.DEFAULT
        )

    def get_token_count(self) -> int:
        # ch16：尚无 API 真实 token 数（首轮发送前）时回退到本地预估，补盲区
        if self.conversation.last_input_tokens:
            return self.conversation.last_input_tokens
        from aixcode.context.tokenizer import estimate_conversation_tokens

        return estimate_conversation_tokens(self.conversation)

    def refresh_status(self) -> None:
        pass

    # --- 命令分发 ---

    def _build_command_context(self, args: str) -> CommandContext:
        def set_conversation(messages, last_active=None):
            self.conversation.replace_history(messages)
            if last_active is not None:
                gap = build_time_gap_message(last_active)
                if gap is not None:
                    self.conversation.history.append(gap)
            self._archived_count = len(self.conversation.history)

        def set_session(session, messages, last_active):
            if self.session is not None:
                self.session.close()
            self.session = session
            set_conversation(messages, last_active)
            self.agent._loop_count = 0

        def clear_chat():
            set_conversation([])
            self.console.clear()

        return CommandContext(
            args=args,
            agent=self.agent,
            conversation=self.conversation,
            session=self.session,
            session_manager=self.session_manager,
            memory_manager=getattr(self.agent, "memory_manager", None),
            ui=self,
            config={
                "registry": self.command_registry,
                "version": _VERSION,
                "set_conversation": set_conversation,
                "set_session": set_session,
                "clear_chat": clear_chat,
                "skill_loader": self.skill_loader,
                "skill_executor": self.skill_executor,
                "task_manager": self.task_manager,
                "trace_manager": self.trace_manager,
            },
        )

    async def _dispatch_command(self, text: str) -> None:
        name, args, _ = parse_command(text)
        cmd = self.command_registry.find(name)
        if cmd is None:
            self.console.print(f"[red]未知命令：/{escape(name)}（用 /help 查看全部）[/red]")
            return
        ctx = self._build_command_context(args)
        try:
            await cmd.handler(ctx)
        except Exception as e:  # 单命令失败不拉崩 REPL
            self.console.print(f"[red]命令 /{escape(name)} 执行失败：{escape(str(e))}[/red]")

    async def _handle_permission(self, request: PermissionRequest) -> None:
        """渲染 4 选项、读用户选择，回填 future。读失败默认拒绝。"""
        self.console.print(f"\n[yellow]需要授权：{request.description}[/yellow]")
        self.console.print(
            "  [cyan]1[/cyan] 本次允许   [cyan]2[/cyan] 本会话允许   "
            "[cyan]3[/cyan] 永久允许   [cyan]4[/cyan] 拒绝"
        )
        try:
            with patch_stdout():
                choice = await PromptSession().prompt_async(
                    HTML("<ansicyan>选择 [1/2/3/4] ❯ </ansicyan>")
                )
        except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
            choice = "4"
        request.future.set_result(parse_permission_choice(choice))

    async def _consume_turn(self, renderer: "_Renderer") -> None:
        """消费 Agent 事件流（含权限 HITL）。"""
        async for event in self.agent.run(self.conversation):
            if isinstance(event, PermissionRequest):
                await self._handle_permission(event)
                continue
            renderer.render(event)

    async def _run_turn(self, message: str) -> None:
        """跑一个回合：写入 user 消息、消费 Agent 事件流；失败/中断回退本轮历史。

        中断时若有仍在跑的子 Agent 工作（task_manager 在），用 adopt_running 把它
        挂后台继续而非杀掉（shield 防止取消传播到内部任务）。
        """
        mark = len(self.conversation.history)
        self.conversation.add_user_message(message)
        renderer = _Renderer(self.console)
        turn_task = asyncio.ensure_future(self._consume_turn(renderer))
        try:
            await asyncio.shield(turn_task)
        except LLMError as e:
            del self.conversation.history[mark:]
            self.console.print(f"[red]错误：{e}[/red]")
        except (KeyboardInterrupt, asyncio.CancelledError):
            if self.task_manager is not None and not turn_task.done():
                self.task_manager.adopt_running(turn_task, "main-turn")
                self.console.print("\n[yellow](已转入后台继续)[/yellow]")
            else:
                turn_task.cancel()
                del self.conversation.history[mark:]
                self.console.print("\n[yellow](已中断)[/yellow]")
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
