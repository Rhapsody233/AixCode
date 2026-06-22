"""Agent 名字注册表：进程内单例，把人类可读 name 映射到 agent_id 供寻址。"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """进程内单例（线程安全 double-checked locking）：name → agent_id。"""

    _instance: AgentNameRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    @classmethod
    def instance(cls) -> AgentNameRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def register(self, name: str, agent_id: str) -> None:
        self._names[name] = agent_id

    def resolve(self, name_or_id: str) -> str | None:
        """先按 name 查，再按 agent_id 反查；命不中返 None。"""
        if name_or_id in self._names:
            return self._names[name_or_id]
        if name_or_id in self._names.values():
            return name_or_id
        return None

    def unregister(self, name: str) -> None:
        self._names.pop(name, None)

    def list_all(self) -> dict[str, str]:
        return dict(self._names)
