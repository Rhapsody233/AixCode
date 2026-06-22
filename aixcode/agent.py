"""Agent Loop：多轮 ReAct 循环 + 对外事件流 + Plan Mode + 可取消。

取代 ch03 的单轮 turn.py（单轮是本循环跑一次的特例）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import ValidationError

from aixcode.context import (
    CompactEvent,
    CompactCircuitBreaker,
    RecoveryState,
    append_replacement_records,
    apply_tool_result_budget,
    auto_compact,
    create_replacement_state,
    ensure_session_dir,
)
from aixcode.context.manager import DEFAULT_CONTEXT_WINDOW
from aixcode.permissions import (
    PermissionChecker,
    PermissionMode,
    Rule,
    extract_content,
)
from aixcode.memory import load_instructions
from aixcode.prompts import (
    build_active_skills_reminder,
    build_environment_context,
    build_plan_mode_reminder,
    build_system_prompt,
)
from aixcode.tools import ToolRegistry
from aixcode.tools.base import (
    MAX_OUTPUT_CHARS,
    StreamEnd,
    TextDelta,
    ThinkingDelta,
    ToolCallComplete,
    ToolResult,
)

MAX_ITERATIONS = 50
MEMORY_EXTRACTION_INTERVAL = 5

logger = logging.getLogger(__name__)


# --- 对外事件 ---------------------------------------------------------------

@dataclass
class StreamText:
    """模型正文增量。"""

    text: str


@dataclass
class ThinkingText:
    """模型思考增量。"""

    text: str


@dataclass
class ToolUseEvent:
    """一个工具即将执行。"""

    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ToolResultEvent:
    """一个工具执行完毕。"""

    tool_name: str
    output: str
    is_error: bool
    arguments: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0


@dataclass
class TurnComplete:
    """一轮（含工具执行）结束，循环将继续。"""


@dataclass
class UsageEvent:
    """一轮的 token 用量与缓存命中。"""

    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int = 0


@dataclass
class LoopComplete:
    """循环结束，携带最终回复文本。"""

    text: str


@dataclass
class ErrorEvent:
    """循环出错。"""

    message: str


@dataclass
class CompactNotification:
    """上下文已被自动/手动压缩，携带压缩前的 token 数。"""

    before_tokens: int


# --- 权限 HITL --------------------------------------------------------------

class PermissionResponse(Enum):
    """用户对一次 ask 的回应（终端 4 选项）。"""

    ALLOW = "allow"
    ALLOW_SESSION = "allow_session"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


@dataclass
class PermissionRequest:
    """工具执行被判 ask 时产出，等终端 set_result(future) 回填用户选择。"""

    tool_name: str
    description: str
    future: "asyncio.Future[PermissionResponse]"


@dataclass
class HookEvent:
    """一次 hook 执行结果，转给 TUI 展示。"""

    hook_id: str
    event: str
    output: str
    success: bool


AgentEvent = (
    StreamText
    | ThinkingText
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | UsageEvent
    | LoopComplete
    | ErrorEvent
    | PermissionRequest
    | CompactNotification
    | HookEvent
)


# --- 工具批次切分 -----------------------------------------------------------

@dataclass
class ToolBatch:
    """一批工具调用。concurrent=True 可并发，否则串行。"""

    concurrent: bool
    calls: list[ToolCallComplete] = field(default_factory=list)


def partition_tool_calls(
    tool_calls: list[ToolCallComplete], registry: ToolRegistry
) -> list[ToolBatch]:
    """把一轮工具调用切成批：相邻的并发安全工具聚为并发批，写/命令类各自串行。"""
    batches: list[ToolBatch] = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        safe = (
            tool is not None
            and tool.is_concurrency_safe
            and registry.is_enabled(tc.tool_name)
        )
        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)
        else:
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
    return batches


# --- 流式聚合 ---------------------------------------------------------------

@dataclass
class CollectedResponse:
    """一次流式响应聚合后的结果。"""

    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCallComplete] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0


def _to_request_tool_calls(tool_calls: list[ToolCallComplete]) -> list[dict[str, Any]]:
    """把 ToolCallComplete 还原为 chat-completions 请求体里的 tool_calls。"""
    return [
        {
            "id": tc.tool_id,
            "type": "function",
            "function": {
                "name": tc.tool_name,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
            },
        }
        for tc in tool_calls
    ]


# --- Agent ------------------------------------------------------------------

class Agent:
    """多轮 ReAct 循环本体。"""

    def __init__(
        self,
        client,
        registry: ToolRegistry,
        protocol: str = "openai",
        work_dir: str = ".",
        max_iterations: int = MAX_ITERATIONS,
        permission_checker: PermissionChecker | None = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        memory_manager=None,
        hook_engine=None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.protocol = protocol
        self.hook_engine = hook_engine
        self.work_dir = work_dir
        self.max_iterations = max_iterations
        self.permission_checker = permission_checker
        self.permission_mode = PermissionMode.DEFAULT
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # ch09 记忆系统：项目指令走对话通道，自动记忆按轮提取
        self.instructions_content = load_instructions(work_dir)
        self.memory_manager = memory_manager
        self._loop_count = 0
        self._extracting = False
        # ch11 Skill 系统：active_skills 名→已渲染 SOP；catalog 为静态清单
        self.active_skills: dict[str, str] = {}
        self._skill_catalog: str = ""
        # ch13 SubAgent：fork 时由 AgentTool 读取的当前活跃对话
        self.active_conversation = None
        # ch15 AgentTeam：本 Agent 的稳定标识 + 团队上下文（mailbox 寻址、协调模式）
        self.agent_id = uuid.uuid4().hex[:12]
        self.team_name: str = ""
        self.coordinator_mode: bool = False
        self._team_manager = None
        # ch08 上下文管理
        self.context_window = context_window
        self.session_dir = ensure_session_dir(work_dir)
        self.replacement_state = create_replacement_state()
        self.recovery_state = RecoveryState()
        self._compact_breaker = CompactCircuitBreaker()

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        if self.permission_checker is not None:
            self.permission_checker.mode = mode

    # --- ch11 Skill 系统 ---

    def activate_skill(self, name: str, prompt_body: str) -> None:
        """把一个 skill 的已渲染 SOP 钉到上下文（下一轮起注入提醒）。"""
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        """清空已激活 skill（/clear 时调用，避免新对话残留旧 SOP）。"""
        self.active_skills = {}

    def set_skill_catalog(self, catalog: str) -> None:
        """设置随环境一次性注入的 skill 静态清单。"""
        self._skill_catalog = catalog

    # --- ch12 Hook 系统 ---

    def _build_hook_context(
        self, event: str, tool_name=None, tool_args=None, message=None, error=None
    ):
        from aixcode.hooks import HookContext

        return HookContext(
            event_name=event,
            tool_name=tool_name,
            tool_args=tool_args or {},
            message=message,
            error=error,
        )

    def _drain_hook_events(self) -> list[HookEvent]:
        """把引擎累积的通知转成 HookEvent（engine 为 None 时空）。"""
        if self.hook_engine is None:
            return []
        return [
            HookEvent(n.hook_id, n.event, n.output, n.success)
            for n in self.hook_engine.drain_notifications()
        ]

    async def _emit_hooks(self, event: str, ctx) -> list[HookEvent]:
        """触发普通事件钩子并返回产生的 HookEvent（engine 为 None 时 no-op）。"""
        if self.hook_engine is None:
            return []
        await self.hook_engine.run_hooks(event, ctx)
        return self._drain_hook_events()

    def _inject_context(self, conversation) -> None:
        """把环境信息 + 长期记忆（项目指令 + 自动记忆）注入对话通道（各自幂等）。"""
        conversation.inject_environment(
            build_environment_context(self.work_dir, self._skill_catalog)
        )
        memories = self.memory_manager.load() if self.memory_manager else ""
        conversation.inject_long_term_memory(self.instructions_content, memories)

    async def _consume_mailbox(self, conversation) -> None:
        """ch15：把团队邮箱里发给本 Agent 的消息转 user message 注入对话；异常吞掉。

        仅当 team_name 与 _team_manager 都非空时生效（Lead 与 in-process 队员共用）。
        """
        if not (self.team_name and self._team_manager):
            return
        try:
            mailbox = self._team_manager.get_mailbox(self.team_name)
            if mailbox is None:
                return
            for msg in mailbox.consume(self.agent_id):
                if msg.message_type == "text":
                    prefix = f"[Message from {msg.from_agent}] "
                else:
                    prefix = f"[{msg.message_type} from {msg.from_agent}] "
                conversation.add_user_message(prefix + msg.content)
        except Exception as e:  # noqa: BLE001
            logger.debug("消费团队邮箱失败：%s", e)

    async def run(self, conversation) -> AsyncIterator[AgentEvent]:
        """多轮 ReAct 循环：调模型→执行工具→回灌→下一轮；无工具调用即结束。"""
        # 暴露当前活跃对话给 AgentTool 的 fork 路径（ch13）
        self.active_conversation = conversation
        # 启动时把环境与长期记忆注入对话通道（幂等），不进系统提示以保前缀缓存
        self._inject_context(conversation)

        # ch12：session_start 钩子
        for ev in await self._emit_hooks(
            "session_start", self._build_hook_context("session_start")
        ):
            yield ev

        iteration = 0
        while True:
            iteration += 1
            if iteration > self.max_iterations:
                yield ErrorEvent(f"超过最大轮数 {self.max_iterations}，已停止")
                return

            # ch15：每轮开头先消费团队邮箱（在调 LLM 之前，避免一轮延迟）
            await self._consume_mailbox(conversation)

            # ch12：turn_start 钩子
            for ev in await self._emit_hooks(
                "turn_start", self._build_hook_context("turn_start")
            ):
                yield ev

            # Layer 2：每轮顶按阈值决定是否整段摘要（昂贵兜底）
            compact_result = await auto_compact(
                conversation,
                self.client,
                self.context_window,
                self.session_dir,
                breaker=self._compact_breaker,
                recovery=self.recovery_state,
                tool_schemas=self.registry.get_all_schemas(),
            )
            if isinstance(compact_result, CompactEvent):
                # 压缩替换了整段历史（replace_history 已重置注入标记），重注入上下文
                self._inject_context(conversation)
                yield CompactNotification(compact_result.before_tokens)

            # Plan 模式：每轮按节奏经 <system-reminder> 注入提醒
            if self.permission_mode == PermissionMode.PLAN:
                conversation.add_system_reminder(build_plan_mode_reminder(iteration))

            # ch11：已激活 skill 的 SOP 每轮经对话通道重注入，钉在最显眼位置
            if self.active_skills:
                conversation.add_system_reminder(
                    build_active_skills_reminder(self.active_skills)
                )

            # ch12：pre_send 钩子；prompt 类型 hook 输出注入本轮请求
            for ev in await self._emit_hooks(
                "pre_send", self._build_hook_context("pre_send")
            ):
                yield ev
            if self.hook_engine is not None:
                for msg in self.hook_engine.get_prompt_messages():
                    conversation.add_system_reminder(msg)

            system = build_system_prompt(
                deferred_tools=self.registry.get_deferred_tool_names(),
                coordinator_mode=self.coordinator_mode,
            )
            tools = self.registry.get_all_schemas()

            # Layer 1：client.stream 前最后一刻做廉价预算控制（不动原 conversation）
            api_conv, new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            append_replacement_records(self.session_dir, new_records)

            response = CollectedResponse()
            async for event in self.client.stream(
                api_conv, tools=tools, system=system
            ):
                if isinstance(event, TextDelta):
                    response.text += event.text
                    yield StreamText(event.text)
                elif isinstance(event, ThinkingDelta):
                    response.thinking += event.text
                    yield ThinkingText(event.text)
                elif isinstance(event, ToolCallComplete):
                    response.tool_calls.append(event)
                    yield ToolUseEvent(event.tool_id, event.tool_name, event.arguments)
                elif isinstance(event, StreamEnd):
                    response.input_tokens = event.input_tokens
                    response.output_tokens = event.output_tokens
                    response.cache_hit_tokens = event.cache_hit_tokens

            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens
            conversation.last_input_tokens = response.input_tokens
            yield UsageEvent(
                response.input_tokens,
                response.output_tokens,
                response.cache_hit_tokens,
            )

            # ch12：post_receive 钩子
            for ev in await self._emit_hooks(
                "post_receive", self._build_hook_context("post_receive")
            ):
                yield ev

            if not response.tool_calls:
                conversation.add_assistant_message(response.text)
                # loop 收尾：按节奏 fire-and-forget 跑一次自动记忆提取
                self._loop_count += 1
                if (
                    self.memory_manager is not None
                    and self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0
                ):
                    asyncio.ensure_future(self._extract_memories(conversation))
                # ch12：turn_end + session_end 钩子（无工具调用即收尾）
                for ev in await self._emit_hooks(
                    "turn_end", self._build_hook_context("turn_end")
                ):
                    yield ev
                for ev in await self._emit_hooks(
                    "session_end", self._build_hook_context("session_end")
                ):
                    yield ev
                yield LoopComplete(response.text)
                return

            conversation.add_assistant_message(
                response.text, tool_calls=_to_request_tool_calls(response.tool_calls)
            )

            # 先串行解析权限（ask 在此处串行 HITL）；denied 映射 tool_id→回灌结果
            denied: dict[str, ToolResult] = {}
            for tc in response.tool_calls:
                outcome = self._resolve_permission(tc)
                if outcome is not None and not isinstance(outcome, ToolResult):
                    # ask：产出请求事件，等终端回填
                    future: asyncio.Future[PermissionResponse] = (
                        asyncio.get_event_loop().create_future()
                    )
                    yield PermissionRequest(tc.tool_name, outcome, future)
                    resp = await future
                    decided = self._apply_response(resp, tc)
                    if decided is not None:
                        denied[tc.tool_id] = decided
                elif isinstance(outcome, ToolResult):
                    denied[tc.tool_id] = outcome

            # ch12：pre_tool_use 钩子（可拦截）；复用 denied 跳过+回灌路径
            if self.hook_engine is not None:
                for tc in response.tool_calls:
                    if tc.tool_id in denied:
                        continue
                    rejection = await self.hook_engine.run_pre_tool_hooks(
                        self._build_hook_context(
                            "pre_tool_use", tc.tool_name, tc.arguments
                        )
                    )
                    for ev in self._drain_hook_events():
                        yield ev
                    if rejection is not None:
                        denied[tc.tool_id] = ToolResult(
                            f"Hook rejected: {rejection.reason}", is_error=True
                        )

            for batch in partition_tool_calls(response.tool_calls, self.registry):
                runnable = [tc for tc in batch.calls if tc.tool_id not in denied]
                if batch.concurrent and len(runnable) > 1:
                    pairs = await asyncio.gather(
                        *[self._run_tool_timed(tc) for tc in runnable]
                    )
                else:
                    pairs = [await self._run_tool_timed(tc) for tc in runnable]
                run_map = {tc.tool_id: pair for tc, pair in zip(runnable, pairs)}
                for tc in batch.calls:
                    if tc.tool_id in denied:
                        result, duration = denied[tc.tool_id], 0.0
                    else:
                        result, duration = run_map[tc.tool_id]
                    yield ToolResultEvent(
                        tc.tool_name,
                        result.output,
                        result.is_error,
                        tc.arguments,
                        duration,
                    )
                    conversation.add_tool_result(tc.tool_id, result.output)
                    # ch12：post_tool_use 钩子
                    for ev in await self._emit_hooks(
                        "post_tool_use",
                        self._build_hook_context(
                            "post_tool_use", tc.tool_name, tc.arguments
                        ),
                    ):
                        yield ev

            # ch12：turn_end 钩子（本轮有工具调用，继续下一轮）
            for ev in await self._emit_hooks(
                "turn_end", self._build_hook_context("turn_end")
            ):
                yield ev
            yield TurnComplete()

    async def _run_tool_timed(self, tc: ToolCallComplete) -> tuple[ToolResult, float]:
        start = time.perf_counter()
        result = await self._run_tool(tc)
        return result, time.perf_counter() - start

    def _resolve_permission(
        self, tc: ToolCallComplete
    ) -> ToolResult | str | None:
        """解析一次工具调用的权限：None=放行执行；ToolResult=回灌该错误不执行；
        str=需 HITL（返回值为请求描述）。"""
        if self.permission_checker is None:
            return None
        tool = self.registry.get(tc.tool_name)
        if tool is None or not self.registry.is_enabled(tc.tool_name):
            return None  # 未知/停用工具留给 _run_tool 出结构化错误
        decision = self.permission_checker.check(tool, tc.arguments)
        if decision.effect == "allow":
            return None
        if decision.effect == "deny":
            return ToolResult(
                f"Error: permission denied: {decision.reason}", is_error=True
            )
        return self._describe(tc)  # ask

    def _apply_response(
        self, resp: PermissionResponse, tc: ToolCallComplete
    ) -> ToolResult | None:
        """据用户回应决定执行（返 None）或回灌拒绝（返 ToolResult）；按需自学习。"""
        if resp == PermissionResponse.DENY:
            return ToolResult(
                "Error: permission denied: 用户拒绝了本次操作", is_error=True
            )
        if resp == PermissionResponse.ALLOW_SESSION:
            self.permission_checker.rule_engine.add_session_rule(self._learn_rule(tc))
        elif resp == PermissionResponse.ALLOW_ALWAYS:
            self.permission_checker.rule_engine.append_project_rule(self._learn_rule(tc))
        return None

    def _learn_rule(self, tc: ToolCallComplete) -> Rule:
        """把工具主参数包成放行规则：超 60 字符截断 + `*` 通配。"""
        content = extract_content(tc.tool_name, tc.arguments)
        pattern = content[:60] + "*" if len(content) > 60 else content
        return Rule(tc.tool_name, pattern, "allow")

    @staticmethod
    def _describe(tc: ToolCallComplete) -> str:
        content = extract_content(tc.tool_name, tc.arguments)
        return f"{tc.tool_name}({content})" if content else tc.tool_name

    async def _run_tool(self, tc: ToolCallComplete) -> ToolResult:
        """查工具 + 参数校验 + 执行 + 结果截断。失败包成结构化错误。

        执行期间把本 Agent 的 work_dir 注入 contextvar，文件工具据此解析相对路径
        （子 Agent / worktree 隔离的关键）；执行后恢复，避免泄漏到其他 Agent。
        """
        from aixcode.tools.workdir import pop_work_dir, push_work_dir

        token = push_work_dir(self.work_dir)
        try:
            tool = self.registry.get(tc.tool_name)
            if tool is None:
                return ToolResult(f"Error: unknown tool: {tc.tool_name}", is_error=True)
            if not self.registry.is_enabled(tc.tool_name):
                return ToolResult(f"Error: tool disabled: {tc.tool_name}", is_error=True)

            try:
                params = tool.params_model.model_validate(tc.arguments)
            except ValidationError as e:
                return ToolResult(f"Error: invalid arguments: {e}", is_error=True)

            result = await tool.execute(params)
            self._snapshot_for_recovery(tc, result)
            if len(result.output) > MAX_OUTPUT_CHARS:
                return ToolResult(
                    result.output[:MAX_OUTPUT_CHARS] + "… (output truncated)",
                    is_error=result.is_error,
                )
            return result
        finally:
            pop_work_dir(token)

    def _snapshot_for_recovery(self, tc: ToolCallComplete, result: ToolResult) -> None:
        """ReadFile 成功后把整文件字节快照写入 recovery_state（压缩后恢复用）。"""
        if result.is_error or tc.tool_name != "ReadFile":
            return
        path = tc.arguments.get("file_path")
        if not path:
            return
        try:
            content = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            return
        self.recovery_state.record_file_read(path, content)

    async def _extract_memories(self, conversation) -> None:
        """fire-and-forget 自动记忆提取：互斥防重入，异常不传播。"""
        if self._extracting:
            return
        self._extracting = True
        try:
            await self.memory_manager.extract(self.client, conversation)
        except Exception as e:  # noqa: BLE001
            logger.debug("自动记忆提取失败：%s", e)
        finally:
            self._extracting = False

    async def manual_compact(self, conversation):
        """手动压缩入口（/compact）：直接走 Layer 2，更小安全余量。"""
        result = await auto_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            manual=True,
            breaker=self._compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(),
        )
        if isinstance(result, CompactEvent):
            return CompactNotification(result.before_tokens)
        return result  # 错误字符串或 None
