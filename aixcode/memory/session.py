"""会话存档：消息 ↔ jsonl 记录互转、meta 索引、SessionManager 生命周期。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from aixcode.conversation import Message

SESSIONS_DIR = ".aixcode/sessions"
TIME_GAP_THRESHOLD = timedelta(hours=24)
DEFAULT_MAX_AGE_DAYS = 30
TITLE_MAX_LENGTH = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecordType(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    COMPRESSION = "compression"


_ROLE_TO_TYPE = {
    "user": RecordType.USER,
    "assistant": RecordType.ASSISTANT,
    "tool": RecordType.TOOL_RESULT,
}


@dataclass
class SessionRecord:
    """一行 jsonl 记录。"""

    type: RecordType
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_call_id: str | None = None
    tool_calls: list | None = None
    is_error: bool = False

    def to_jsonl(self) -> str:
        obj: dict = {
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.tool_call_id is not None:
            obj["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            obj["tool_calls"] = self.tool_calls
        if self.type == RecordType.TOOL_RESULT and self.is_error:
            obj["is_error"] = True
        return json.dumps(obj, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> SessionRecord | None:
        try:
            obj = json.loads(line)
            rtype = RecordType(obj["type"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None
        return cls(
            type=rtype,
            content=obj.get("content", ""),
            timestamp=obj.get("timestamp", 0.0),
            tool_call_id=obj.get("tool_call_id"),
            tool_calls=obj.get("tool_calls"),
            is_error=obj.get("is_error", False),
        )

    @classmethod
    def from_message(cls, message: Message) -> SessionRecord:
        rtype = _ROLE_TO_TYPE.get(message.role, RecordType.USER)
        return cls(
            type=rtype,
            content=message.content,
            tool_call_id=message.tool_call_id,
            tool_calls=message.tool_calls,
        )


def records_to_messages(records: list[SessionRecord]) -> list[Message]:
    """把 jsonl 记录序列还原成 Message：system 跳过，compression 渲染成 [摘要] user。"""
    messages: list[Message] = []
    for r in records:
        if r.type == RecordType.SYSTEM:
            continue
        if r.type == RecordType.COMPRESSION:
            messages.append(Message(role="user", content=f"[摘要]\n{r.content}"))
        elif r.type == RecordType.TOOL_RESULT:
            messages.append(
                Message(role="tool", content=r.content, tool_call_id=r.tool_call_id)
            )
        elif r.type == RecordType.ASSISTANT:
            messages.append(
                Message(role="assistant", content=r.content, tool_calls=r.tool_calls)
            )
        else:
            messages.append(Message(role="user", content=r.content))
    return messages


def validate_message_chain(records: list[SessionRecord]) -> int:
    """返回 tool_call ↔ tool_result 链路完整的最大前缀长度（用于 resume 截断）。"""
    pending: set[str] = set()
    complete_len = 0
    for i, r in enumerate(records):
        if r.type == RecordType.ASSISTANT and r.tool_calls:
            for call in r.tool_calls:
                cid = call.get("id") if isinstance(call, dict) else None
                if cid:
                    pending.add(cid)
        elif r.type == RecordType.TOOL_RESULT and r.tool_call_id:
            pending.discard(r.tool_call_id)
        if not pending:
            complete_len = i + 1
    return complete_len


# --- meta / session 句柄 ----------------------------------------------------

@dataclass
class SessionMeta:
    id: str
    title: str = ""
    summary: str = ""
    message_count: int = 0
    total_tokens: int = 0
    created_at: datetime = field(default_factory=_now)
    last_active: datetime = field(default_factory=_now)

    def save(self, path) -> None:
        obj = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
        }
        Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path) -> SessionMeta | None:
        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(
                id=obj["id"],
                title=obj.get("title", ""),
                summary=obj.get("summary", ""),
                message_count=obj.get("message_count", 0),
                total_tokens=obj.get("total_tokens", 0),
                created_at=datetime.fromisoformat(obj["created_at"]),
                last_active=datetime.fromisoformat(obj["last_active"]),
            )
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None


@dataclass
class ResumeResult:
    session: "Session"
    messages: list[Message]
    last_active: datetime


class Session:
    """活跃会话句柄：持 jsonl 文件句柄与 meta，append 即写盘。"""

    def __init__(self, session_id: str, file, meta: SessionMeta, sessions_dir) -> None:
        self.id = session_id
        self._file = file
        self.meta = meta
        self.sessions_dir = Path(sessions_dir)

    def _meta_path(self):
        return self.sessions_dir / f"{self.id}.meta"

    def append(self, message: Message) -> None:
        record = SessionRecord.from_message(message)
        self._file.write(record.to_jsonl() + "\n")
        self._file.flush()
        self.meta.message_count += 1
        self.meta.last_active = _now()
        if not self.meta.title and message.role == "user":
            self.meta.title = message.content[:TITLE_MAX_LENGTH]
        self.meta.save(self._meta_path())

    def close(self) -> None:
        if self._file is not None and not self._file.closed:
            self._file.flush()
            self._file.close()


# --- SessionManager ---------------------------------------------------------

import random  # noqa: E402
import string  # noqa: E402


def _generate_session_id() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"


class SessionManager:
    """会话目录管理：create / list / resume / delete / cleanup。"""

    def __init__(self, work_dir: str) -> None:
        self._dir = Path(work_dir) / SESSIONS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _jsonl_path(self, sid: str):
        return self._dir / f"{sid}.jsonl"

    def _meta_path(self, sid: str):
        return self._dir / f"{sid}.meta"

    def create(self) -> Session:
        sid = _generate_session_id()
        meta = SessionMeta(id=sid)
        meta.save(self._meta_path(sid))
        f = open(self._jsonl_path(sid), "a", encoding="utf-8")
        return Session(sid, f, meta, self._dir)

    def list(self) -> list[SessionMeta]:
        metas = [
            m
            for p in self._dir.glob("*.meta")
            if (m := SessionMeta.load(p)) is not None
        ]
        metas.sort(key=lambda m: m.last_active, reverse=True)
        return metas

    def resume(self, session_id: str) -> ResumeResult | None:
        jsonl = self._jsonl_path(session_id)
        if not jsonl.exists():
            return None
        records: list[SessionRecord] = []
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = SessionRecord.from_jsonl(line)
            if rec is not None:
                records.append(rec)
        valid_len = validate_message_chain(records)
        messages = records_to_messages(records[:valid_len])
        meta = SessionMeta.load(self._meta_path(session_id)) or SessionMeta(id=session_id)
        f = open(jsonl, "a", encoding="utf-8")
        session = Session(session_id, f, meta, self._dir)
        return ResumeResult(session, messages, meta.last_active)

    def delete(self, session_id: str) -> bool:
        removed = False
        for path in (self._jsonl_path(session_id), self._meta_path(session_id)):
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def cleanup(self, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
        cutoff = _now() - timedelta(days=max_age_days)
        count = 0
        for meta in self.list():
            if meta.last_active < cutoff:
                if self.delete(meta.id):
                    count += 1
        return count


def build_time_gap_message(last_active: datetime) -> Message | None:
    """距上次活跃 ≥24h 时返回一条断会话时长提示 user 消息；否则 None。"""
    gap = _now() - last_active
    if gap < TIME_GAP_THRESHOLD:
        return None
    hours = int(gap.total_seconds() // 3600)
    span = f"{hours // 24} 天" if hours >= 48 else f"{hours} 小时"
    return Message(
        role="user",
        content=(
            f"[系统提示] 距离上次会话已过去 {span}。"
            "代码可能有变更，建议在操作前重新读取相关文件。"
        ),
    )
