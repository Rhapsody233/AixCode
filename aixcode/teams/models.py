"""团队核心模型：BackendType / TeammateInfo / AgentTeam + 团队目录解析。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class BackendType(str, Enum):
    """队员运行后端三档。"""

    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    """一个队员的元信息。

    is_active 三值语义：None 或 True 表示活跃，False 表示空闲。
    """

    name: str
    agent_id: str
    agent_type: str = ""
    model: str = ""
    worktree_path: str = ""
    backend_type: str = ""
    is_active: bool | None = None


@dataclass
class AgentTeam:
    """长期协作团队聚合：名册 + 负责人 + 持久化位置。"""

    name: str
    lead_agent_id: str
    members: list[TeammateInfo] = field(default_factory=list)
    config_path: str = ""
    description: str = ""

    def get_member(self, name_or_id: str) -> TeammateInfo | None:
        """按 name 或 agent_id 双向查找。"""
        for m in self.members:
            if m.name == name_or_id or m.agent_id == name_or_id:
                return m
        return None

    def add_member(self, info: TeammateInfo) -> None:
        self.members.append(info)

    def remove_member(self, name_or_id: str) -> None:
        """从名册移除（不留墓碑）。"""
        m = self.get_member(name_or_id)
        if m is not None:
            self.members.remove(m)

    def set_member_active(self, name_or_id: str, is_active: bool | None) -> None:
        m = self.get_member(name_or_id)
        if m is not None:
            m.is_active = is_active

    def active_members(self) -> list[TeammateInfo]:
        """活跃成员：is_active is not False（None 与 True 都算活跃）。"""
        return [m for m in self.members if m.is_active is not False]

    def all_idle(self) -> bool:
        """是否全员空闲（is_active is False）。"""
        return all(m.is_active is False for m in self.members)

    # --- 序列化 ---

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lead_agent_id": self.lead_agent_id,
            "members": [asdict(m) for m in self.members],
            "config_path": self.config_path,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AgentTeam:
        members = [TeammateInfo(**m) for m in d.get("members", [])]
        return cls(
            name=d["name"],
            lead_agent_id=d.get("lead_agent_id", ""),
            members=members,
            config_path=d.get("config_path", ""),
            description=d.get("description", ""),
        )

    def save(self) -> None:
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str) -> AgentTeam:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


# --- 团队目录解析 -----------------------------------------------------------

def _sanitize_name(name: str) -> str:
    """把任意名字规整为文件系统安全的 slug。"""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "team"


def _teams_root() -> Path:
    return Path.home() / ".aixcode" / "teams"


def resolve_team_dir(name: str) -> Path:
    """团队目录：~/.aixcode/teams/<slug>/。"""
    return _teams_root() / _sanitize_name(name)


def unique_team_name(name: str) -> str:
    """同名冲突自动加 -2/-3/... 后缀，返回唯一 slug。"""
    base = _sanitize_name(name)
    root = _teams_root()
    candidate = base
    i = 2
    while (root / candidate).exists():
        candidate = f"{base}-{i}"
        i += 1
    return candidate
