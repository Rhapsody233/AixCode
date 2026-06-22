"""ch09 记忆系统测试。"""

from pathlib import Path

import pytest

from aixcode.memory import instructions as instr


@pytest.fixture
def clean_home(tmp_path, monkeypatch):
    """把 ~ 指向一个干净的临时目录，隔离用户级 AIXCODE.md / memories.md。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


# --- T1: process_includes --------------------------------------------------

def test_no_includes(tmp_path):
    out = instr.process_includes("hello world", tmp_path, tmp_path)
    assert out == "hello world"


def test_basic_include(tmp_path):
    (tmp_path / "sub.md").write_text("included content", encoding="utf-8")
    out = instr.process_includes("@include sub.md", tmp_path, tmp_path)
    assert "included content" in out


def test_recursive_include(tmp_path):
    (tmp_path / "a.md").write_text("@include b.md", encoding="utf-8")
    (tmp_path / "b.md").write_text("deep", encoding="utf-8")
    out = instr.process_includes("@include a.md", tmp_path, tmp_path)
    assert "deep" in out


def test_depth_limit(tmp_path):
    # 自引用：靠 MAX_INCLUDE_DEPTH 兜底不无限递归
    (tmp_path / "loop.md").write_text("@include loop.md", encoding="utf-8")
    out = instr.process_includes("@include loop.md", tmp_path, tmp_path)
    assert "@include loop.md" in out  # 到顶后原样保留


def test_path_outside_project_blocked(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    out = instr.process_includes("@include ../secret.md", project, project)
    assert "blocked: path outside project" in out


def test_file_not_found(tmp_path):
    out = instr.process_includes("@include nope.md", tmp_path, tmp_path)
    assert "skipped: file not found" in out


# --- T2: load_instructions -------------------------------------------------

def test_load_single_layer(tmp_path, clean_home):
    (tmp_path / "AIXCODE.md").write_text("项目根指令", encoding="utf-8")
    assert instr.load_instructions(str(tmp_path)) == "项目根指令"


def test_load_multi_layer_priority(tmp_path, clean_home):
    (tmp_path / "AIXCODE.md").write_text("根层", encoding="utf-8")
    (tmp_path / ".aixcode").mkdir()
    (tmp_path / ".aixcode" / "AIXCODE.md").write_text("项目层", encoding="utf-8")
    out = instr.load_instructions(str(tmp_path))
    # 根层在前（高优先级），\n---\n 分隔
    assert out == "根层\n---\n项目层"


def test_load_no_files_returns_empty(tmp_path, clean_home):
    assert instr.load_instructions(str(tmp_path)) == ""


# --- T3: SessionRecord -----------------------------------------------------

from aixcode.conversation import Message  # noqa: E402
from aixcode.memory import session as sess  # noqa: E402


def test_record_types():
    assert {t.value for t in sess.RecordType} == {
        "system", "user", "assistant", "tool_result", "compression"
    }


def test_user_record_roundtrip():
    rec = sess.SessionRecord.from_message(Message(role="user", content="hi"))
    line = rec.to_jsonl()
    back = sess.SessionRecord.from_jsonl(line)
    assert back.type == sess.RecordType.USER
    assert back.content == "hi"


def test_assistant_record_with_tool_calls():
    tc = [{"id": "c1", "type": "function", "function": {"name": "X", "arguments": "{}"}}]
    rec = sess.SessionRecord.from_message(
        Message(role="assistant", content="思考", tool_calls=tc)
    )
    back = sess.SessionRecord.from_jsonl(rec.to_jsonl())
    assert back.type == sess.RecordType.ASSISTANT
    assert back.tool_calls == tc


def test_tool_result_record():
    rec = sess.SessionRecord.from_message(
        Message(role="tool", content="结果", tool_call_id="c1")
    )
    back = sess.SessionRecord.from_jsonl(rec.to_jsonl())
    assert back.type == sess.RecordType.TOOL_RESULT
    assert back.tool_call_id == "c1"
    assert back.content == "结果"


def test_from_jsonl_malformed_returns_none():
    assert sess.SessionRecord.from_jsonl("{not json") is None
    assert sess.SessionRecord.from_jsonl('{"type": "bogus", "content": "x"}') is None


# --- T4: records_to_messages + validate_message_chain ----------------------

def _records(*messages):
    return [sess.SessionRecord.from_message(m) for m in messages]


def test_records_to_messages_roundtrip():
    tc = [{"id": "c1", "type": "function", "function": {"name": "X", "arguments": "{}"}}]
    msgs = [
        Message(role="user", content="读文件"),
        Message(role="assistant", content="", tool_calls=tc),
        Message(role="tool", content="文件内容", tool_call_id="c1"),
        Message(role="assistant", content="读完了"),
    ]
    back = sess.records_to_messages(_records(*msgs))
    assert [m.role for m in back] == ["user", "assistant", "tool", "assistant"]
    assert back[1].tool_calls == tc
    assert back[2].tool_call_id == "c1"


def test_records_to_messages_skips_system_renders_compression():
    recs = [
        sess.SessionRecord(sess.RecordType.SYSTEM, "系统提示"),
        sess.SessionRecord(sess.RecordType.COMPRESSION, "摘要内容"),
    ]
    msgs = sess.records_to_messages(recs)
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert msgs[0].content.startswith("[摘要]")
    assert "摘要内容" in msgs[0].content


def test_validate_complete_chain():
    tc = [{"id": "c1", "type": "function", "function": {"name": "X", "arguments": "{}"}}]
    recs = _records(
        Message(role="user", content="q"),
        Message(role="assistant", content="", tool_calls=tc),
        Message(role="tool", content="r", tool_call_id="c1"),
        Message(role="assistant", content="done"),
    )
    assert sess.validate_message_chain(recs) == 4


def test_validate_truncates_incomplete_chain():
    tc = [{"id": "c1", "type": "function", "function": {"name": "X", "arguments": "{}"}}]
    recs = _records(
        Message(role="user", content="q"),
        Message(role="assistant", content="", tool_calls=tc),  # 缺 tool_result
    )
    # 完整前缀只到 user（index 1），assistant 带未配对 tool_call 不算完整
    assert sess.validate_message_chain(recs) == 1


def test_validate_empty():
    assert sess.validate_message_chain([]) == 0


# --- T5: SessionMeta + Session ---------------------------------------------

def test_session_meta_save_load(tmp_path):
    meta = sess.SessionMeta(id="s1", title="标题")
    path = tmp_path / "s1.meta"
    meta.save(path)
    loaded = sess.SessionMeta.load(path)
    assert loaded.id == "s1" and loaded.title == "标题"


def test_session_meta_load_invalid_returns_none(tmp_path):
    bad = tmp_path / "bad.meta"
    bad.write_text("{not json", encoding="utf-8")
    assert sess.SessionMeta.load(bad) is None


def _open_session(tmp_path, sid="s1"):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    meta = sess.SessionMeta(id=sid)
    f = open(sessions / f"{sid}.jsonl", "a", encoding="utf-8")
    return sess.Session(sid, f, meta, sessions)


def test_session_append_writes_jsonl_and_meta(tmp_path):
    s = _open_session(tmp_path)
    s.append(Message(role="user", content="第一条消息"))
    s.append(Message(role="assistant", content="回应"))
    s.close()
    lines = (tmp_path / "sessions" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert s.meta.message_count == 2


def test_session_title_from_first_user(tmp_path):
    s = _open_session(tmp_path)
    long = "标" * 80
    s.append(Message(role="user", content=long))
    s.close()
    assert s.meta.title == long[: sess.TITLE_MAX_LENGTH]


# --- T6: SessionManager ----------------------------------------------------

import re  # noqa: E402


def test_generate_session_id_format():
    sid = sess._generate_session_id()
    assert re.match(r"^session_\d{8}_\d{6}_[a-z0-9]{4}$", sid)


def test_manager_create_and_list(tmp_path):
    mgr = sess.SessionManager(str(tmp_path))
    s = mgr.create()
    s.append(Message(role="user", content="hi"))
    s.close()
    listed = mgr.list()
    assert len(listed) == 1
    assert listed[0].id == s.id


def test_manager_delete(tmp_path):
    mgr = sess.SessionManager(str(tmp_path))
    s = mgr.create()
    s.close()
    assert mgr.delete(s.id) is True
    assert mgr.list() == []


def test_manager_resume_restores_messages(tmp_path):
    mgr = sess.SessionManager(str(tmp_path))
    s = mgr.create()
    s.append(Message(role="user", content="问题"))
    s.append(Message(role="assistant", content="回答"))
    s.close()

    result = sess.SessionManager(str(tmp_path)).resume(s.id)
    assert result is not None
    assert [m.role for m in result.messages] == ["user", "assistant"]
    assert result.messages[0].content == "问题"
    result.session.close()


def test_manager_resume_nonexistent(tmp_path):
    assert sess.SessionManager(str(tmp_path)).resume("nope") is None


def test_manager_resume_truncates_incomplete_chain(tmp_path):
    mgr = sess.SessionManager(str(tmp_path))
    s = mgr.create()
    tc = [{"id": "c1", "type": "function", "function": {"name": "X", "arguments": "{}"}}]
    s.append(Message(role="user", content="q"))
    s.append(Message(role="assistant", content="", tool_calls=tc))  # 缺 tool_result
    s.close()

    result = sess.SessionManager(str(tmp_path)).resume(s.id)
    # 未配对的 assistant(tool_calls) 被截断，只剩 user
    assert [m.role for m in result.messages] == ["user"]
    result.session.close()


def test_manager_cleanup_removes_old(tmp_path):
    from datetime import timedelta
    mgr = sess.SessionManager(str(tmp_path))
    s = mgr.create()
    s.close()
    # 把 last_active 改到 40 天前
    s.meta.last_active = sess._now() - timedelta(days=40)
    s.meta.save(tmp_path / sess.SESSIONS_DIR.split("/")[-1] if False else s._meta_path())
    removed = mgr.cleanup(max_age_days=30)
    assert removed == 1
    assert mgr.list() == []


# --- T7: build_time_gap_message --------------------------------------------

def test_time_gap_no_gap_returns_none():
    from datetime import timedelta
    recent = sess._now() - timedelta(hours=2)
    assert sess.build_time_gap_message(recent) is None


def test_time_gap_hours():
    from datetime import timedelta
    last = sess._now() - timedelta(hours=25)
    msg = sess.build_time_gap_message(last)
    assert msg is not None
    assert "25 小时" in msg.content
    assert "代码可能有变更" in msg.content


def test_time_gap_days():
    from datetime import timedelta
    last = sess._now() - timedelta(days=3)
    msg = sess.build_time_gap_message(last)
    assert "3 天" in msg.content


# --- T8: MemoryManager 双路径 + load ---------------------------------------

from aixcode.memory.auto_memory import MemoryManager  # noqa: E402


def test_memory_paths(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    assert mgr.user_path == clean_home / ".aixcode/memories.md"
    assert mgr.project_path == tmp_path / ".aixcode/memories.md"


def test_memory_load_empty(tmp_path, clean_home):
    assert MemoryManager(str(tmp_path)).load() == ""


def test_memory_load_merges(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    mgr.user_path.parent.mkdir(parents=True, exist_ok=True)
    mgr.user_path.write_text("用户级内容", encoding="utf-8")
    mgr.project_path.parent.mkdir(parents=True, exist_ok=True)
    mgr.project_path.write_text("项目级内容", encoding="utf-8")
    out = mgr.load()
    assert "用户级内容" in out and "项目级内容" in out


# --- T9 / T10: extract + write + clear + display ---------------------------

import asyncio  # noqa: E402

from aixcode.conversation import ConversationManager  # noqa: E402
from aixcode.memory import auto_memory as am  # noqa: E402
from aixcode.tools.base import StreamEnd, TextDelta  # noqa: E402


class _MemClient:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    async def stream(self, conversation, tools=None, system=None):
        self.calls += 1
        yield TextDelta(self.text)
        yield StreamEnd(1, 1)


def test_extraction_prompt_has_categories():
    for cat in ("用户偏好", "纠正反馈", "项目知识", "参考资料"):
        assert cat in am.MEMORY_EXTRACTION_PROMPT
    assert "不要调用任何工具" in am.MEMORY_EXTRACTION_PROMPT


def test_write_memories_splits_correctly(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    content = "### 用户偏好\n- 喜欢简洁\n\n### 项目知识\n- 用 pytest\n"
    mgr._write_memories(content)
    assert "喜欢简洁" in mgr.user_path.read_text(encoding="utf-8")
    assert "用 pytest" in mgr.project_path.read_text(encoding="utf-8")
    assert "喜欢简洁" not in mgr.project_path.read_text(encoding="utf-8")


def test_write_memories_filters_placeholders(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    mgr._write_memories("### 用户偏好\n- 暂无\n- ...\n")
    assert not mgr.user_path.exists()


def test_extract_writes_and_advances_cursor(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    conv = ConversationManager()
    conv.add_user_message("我喜欢用 4 空格缩进")
    conv.add_assistant_message("好的")
    client = _MemClient("### 用户偏好\n- 用 4 空格缩进\n\n### 项目知识\n- 这是 Python 项目\n")
    asyncio.run(mgr.extract(client, conv))
    assert "4 空格" in mgr.user_path.read_text(encoding="utf-8")
    assert "Python 项目" in mgr.project_path.read_text(encoding="utf-8")
    assert mgr._last_extraction_msg_count == 2


def test_clear(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    mgr.project_path.parent.mkdir(parents=True, exist_ok=True)
    mgr.project_path.write_text("x", encoding="utf-8")
    mgr.clear()
    assert mgr.project_path.read_text(encoding="utf-8") == ""


def test_get_display_text_empty(tmp_path, clean_home):
    assert MemoryManager(str(tmp_path)).get_display_text() == "当前没有任何自动记忆。"


def test_get_display_text_levels(tmp_path, clean_home):
    mgr = MemoryManager(str(tmp_path))
    mgr.user_path.parent.mkdir(parents=True, exist_ok=True)
    mgr.user_path.write_text("u内容", encoding="utf-8")
    out = mgr.get_display_text()
    assert "[用户级]" in out and "u内容" in out
