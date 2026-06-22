"""AgentTool：主 Agent 调用本工具按 subagent_type 启子 Agent 或 fork 当前对话。"""

from __future__ import annotations

import dataclasses

from pydantic import BaseModel, Field

from aixcode.agents.fork import ForkError, build_forked_messages
from aixcode.agents.loader import AgentLoader
from aixcode.agents.parser import AgentDef
from aixcode.agents.task_manager import TaskManager
from aixcode.agents.tool_filter import resolve_agent_tools
from aixcode.agents.trace import TraceManager
from aixcode.client import create_client
from aixcode.commands.handlers.mode import parse_mode_name
from aixcode.config import ProviderConfig
from aixcode.conversation import ConversationManager
from aixcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from aixcode.tools.base import Tool, ToolResult

# 复用 ch10 /mode 的权威解析，未识别回退 DEFAULT
def PERMISSION_MODE_MAP(name: str) -> PermissionMode:
    return parse_mode_name(name) or PermissionMode.DEFAULT


async def run_to_completion(sub_agent, conversation) -> str:
    """驱动子 Agent 的 run 异步流，累计正文，到 LoopComplete 取最终文本返回。"""
    from aixcode.agent import ErrorEvent, LoopComplete, StreamText

    parts: list[str] = []
    async for event in sub_agent.run(conversation):
        if isinstance(event, StreamText):
            parts.append(event.text)
        elif isinstance(event, ErrorEvent):
            parts.append(f"[error: {event.message}]")
        elif isinstance(event, LoopComplete):
            return event.text or "".join(parts)
    return "".join(parts)


class AgentToolParams(BaseModel):
    """Agent 工具参数。"""

    prompt: str = Field(..., description="交给子 Agent 的任务描述")
    description: str = Field(..., description="对本次 spawn 的简短说明（3-5 词）")
    subagent_type: str = ""
    model: str = ""
    run_in_background: bool = False
    isolation: str | None = None


def _build_description(loader: AgentLoader, enable_fork: bool) -> str:
    lines = [
        "启动一个上下文隔离的子 Agent 去独立完成一件任务。",
        "按 subagent_type 选专家子 Agent；可用类型：",
    ]
    for name, when in loader.get_catalog():
        lines.append(f"- {name}: {when}")
    if enable_fork:
        lines.append(
            "不带 subagent_type 时 fork 当前对话上下文跑一个临时子 Agent（强制后台）。"
        )
    lines.append("run_in_background=True 时后台执行并立即返回 Task ID。")
    return "\n".join(lines)


class AgentTool(Tool):
    """把「开子 Agent」做成主 Agent 可调用的普通工具。"""

    name = "Agent"
    description = "启动子 Agent"  # 实例化时按 catalog 动态覆盖
    params_model = AgentToolParams
    category = "command"
    is_system_tool = False
    is_concurrency_safe = False

    def __init__(
        self,
        agent_loader: AgentLoader,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        parent_agent,
        provider_config: ProviderConfig,
        enable_fork: bool = False,
        worktree_manager=None,
    ) -> None:
        self.agent_loader = agent_loader
        self.task_manager = task_manager
        self.trace_manager = trace_manager
        self.parent_agent = parent_agent
        self.provider_config = provider_config
        self.enable_fork = enable_fork
        self.worktree_manager = worktree_manager
        # 实例级描述覆盖类属性（动态拼可用类型）
        self.description = _build_description(agent_loader, enable_fork)

    def get_schema(self):
        # 用实例 description 而非类属性
        parameters = self.params_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }

    # --- 模型路由 ---

    def _select_model(self, params: AgentToolParams, definition: AgentDef) -> str | None:
        """params.model > definition.model(≠inherit) > None（继承父 client）。"""
        if params.model:
            return params.model
        if definition.model and definition.model != "inherit":
            return definition.model
        return None

    def _create_client_for_model(self, model: str):
        """复制 provider_config 换 model 建 client；失败回退父 client。"""
        try:
            cfg = dataclasses.replace(self.provider_config, model=model)
            return create_client(cfg)
        except Exception:  # noqa: BLE001
            return getattr(self.parent_agent, "client", None)

    # --- 构建子 Agent ---

    def _build_permission_checker(self, definition: AgentDef, work_dir: str):
        """独立 PermissionChecker：新 sandbox + 独立 mode；复用父 detector/rule_engine。"""
        parent_checker = getattr(self.parent_agent, "permission_checker", None)
        if parent_checker is not None:
            detector = parent_checker.detector
            rule_engine = parent_checker.rule_engine
        else:
            detector = DangerousCommandDetector()
            rule_engine = RuleEngine(user_rules_path="", project_rules_path="")
        mode = PERMISSION_MODE_MAP(definition.permission_mode)
        return PermissionChecker(
            detector=detector,
            sandbox=PathSandbox(project_root=work_dir),
            rule_engine=rule_engine,
            mode=mode,
        )

    def _build_sub_agent(self, definition, tools_registry, model_client, work_dir):
        """建独立运行态子 Agent：复用父 hook_engine，独立 checker / token / 会话。"""
        from aixcode.agent import Agent

        client = model_client or getattr(self.parent_agent, "client", None)
        return Agent(
            client,
            tools_registry,
            protocol=self.provider_config.protocol,
            work_dir=work_dir,
            max_iterations=definition.max_turns,
            permission_checker=self._build_permission_checker(definition, work_dir),
            context_window=getattr(self.parent_agent, "context_window", 200000),
            hook_engine=getattr(self.parent_agent, "hook_engine", None),
        )

    async def execute(self, params: AgentToolParams) -> ToolResult:
        """三路径分发：未知类型报错 / fork（强制后台）/ 定义式（sync·background）。"""
        if not params.subagent_type:
            return await self._execute_fork(params)
        definition = self.agent_loader.get(params.subagent_type)
        if definition is None:
            available = ", ".join(n for n, _ in self.agent_loader.get_catalog())
            return ToolResult(
                f"未知 subagent_type: {params.subagent_type}。可用类型：{available}",
                is_error=True,
            )
        isolation = params.isolation or definition.isolation
        if isolation == "worktree":
            return await self._execute_with_worktree(params, definition)
        return await self._execute_definition(params, definition)

    async def _execute_with_worktree(
        self, params: AgentToolParams, definition: AgentDef
    ) -> ToolResult:
        """Agent 级 worktree 隔离：建独立 worktree → 跑子 Agent → 按变更自动清理。"""
        if self.worktree_manager is None:
            return ToolResult(
                "worktree 隔离不可用（worktree_manager 未装配）。", is_error=True
            )
        from aixcode.worktree.integration import (
            build_worktree_notice,
            generate_worktree_name,
        )

        wt_name = generate_worktree_name()
        try:
            wt = await self.worktree_manager.create(wt_name, "HEAD")
        except Exception as e:  # noqa: BLE001
            return ToolResult(f"创建 worktree 失败：{e}", is_error=True)

        parent_cwd = getattr(self.parent_agent, "work_dir", ".")
        notice = build_worktree_notice(parent_cwd, wt.path)
        task = f"{notice}\n\n{params.prompt}"

        registry = resolve_agent_tools(
            self.parent_agent.registry, definition, is_background=False
        )
        model = self._select_model(params, definition)
        client = self._create_client_for_model(model) if model else None
        sub_agent = self._build_sub_agent(definition, registry, client, wt.path)
        node = self.trace_manager.create(definition.agent_type)

        try:
            text = await run_to_completion(sub_agent, self._fresh_conv(task))
        except Exception as e:  # noqa: BLE001
            self.trace_manager.complete(node.agent_id, "failed")
            return ToolResult(f"子 Agent 执行失败：{e}", is_error=True)
        self.trace_manager.update(
            node.agent_id,
            input_tokens=getattr(sub_agent, "total_input_tokens", 0),
            output_tokens=getattr(sub_agent, "total_output_tokens", 0),
        )
        self.trace_manager.complete(node.agent_id, "completed")

        cleanup = await self.worktree_manager.auto_cleanup(wt_name, wt.head_commit)
        if cleanup.kept:
            text += (
                f"\n\n[Worktree preserved at {cleanup.path}, branch {cleanup.branch}]"
            )
        return ToolResult(text)

    async def _execute_fork(self, params: AgentToolParams) -> ToolResult:
        if not self.enable_fork:
            return ToolResult(
                "未启用 fork：请指定 subagent_type 选择一个子 Agent 类型。",
                is_error=True,
            )
        conversation = getattr(self.parent_agent, "active_conversation", None)
        if conversation is None:
            return ToolResult("无可 fork 的当前对话。", is_error=True)
        try:
            forked_conv = build_forked_messages(conversation, params.prompt)
        except ForkError as e:
            return ToolResult(str(e), is_error=True)

        fork_def = AgentDef(
            agent_type="fork", when_to_use="forked", system_prompt="",
            background=True, source="builtin",
        )
        work_dir = getattr(self.parent_agent, "work_dir", ".")
        registry = resolve_agent_tools(
            self.parent_agent.registry, fork_def, is_background=True
        )
        sub_agent = self._build_sub_agent(fork_def, registry, None, work_dir)
        node = self.trace_manager.create("fork")
        task_id = self.task_manager.launch(
            self._make_runner(sub_agent, forked_conv, node), "fork"
        )
        return ToolResult(f"已 fork 子 Agent 后台执行。Task ID: {task_id}")

    async def _execute_definition(
        self, params: AgentToolParams, definition: AgentDef
    ) -> ToolResult:
        is_background = params.run_in_background or definition.background
        work_dir = getattr(self.parent_agent, "work_dir", ".")
        registry = resolve_agent_tools(
            self.parent_agent.registry, definition, is_background
        )
        model = self._select_model(params, definition)
        client = self._create_client_for_model(model) if model else None
        sub_agent = self._build_sub_agent(definition, registry, client, work_dir)
        node = self.trace_manager.create(definition.agent_type)

        if is_background:
            task_id = self.task_manager.launch(
                self._make_runner(sub_agent, self._fresh_conv(params.prompt), node),
                definition.agent_type,
            )
            return ToolResult(f"已后台启动子 Agent。Task ID: {task_id}")

        # 前台同步：跑到底返回最终文本；异常标 failed 不抛
        try:
            text = await run_to_completion(sub_agent, self._fresh_conv(params.prompt))
        except Exception as e:  # noqa: BLE001
            self.trace_manager.complete(node.agent_id, "failed")
            return ToolResult(f"子 Agent 执行失败：{e}", is_error=True)
        self.trace_manager.update(
            node.agent_id,
            input_tokens=getattr(sub_agent, "total_input_tokens", 0),
            output_tokens=getattr(sub_agent, "total_output_tokens", 0),
        )
        self.trace_manager.complete(node.agent_id, "completed")
        return ToolResult(text)

    @staticmethod
    def _fresh_conv(prompt: str) -> ConversationManager:
        conv = ConversationManager()
        conv.add_user_message(prompt)
        return conv

    def _make_runner(self, sub_agent, conversation, node):
        """后台任务协程工厂：跑子 Agent，更新 trace，返回 (text, in, out)。"""
        async def runner():
            try:
                text = await run_to_completion(sub_agent, conversation)
            except Exception:
                self.trace_manager.complete(node.agent_id, "failed")
                raise
            in_tok = getattr(sub_agent, "total_input_tokens", 0)
            out_tok = getattr(sub_agent, "total_output_tokens", 0)
            self.trace_manager.update(
                node.agent_id, input_tokens=in_tok, output_tokens=out_tok
            )
            self.trace_manager.complete(node.agent_id, "completed")
            return (text, in_tok, out_tok)

        return runner
