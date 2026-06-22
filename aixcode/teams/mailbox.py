"""邮箱：单文件单消息模型，跨进程写入无需文件锁，consume 按时间序 FIFO。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class MailboxMessage:
    """一条邮箱消息。

    message_type 三档：text | shutdown_request | shutdown_response。
    """

    id: str
    from_agent: str
    to_agent: str
    content: str
    summary: str = ""
    message_type: str = "text"
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


def create_message(
    from_agent: str,
    to_agent: str,
    content: str,
    summary: str = "",
    message_type: str = "text",
    metadata: dict | None = None,
) -> MailboxMessage:
    """统一构造器：自动填 id 与 timestamp。"""
    return MailboxMessage(
        id=uuid.uuid4().hex[:12],
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        summary=summary,
        message_type=message_type,
        timestamp=time.time(),
        metadata=metadata or {},
    )


class Mailbox:
    """基于 <base_dir>/<agent_id>/<timestamp>_<id>.json 的单文件单消息邮箱。"""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    def _agent_dir(self, agent_id: str) -> Path:
        return self.base_dir / agent_id

    def write(self, agent_id: str, msg: MailboxMessage) -> None:
        """把一条消息落到收件人目录下的独立文件。"""
        d = self._agent_dir(agent_id)
        d.mkdir(parents=True, exist_ok=True)
        fname = f"{msg.timestamp:.6f}_{msg.id}.json"
        (d / fname).write_text(
            json.dumps(asdict(msg), ensure_ascii=False), encoding="utf-8"
        )

    def _read_files(self, agent_id: str) -> list[Path]:
        d = self._agent_dir(agent_id)
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir() if p.suffix == ".json")

    def read(self, agent_id: str) -> list[MailboxMessage]:
        """只读不删，按文件名（时间戳前缀）时间序返回。"""
        out: list[MailboxMessage] = []
        for f in self._read_files(agent_id):
            out.append(MailboxMessage(**json.loads(f.read_text(encoding="utf-8"))))
        return out

    def consume(self, agent_id: str) -> list[MailboxMessage]:
        """读完逐个 unlink 保证 FIFO 且不重复消费。"""
        out: list[MailboxMessage] = []
        for f in self._read_files(agent_id):
            out.append(MailboxMessage(**json.loads(f.read_text(encoding="utf-8"))))
            f.unlink()
        return out

    def broadcast(
        self, agent_ids: list[str], msg: MailboxMessage, exclude: str | None = None
    ) -> None:
        """按列表逐个 write，排除 exclude。"""
        for aid in agent_ids:
            if aid == exclude:
                continue
            self.write(aid, msg)

    def cleanup(self, agent_id: str) -> None:
        """清空某 agent 的收件箱目录。"""
        d = self._agent_dir(agent_id)
        if d.is_dir():
            for f in d.iterdir():
                f.unlink()
            d.rmdir()

    def cleanup_all(self) -> None:
        """清空整个邮箱根目录。"""
        if not self.base_dir.is_dir():
            return
        for sub in self.base_dir.iterdir():
            if sub.is_dir():
                for f in sub.iterdir():
                    f.unlink()
                sub.rmdir()
