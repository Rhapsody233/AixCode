import asyncio

import pytest

from aixcode.agent import (
    Agent,
    CompactNotification,
    ErrorEvent,
    LoopComplete,
    PermissionMode,
    PermissionRequest,
    PermissionResponse,
    StreamText,
    ToolBatch,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
    partition_tool_calls,
)
from aixcode.context import manager as ctx
from aixcode.conversation import ConversationManager
from aixcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    RuleEngine,
)
from aixcode.tools import create_default_registry
from aixcode.tools.base import (
    StreamEnd,
    TextDelta,
    Tool,
    ToolCallComplete,
    ToolResult,
)
from pydantic import BaseModel


class MockLLMClient:
    """脚本化客户端：每次 stream 吐出预设的一段 StreamEvent。"""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.systems_seen = []

    async def stream(self, conversation, tools=None, system=None):
        self.systems_seen.append(system)
        for event in self._scripts.pop(0):
            yield event


def _drive(agent, conv):
    async def go():
        return [event async for event in agent.run(conv)]

    return asyncio.run(go())


def _tc(name, **args):
    return ToolCallComplete("id_" + name, name, args)


class _DummyClient:
    async def stream(self, conversation, tools=None, system=None):
        if False:
            yield None  # 占位 async generator，T4 不触发


def _agent(permission_checker=None):
    return Agent(
        _DummyClient(),
        create_default_registry(),
        permission_checker=permission_checker,
    )


def test_partition_groups_adjacent_concurrent_safe():
    # ReadFile/Glob/Grep 是 is_concurrency_safe=True；WriteFile/Bash 不是
    registry = create_default_registry()
    calls = [_tc("ReadFile"), _tc("Glob"), _tc("WriteFile"), _tc("Grep"), _tc("ReadFile")]

    batches = partition_tool_calls(calls, registry)

    # [Read,Glob] 并发 / [Write] 串行 / [Grep,Read] 并发
    assert len(batches) == 3
    assert batches[0].concurrent is True
    assert [c.tool_name for c in batches[0].calls] == ["ReadFile", "Glob"]
    assert batches[1].concurrent is False
    assert [c.tool_name for c in batches[1].calls] == ["WriteFile"]
    assert batches[2].concurrent is True
    assert [c.tool_name for c in batches[2].calls] == ["Grep", "ReadFile"]


def test_partition_single_write_is_serial_batch():
    registry = create_default_registry()
    batches = partition_tool_calls([_tc("WriteFile")], registry)
    assert len(batches) == 1
    assert batches[0].concurrent is False


def test_partition_disabled_tool_not_concurrent():
    registry = create_default_registry()
    registry.disable("ReadFile")
    # disabled 的 ReadFile 不能进并发批
    batches = partition_tool_calls([_tc("ReadFile"), _tc("Glob")], registry)
    assert batches[0].concurrent is False


# --- 权限：HITL 与自学习（走 run 主循环）-----------------------------------

def _checker(tmp_path, mode=PermissionMode.DEFAULT):
    return PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(project_root=str(tmp_path)),
        rule_engine=RuleEngine(
            user_rules_path=str(tmp_path / "user.yaml"),
            project_rules_path=str(tmp_path / "project.yaml"),
        ),
        mode=mode,
    )


def _drive_hitl(agent, conv, responder):
    """消费事件流；遇 PermissionRequest 用 responder(req) 的返回值 set_result。"""
    async def go():
        events = []
        async for event in agent.run(conv):
            if isinstance(event, PermissionRequest):
                event.future.set_result(responder(event))
            events.append(event)
        return events

    return asyncio.run(go())


def test_dangerous_command_denied_and_not_executed(tmp_path):
    client = MockLLMClient([
        [ToolCallComplete("c1", "Bash", {"command": "rm -rf /"}), StreamEnd(1, 1)],
        [TextDelta("已停手"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), permission_checker=_checker(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("删库")

    events = _drive_hitl(agent, conv, lambda req: PermissionResponse.ALLOW)

    denied = [e for e in events if isinstance(e, ToolResultEvent) and e.is_error]
    assert any("危险命令" in e.output for e in denied)
    # 危险命令不该走到 ask（直接 deny），也不产生 PermissionRequest
    assert not any(isinstance(e, PermissionRequest) for e in events)


def test_ask_then_allow_executes(tmp_path):
    target = tmp_path / "out.txt"
    client = MockLLMClient([
        [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "hi"}), StreamEnd(1, 1)],
        [TextDelta("写好了"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), permission_checker=_checker(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("写文件")

    events = _drive_hitl(agent, conv, lambda req: PermissionResponse.ALLOW)

    assert any(isinstance(e, PermissionRequest) for e in events)
    assert target.read_text(encoding="utf-8") == "hi"
    assert not any(isinstance(e, ToolResultEvent) and e.is_error for e in events)


def test_ask_then_deny_blocks(tmp_path):
    target = tmp_path / "out.txt"
    client = MockLLMClient([
        [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "hi"}), StreamEnd(1, 1)],
        [TextDelta("好的不写"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), permission_checker=_checker(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("写文件")

    events = _drive_hitl(agent, conv, lambda req: PermissionResponse.DENY)

    assert not target.exists()
    assert any(isinstance(e, ToolResultEvent) and e.is_error for e in events)


def test_allow_always_appends_project_rule(tmp_path):
    target = tmp_path / "out.txt"
    checker = _checker(tmp_path)
    client = MockLLMClient([
        [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "hi"}), StreamEnd(1, 1)],
        [TextDelta("已记住"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), permission_checker=checker)
    conv = ConversationManager()
    conv.add_user_message("写文件")

    _drive_hitl(agent, conv, lambda req: PermissionResponse.ALLOW_ALWAYS)

    project_file = tmp_path / "project.yaml"
    assert project_file.exists()
    assert "WriteFile" in project_file.read_text(encoding="utf-8")
    # 再写同路径应直接 allow（不再 ask）
    assert checker.check(create_default_registry().get("WriteFile"),
                         {"file_path": str(target), "content": "x"}).effect == "allow"


def test_allow_session_adds_session_rule(tmp_path):
    target = tmp_path / "out.txt"
    checker = _checker(tmp_path)
    client = MockLLMClient([
        [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "hi"}), StreamEnd(1, 1)],
        [TextDelta("ok"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), permission_checker=checker)
    conv = ConversationManager()
    conv.add_user_message("写文件")

    _drive_hitl(agent, conv, lambda req: PermissionResponse.ALLOW_SESSION)

    # 会话规则在内存里命中，但项目文件不应被写
    assert not (tmp_path / "project.yaml").exists()
    assert checker.check(create_default_registry().get("WriteFile"),
                         {"file_path": str(target), "content": "x"}).effect == "allow"


def test_plan_mode_denies_write_via_checker(tmp_path):
    target = tmp_path / "out.txt"
    agent = Agent(
        MockLLMClient([
            [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "x"}), StreamEnd(1, 1)],
            [TextDelta("这是计划"), StreamEnd(1, 1)],
        ]),
        create_default_registry(),
        permission_checker=_checker(tmp_path),
    )
    agent.set_permission_mode(PermissionMode.PLAN)
    conv = ConversationManager()
    conv.add_user_message("改 out.txt")

    events = _drive_hitl(agent, conv, lambda req: PermissionResponse.ALLOW)

    denied = [e for e in events if isinstance(e, ToolResultEvent) and e.is_error]
    assert any("permission denied" in e.output.lower() for e in denied)
    assert not target.exists()


def test_no_checker_allows_all(tmp_path):
    target = tmp_path / "out.txt"
    agent = Agent(
        MockLLMClient([
            [ToolCallComplete("c1", "WriteFile", {"file_path": str(target), "content": "hi"}), StreamEnd(1, 1)],
            [TextDelta("done"), StreamEnd(1, 1)],
        ]),
        create_default_registry(),
    )
    conv = ConversationManager()
    conv.add_user_message("写文件")

    events = _drive(agent, conv)

    assert target.read_text(encoding="utf-8") == "hi"
    assert not any(isinstance(e, PermissionRequest) for e in events)


def test_set_permission_mode_syncs_checker(tmp_path):
    checker = _checker(tmp_path)
    agent = Agent(_DummyClient(), create_default_registry(), permission_checker=checker)
    agent.set_permission_mode(PermissionMode.BYPASS)
    assert checker.mode == PermissionMode.BYPASS


def test_unknown_tool_is_error():
    agent = _agent()
    result = asyncio.run(agent._run_tool(_tc("NoSuchTool")))
    assert result.is_error is True
    assert "unknown tool" in result.output.lower()


# --- run 多轮主循环 ---------------------------------------------------------

def test_single_step_tool_call(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    client = MockLLMClient([
        [ToolCallComplete("c1", "ReadFile", {"file_path": str(f)}), StreamEnd(2, 3)],
        [TextDelta("第一行是 hello"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("读 a.txt")

    events = _drive(agent, conv)

    assert any(isinstance(e, ToolUseEvent) and e.tool_name == "ReadFile" for e in events)
    assert any(isinstance(e, ToolResultEvent) and "hello" in e.output for e in events)
    assert isinstance(events[-1], LoopComplete)
    assert events[-1].text == "第一行是 hello"
    # history[0] 是注入的环境消息，其后是本轮的 user/assistant/tool/assistant
    assert conv.env_injected is True
    assert [m.role for m in conv.history[1:]] == ["user", "assistant", "tool", "assistant"]


def test_multi_step_autonomous(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n", encoding="utf-8")
    client = MockLLMClient([
        [ToolCallComplete("c1", "ReadFile", {"file_path": str(f)}), StreamEnd(1, 1)],
        [ToolCallComplete("c2", "Glob", {"pattern": "*", "path": str(tmp_path)}), StreamEnd(1, 1)],
        [TextDelta("完成"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("做两步")

    events = _drive(agent, conv)

    assert sum(isinstance(e, TurnComplete) for e in events) == 2
    assert isinstance(events[-1], LoopComplete)


def test_stop_when_no_tool_calls():
    client = MockLLMClient([[TextDelta("你好"), StreamEnd(4, 2)]])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("hi")

    events = _drive(agent, conv)

    assert not any(isinstance(e, ToolUseEvent) for e in events)
    assert isinstance(events[-1], LoopComplete)
    assert events[-1].text == "你好"


def test_stop_max_iterations():
    class AlwaysTool:
        async def stream(self, conversation, tools=None, system=None):
            yield ToolCallComplete("c", "Glob", {"pattern": "*", "path": "."})
            yield StreamEnd(1, 1)

    agent = Agent(AlwaysTool(), create_default_registry(), max_iterations=2)
    conv = ConversationManager()
    conv.add_user_message("loop forever")

    events = _drive(agent, conv)

    assert isinstance(events[-1], ErrorEvent)
    assert sum(isinstance(e, TurnComplete) for e in events) == 2


def test_cancel_propagates_cleanly():
    class CancelClient:
        async def stream(self, conversation, tools=None, system=None):
            raise asyncio.CancelledError
            yield  # 使其成为 async generator

    agent = Agent(CancelClient(), create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("hi")

    async def go():
        async for _ in agent.run(conv):
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())
    # 取消时 agent 未写入任何 assistant/tool 消息（只有 user 与注入的环境）
    assert all(m.role == "user" for m in conv.history)


def test_concurrent_batch_execution(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("AAA\n", encoding="utf-8")
    b.write_text("BBB\n", encoding="utf-8")
    client = MockLLMClient([
        [
            ToolCallComplete("c1", "ReadFile", {"file_path": str(a)}),
            ToolCallComplete("c2", "ReadFile", {"file_path": str(b)}),
            StreamEnd(1, 1),
        ],
        [TextDelta("读完了"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("读两个文件")

    events = _drive(agent, conv)

    outputs = [e.output for e in events if isinstance(e, ToolResultEvent)]
    assert any("AAA" in o for o in outputs)
    assert any("BBB" in o for o in outputs)


def test_token_usage_accumulates():
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(10, 5)]])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("hi")

    events = _drive(agent, conv)

    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert usage[-1].input_tokens == 10 and usage[-1].output_tokens == 5
    assert agent.total_input_tokens == 10
    assert agent.total_output_tokens == 5


def test_cache_hit_tokens_propagate_to_usage_event():
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(10, 5, 8)]])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("hi")

    events = _drive(agent, conv)

    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert usage[-1].cache_hit_tokens == 8


# --- 环境注入 / Plan 提醒（走对话通道）-------------------------------------

def test_run_injects_environment_at_head():
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(1, 1)]])
    agent = Agent(client, create_default_registry())
    conv = ConversationManager()
    conv.add_user_message("hi")

    _drive(agent, conv)

    assert conv.env_injected is True
    assert "环境信息" in conv.history[0].content  # 头插在 user 之前


# --- ch08 上下文管理集成 ---------------------------------------------------

class _BigParams(BaseModel):
    pass


class BigOutputTool(Tool):
    name = "BigOut"
    description = "返回超大输出"
    params_model = _BigParams
    category = "command"

    async def execute(self, params):
        return ToolResult("Y" * 6000)


class CapturingClient:
    """记录每次 stream 收到的 conversation 历史快照，用于检查 api_conv。"""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.seen = []

    async def stream(self, conversation, tools=None, system=None):
        self.seen.append([(m.role, m.content, m.tool_call_id) for m in conversation.history])
        for event in self._scripts.pop(0):
            yield event


def test_last_input_tokens_recorded(tmp_path):
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(123, 5)]])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("hi")

    _drive(agent, conv)

    assert conv.last_input_tokens == 123


def test_big_tool_result_budgeted_on_next_stream(tmp_path):
    registry = create_default_registry()
    registry.register(BigOutputTool())
    client = CapturingClient([
        [ToolCallComplete("c1", "BigOut", {}), StreamEnd(1, 1)],
        [TextDelta("完成"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, registry, work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("跑个大输出")

    _drive(agent, conv)

    # 第二次 stream 收到的历史里，那条 tool 结果应已成 persisted preview
    second = client.seen[1]
    tool_contents = [content for role, content, _ in second if role == "tool"]
    assert any(c.startswith(ctx.PERSISTED_TAG) for c in tool_contents)
    # 但真实 conversation.history 里仍是原始 6000 字符（不 mutate）
    real_tool = [m.content for m in conv.history if m.role == "tool"]
    assert real_tool and real_tool[0] == "Y" * 6000
    # 落盘文件存在
    assert (agent.session_dir / "c1.txt").exists()


def test_readfile_snapshot_recorded(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    client = MockLLMClient([
        [ToolCallComplete("c1", "ReadFile", {"file_path": str(f)}), StreamEnd(1, 1)],
        [TextDelta("读完了"), StreamEnd(1, 1)],
    ])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("读 a.txt")

    _drive(agent, conv)

    snap = agent.recovery_state.snapshot_files(5)
    assert any(r.path == str(f) and "hello world" in r.content for r in snap)


def test_manual_compact_returns_notification(tmp_path):
    class SummaryClient:
        async def stream(self, conversation, tools=None, system=None):
            yield TextDelta("<summary>这是手动摘要</summary>")
            yield StreamEnd(1, 1)

    agent = Agent(SummaryClient(), create_default_registry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("一些历史")
    conv.add_assistant_message("回应")
    conv.last_input_tokens = 1000

    result = asyncio.run(agent.manual_compact(conv))

    assert isinstance(result, CompactNotification)
    assert "这是手动摘要" in conv.history[0].content


# --- ch09 记忆系统集成 ------------------------------------------------------

class _FakeMemoryManager:
    def __init__(self, memories=""):
        self._memories = memories
        self.extract_calls = 0

    def load(self):
        return self._memories

    async def extract(self, client, conversation):
        self.extract_calls += 1


def test_run_injects_ltm(tmp_path):
    (tmp_path / "AIXCODE.md").write_text("用 4 空格缩进", encoding="utf-8")
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(1, 1)]])
    mm = _FakeMemoryManager(memories="记住：用户喜欢简洁")
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path), memory_manager=mm)
    conv = ConversationManager()
    conv.add_user_message("hi")

    _drive(agent, conv)

    contents = [m.content for m in conv.history]
    assert any("## 项目指令" in c and "4 空格" in c for c in contents)
    assert any("## 自动记忆" in c and "用户喜欢简洁" in c for c in contents)


def test_loop_count_increments(tmp_path):
    client = MockLLMClient([[TextDelta("done"), StreamEnd(1, 1)]])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("hi")

    _drive(agent, conv)

    assert agent._loop_count == 1


def test_extract_memories_calls_manager(tmp_path):
    mm = _FakeMemoryManager()
    agent = Agent(_DummyClient(), create_default_registry(), work_dir=str(tmp_path), memory_manager=mm)
    conv = ConversationManager()
    conv.add_user_message("hi")

    asyncio.run(agent._extract_memories(conv))

    assert mm.extract_calls == 1
    assert agent._extracting is False


def test_no_memory_manager_no_crash(tmp_path):
    client = MockLLMClient([[TextDelta("hi"), StreamEnd(1, 1)]])
    agent = Agent(client, create_default_registry(), work_dir=str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("hi")
    events = _drive(agent, conv)
    assert isinstance(events[-1], LoopComplete)


def test_plan_mode_injects_system_reminder():
    client = MockLLMClient([[TextDelta("这是计划"), StreamEnd(1, 1)]])
    agent = Agent(client, create_default_registry())
    agent.set_permission_mode(PermissionMode.PLAN)
    conv = ConversationManager()
    conv.add_user_message("调研一下")

    _drive(agent, conv)

    assert any("<system-reminder>" in m.content for m in conv.history)
