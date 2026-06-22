"""队员对话落盘：把扁平 Message 列表序列化为 JSON，供事后回看（不支持 resume）。"""

from __future__ import annotations

import json
from pathlib import Path

from aixcode.conversation import ConversationManager, Message
from aixcode.teams.models import resolve_team_dir


def _serialize_message(m: Message) -> dict:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": m.tool_calls,
        "tool_call_id": m.tool_call_id,
    }


def _deserialize_message(d: dict) -> Message:
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=d.get("tool_calls"),
        tool_call_id=d.get("tool_call_id"),
    )


def _transcript_path(team_name: str, agent_id: str) -> Path:
    return resolve_team_dir(team_name) / "transcripts" / f"{agent_id}.json"


def save_transcript(team_name: str, agent_id: str, conv: ConversationManager) -> None:
    """把 conv.history 序列化落 ~/.aixcode/teams/<team>/transcripts/<agent_id>.json。"""
    path = _transcript_path(team_name, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [_serialize_message(m) for m in conv.history]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_transcript(team_name: str, agent_id: str) -> ConversationManager | None:
    """反序列化回填新 ConversationManager；置注入标记防重复注入；缺文件返 None。"""
    path = _transcript_path(team_name, agent_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    conv = ConversationManager()
    conv.history = [_deserialize_message(d) for d in data]
    conv.env_injected = True
    conv.ltm_injected = True
    return conv
