"""ch08 上下文管理测试。"""

import asyncio

from aixcode.client import LLMError
from aixcode.conversation import ConversationManager, Message
from aixcode.context import manager as m
from aixcode.tools.base import StreamEnd, TextDelta


# --- T1: 常量与 session 助手 -----------------------------------------------

def test_constants():
    assert m.SINGLE_RESULT_CHAR_LIMIT == 5_000
    assert m.AGGREGATE_CHAR_LIMIT == 20_000
    assert m.PREVIEW_CHARS == 2_000
    assert m.KEEP_RECENT_TURNS == 10
    assert m.OLD_RESULT_SNIP_CHARS == 2_000
    assert m.SNIPPED_TAG == "<snipped>"
    assert m.PERSISTED_TAG == "<persisted-output>"
    assert m.SUMMARY_OUTPUT_RESERVE == 20_000
    assert m.AUTO_COMPACT_SAFETY_MARGIN == 13_000
    assert m.MANUAL_COMPACT_SAFETY_MARGIN == 3_000


def test_ensure_session_dir_creates(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    assert session.is_dir()
    assert session.name == "tool-results"


def test_cleanup_tool_results_empties(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    (session / "x.txt").write_text("hi", encoding="utf-8")
    m.cleanup_tool_results(session)
    assert session.is_dir()
    assert list(session.iterdir()) == []


# --- T2: 状态容器 + create/clone -------------------------------------------

def test_create_returns_empty():
    state = m.create_replacement_state()
    assert state.seen_ids == set()
    assert state.replacements == {}


def test_compact_event():
    assert m.CompactEvent(before_tokens=123).before_tokens == 123


def test_replacement_record_defaults():
    rec = m.ContentReplacementRecord(tool_use_id="t1", replacement="x")
    assert rec.kind == "tool-result"


def test_clone_independent():
    src = m.create_replacement_state()
    src.seen_ids.add("a")
    src.replacements["a"] = "preview"
    clone = m.clone_replacement_state(src)
    # 子改不影响父
    clone.seen_ids.add("b")
    clone.replacements["a"] = "changed"
    assert "b" not in src.seen_ids
    assert src.replacements["a"] == "preview"


# --- T3: JSONL records + reconstruct ---------------------------------------

def test_append_and_load_records_roundtrip(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    recs = [
        m.ContentReplacementRecord("t1", "preview-1"),
        m.ContentReplacementRecord("t2", "preview-2"),
    ]
    m.append_replacement_records(session, recs)
    loaded = m.load_replacement_records(session)
    assert [(r.tool_use_id, r.replacement) for r in loaded] == [
        ("t1", "preview-1"),
        ("t2", "preview-2"),
    ]


def test_append_empty_is_noop(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    m.append_replacement_records(session, [])
    assert m.load_replacement_records(session) == []


def test_load_missing_returns_empty(tmp_path):
    assert m.load_replacement_records(tmp_path / "nope") == []


def _tool_msg(tid, content):
    return Message(role="tool", content=content, tool_call_id=tid)


def test_reconstruct_from_records():
    messages = [_tool_msg("t1", "orig"), _tool_msg("t2", "orig2")]
    records = [m.ContentReplacementRecord("t1", "preview-1")]
    state = m.reconstruct_replacement_state(messages, records)
    assert state.seen_ids == {"t1", "t2"}
    assert state.replacements == {"t1": "preview-1"}


def test_reconstruct_with_inherited_parent():
    messages = [_tool_msg("t1", "orig"), _tool_msg("t2", "orig2")]
    state = m.reconstruct_replacement_state(
        messages, [], inherited_replacements={"t2": "inherited", "tX": "ignored"}
    )
    # 只对出现在 messages 里的 candidate 做 gap-fill
    assert state.replacements == {"t2": "inherited"}


# --- T4: persist + preview --------------------------------------------------

def test_persist_tool_result_writes_file(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    path = m.persist_tool_result("tid1", "big content", session)
    from pathlib import Path
    assert Path(path).read_text(encoding="utf-8") == "big content"
    assert Path(path).name == "tid1.txt"


def test_persist_tool_result_idempotent(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    p1 = m.persist_tool_result("tid1", "first", session)
    # 同 id 重跑：已存在则静默跳过，不抛、不覆盖
    p2 = m.persist_tool_result("tid1", "second", session)
    from pathlib import Path
    assert p1 == p2
    assert Path(p1).read_text(encoding="utf-8") == "first"


def test_make_persisted_preview_format():
    content = "X" * 6000
    preview = m.make_persisted_preview(content, "/some/path.txt")
    assert preview.startswith(m.PERSISTED_TAG)
    assert preview.endswith("</persisted-output>")
    assert "/some/path.txt" in preview
    # 预览只含前 PREVIEW_CHARS 字符
    assert preview.count("X") == m.PREVIEW_CHARS


# --- T5: _count_turns / _snip_stale_messages -------------------------------

def _turn(tool_content):
    """一轮：assistant(带 tool_calls) → tool → assistant(收尾，计一轮)。"""
    return [
        Message(role="assistant", content="", tool_calls=[{"id": "x"}]),
        Message(role="tool", content=tool_content, tool_call_id="x"),
        Message(role="assistant", content="done"),
    ]


def test_count_turns():
    history = _turn("a") + _turn("b")
    assert m._count_turns(history) == 2


def test_snip_short_history_unchanged():
    history = _turn("X" * 5000)
    out = m._snip_stale_messages(history)
    assert out == history


def test_snip_old_tool_results():
    history = []
    for i in range(12):
        history += _turn("X" * 5000)
    out = m._snip_stale_messages(history)
    # 第 1 轮（最旧）的 tool result 应被裁剪
    assert out[1].content.startswith(m.SNIPPED_TAG)
    # 最后一轮的 tool result 应保留原文
    assert out[-2].content == "X" * 5000


def test_snip_skips_already_tagged():
    history = []
    for i in range(12):
        history += _turn("X" * 5000)
    history[1] = Message(role="tool", content=m.PERSISTED_TAG + "\n...", tool_call_id="x")
    out = m._snip_stale_messages(history)
    # 已带 PERSISTED 前缀的不再重复裁剪
    assert out[1].content == m.PERSISTED_TAG + "\n..."


# --- T6: Layer 1 apply_tool_result_budget ----------------------------------

def _conv_with_tools(*tool_contents):
    conv = ConversationManager()
    conv.add_user_message("go")
    conv.add_assistant_message("", tool_calls=[{"id": f"t{i}"} for i in range(len(tool_contents))])
    for i, c in enumerate(tool_contents):
        conv.add_tool_result(f"t{i}", c)
    return conv


def test_apply_does_not_mutate_conv(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    state = m.create_replacement_state()
    conv = _conv_with_tools("X" * 6000)
    before = conv.history[-1].content
    api_conv, recs = m.apply_tool_result_budget(conv, session, state)
    # 原 conversation 不变
    assert conv.history[-1].content == before == "X" * 6000
    # api_conv 视图里成 preview
    assert api_conv.history[-1].content.startswith(m.PERSISTED_TAG)


def test_single_over_limit_persisted(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    state = m.create_replacement_state()
    conv = _conv_with_tools("X" * 6000)
    api_conv, recs = m.apply_tool_result_budget(conv, session, state)
    assert len(recs) == 1
    assert "t0" in state.replacements
    # 落盘文件存在
    from pathlib import Path
    assert (Path(session) / "t0.txt").exists()


def test_under_limit_frozen_not_replaced(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    state = m.create_replacement_state()
    conv = _conv_with_tools("small")
    api_conv, recs = m.apply_tool_result_budget(conv, session, state)
    assert recs == []
    assert "t0" in state.seen_ids
    assert "t0" not in state.replacements
    assert api_conv.history[-1].content == "small"


def test_replacement_byte_identical(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    state = m.create_replacement_state()
    conv = _conv_with_tools("X" * 6000)
    api1, _ = m.apply_tool_result_budget(conv, session, state)
    api2, recs2 = m.apply_tool_result_budget(conv, session, state)
    # 第二次复读字节完全相同，且不再产生新 record
    assert api1.history[-1].content == api2.history[-1].content
    assert recs2 == []


def test_frozen_never_replaced(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    state = m.create_replacement_state()
    # 首轮：两条都在单条限内、聚合也在限内 → 都冻结（seen 不 replace）
    conv = _conv_with_tools("a" * 4500, "b" * 4500)
    m.apply_tool_result_budget(conv, session, state)
    assert "t0" in state.seen_ids and "t1" in state.seen_ids
    # 第二轮：t0/t1 已冻结 + 三条新的，聚合 22500 > 20000 触发 Pass 2
    conv2 = _conv_with_tools("a" * 4500, "b" * 4500, "c" * 4500, "d" * 4500, "e" * 4500)
    api, recs = m.apply_tool_result_budget(conv2, session, state)
    # 冻结的 t0/t1 即使聚合超限也绝不被选中替换；只挑 fresh
    assert "t0" not in state.replacements
    assert "t1" not in state.replacements
    assert len(recs) >= 1
    assert all(r.tool_use_id in {"t2", "t3", "t4"} for r in recs)


# --- T7: 阈值计算 -----------------------------------------------------------

def test_compute_compact_threshold():
    assert m.compute_compact_threshold(200_000) == 167_000
    assert m.compute_compact_threshold(200_000, manual=True) == 177_000
    assert m.compute_compact_threshold(128_000) == 95_000


def test_should_auto_compact_boundary():
    threshold = m.compute_compact_threshold(200_000)
    assert m.should_auto_compact(threshold, 200_000) is True
    assert m.should_auto_compact(threshold - 1, 200_000) is False


# --- T8: 摘要 prompt + helpers + 熔断器 ------------------------------------

def test_summary_prompt_structure():
    p = m.SUMMARY_PROMPT
    assert "<analysis>" in p and "<summary>" in p
    # 两次禁止工具调用
    assert p.count("不要调用") >= 2 or p.lower().count("do not call") >= 2 or p.count("禁止") >= 2


def test_extract_summary_with_tags():
    out = "<analysis>草稿</analysis>\n<summary>正式摘要内容</summary>"
    assert m.extract_summary(out) == "正式摘要内容"


def test_extract_summary_without_tags():
    out = "没有标签的纯文本"
    assert m.extract_summary(out) == "没有标签的纯文本"


def test_build_compact_messages():
    msgs = m.build_compact_messages("我的摘要")
    assert len(msgs) == 2
    assert msgs[0].role == "user" and "我的摘要" in msgs[0].content
    assert msgs[1].role == "assistant"


def test_build_compact_messages_with_attachment():
    msgs = m.build_compact_messages("摘要", attachment="## 最近读过的文件\n...")
    assert "---" in msgs[0].content
    assert "最近读过的文件" in msgs[0].content


def test_circuit_breaker():
    b = m.CompactCircuitBreaker(max_failures=3)
    assert b.is_open() is False
    b.record_failure()
    b.record_failure()
    assert b.is_open() is False
    b.record_failure()
    assert b.is_open() is True
    b.record_success()
    assert b.is_open() is False


# --- T10: RecoveryState + build_recovery_attachment ------------------------

_SCHEMAS = [
    {"type": "function", "function": {"name": "ReadFile", "description": "读文件\n第二行"}},
]


def test_recovery_empty_returns_blank():
    state = m.RecoveryState()
    assert m.build_recovery_attachment(state, []) == ""


def test_recovery_emits_sections():
    state = m.RecoveryState()
    state.record_file_read("/proj/a.py", "print('hi')")
    out = m.build_recovery_attachment(state, _SCHEMAS)
    assert "## 最近读过的文件" in out
    assert "### /proj/a.py" in out
    assert "print('hi')" in out
    assert "## 可用工具" in out
    assert "ReadFile — 读文件" in out  # 只取描述首行
    assert "## 提示" in out


def test_recovery_record_empty_path_ignored():
    state = m.RecoveryState()
    state.record_file_read("", "x")
    assert state.snapshot_files(5) == []


def test_recovery_file_limit_and_order():
    state = m.RecoveryState()
    for i in range(6):
        state.record_file_read(f"/f{i}.py", f"content{i}")
    snap = state.snapshot_files(m.RECOVERY_FILE_LIMIT)
    assert len(snap) == 5
    # 最近读的在最前
    assert snap[0].path == "/f5.py"
    assert "/f0.py" not in [r.path for r in snap]


def test_recovery_truncates_per_file():
    state = m.RecoveryState()
    big = "Z" * (m.RECOVERY_TOKENS_PER_FILE * 4)  # 远超单文件 token 预算
    state.record_file_read("/big.py", big)
    out = m.build_recovery_attachment(state, [])
    assert "… (内容已截断)" in out


# --- T9: Layer 2 auto_compact ----------------------------------------------

class _SummaryClient:
    def __init__(self, text="<summary>压缩摘要</summary>", raises=None):
        self.text = text
        self.raises = raises
        self.calls = 0

    async def stream(self, conversation, tools=None, system=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        yield TextDelta(self.text)
        yield StreamEnd(1, 1)


def _long_conv(tokens):
    conv = ConversationManager()
    for i in range(6):
        conv.add_user_message(f"q{i}")
        conv.add_assistant_message(f"a{i}")
    conv.last_input_tokens = tokens
    return conv


def test_auto_compact_below_threshold_returns_none(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(100)
    client = _SummaryClient()
    res = asyncio.run(m.auto_compact(conv, client, 200_000, session))
    assert res is None
    assert client.calls == 0


def test_auto_compact_summarizes(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(170_000)  # > 167_000 阈值
    client = _SummaryClient("<analysis>x</analysis><summary>这是压缩摘要</summary>")
    res = asyncio.run(m.auto_compact(conv, client, 200_000, session))
    assert isinstance(res, m.CompactEvent)
    assert res.before_tokens == 170_000
    assert len(conv.history) == 2
    assert "这是压缩摘要" in conv.history[0].content


def test_auto_compact_breaker_open(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(170_000)
    breaker = m.CompactCircuitBreaker(max_failures=3)
    for _ in range(3):
        breaker.record_failure()
    client = _SummaryClient()
    res = asyncio.run(m.auto_compact(conv, client, 200_000, session, breaker=breaker))
    assert isinstance(res, str)
    assert client.calls == 0


def test_auto_compact_manual_low_tokens(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(100)
    client = _SummaryClient("<summary>手动摘要</summary>")
    res = asyncio.run(m.auto_compact(conv, client, 200_000, session, manual=True))
    assert isinstance(res, m.CompactEvent)
    assert "手动摘要" in conv.history[0].content


def test_auto_compact_ptl_retry_exhausts(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(170_000)
    breaker = m.CompactCircuitBreaker(max_failures=3)
    client = _SummaryClient(raises=LLMError("prompt is too long, 65536 tokens"))
    res = asyncio.run(m.auto_compact(conv, client, 200_000, session, breaker=breaker))
    assert isinstance(res, str)
    assert breaker.consecutive_failures == 1


def test_auto_compact_includes_recovery(tmp_path):
    session = m.ensure_session_dir(str(tmp_path))
    conv = _long_conv(170_000)
    recovery = m.RecoveryState()
    recovery.record_file_read("/proj/x.py", "print(1)")
    client = _SummaryClient("<summary>摘要</summary>")
    asyncio.run(m.auto_compact(conv, client, 200_000, session, recovery=recovery))
    assert "## 最近读过的文件" in conv.history[0].content
