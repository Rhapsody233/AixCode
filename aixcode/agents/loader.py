"""AgentLoader：三级搜索（项目 > 用户 > 内置）+ 热重载 + verification flag。"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from aixcode.agents.parser import AgentDef, AgentParseError, parse_agent_file

log = logging.getLogger(__name__)

PROJECT_AGENTS_DIR = ".aixcode/agents"
USER_AGENTS_DIR = "~/.aixcode/agents"

_BUILTINS_PACKAGE = "aixcode.agents.builtins"

# enable_verification=False 时不加载的内置（若提供该内置）
_VERIFICATION_NAME = "verification"


class AgentLoader:
    """加载并缓存所有子 Agent 定义；`get` 每次重读源文件实现热重载。"""

    def __init__(self, work_dir: str, enable_verification: bool = False) -> None:
        self._project_dir = Path(work_dir) / PROJECT_AGENTS_DIR
        self._user_dir = Path(USER_AGENTS_DIR).expanduser()
        self._enable_verification = enable_verification
        self._agents: dict[str, AgentDef] = {}
        self._cache: dict[str, AgentDef] = {}

    # --- 加载 ---

    def load_all(self) -> dict[str, AgentDef]:
        """按 项目 → 用户 → 内置 扫描；首次出现的 name 占位，后续同名跳过。"""
        self._agents = {}
        self._scan_directory(self._project_dir, "project")
        self._scan_directory(self._user_dir, "user")
        self._load_builtins()
        self._cache = dict(self._agents)
        return self._agents

    def reload(self) -> dict[str, AgentDef]:
        return self.load_all()

    def _scan_directory(self, dir_path: Path, source: str) -> None:
        if not dir_path.is_dir():
            return
        for entry in sorted(dir_path.iterdir(), key=lambda p: p.name):
            if entry.is_file() and entry.name.endswith(".md"):
                self._try_add(str(entry), source)

    def _load_builtins(self) -> None:
        try:
            root = importlib.resources.files(_BUILTINS_PACKAGE)
        except (ModuleNotFoundError, FileNotFoundError, TypeError):
            return
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if entry.name.endswith(".md"):
                self._try_add(str(entry), "builtin")

    def _try_add(self, source_path: str, source: str) -> None:
        try:
            agent = parse_agent_file(source_path, source=source)
        except AgentParseError as e:
            log.warning("Skipping agent at %s: %s", source_path, e)
            return
        if agent.agent_type == _VERIFICATION_NAME and not self._enable_verification:
            return
        if agent.agent_type not in self._agents:
            self._agents[agent.agent_type] = agent

    # --- 查询 ---

    def get(self, name: str) -> AgentDef | None:
        """重读源文件实现热重载；失败回退缓存旧版本并 warning。"""
        entry = self._agents.get(name)
        if entry is None:
            return None
        if entry.file_path is None:
            return entry
        try:
            fresh = parse_agent_file(entry.file_path, source=entry.source)
        except AgentParseError as e:
            log.warning("Hot-reload of agent '%s' failed, using cached: %s", name, e)
            return self._cache.get(name, entry)
        self._agents[name] = fresh
        self._cache[name] = fresh
        return fresh

    def list_agents(self) -> list[AgentDef]:
        return list(self._agents.values())

    def get_catalog(self) -> list[tuple[str, str]]:
        return [(a.agent_type, a.when_to_use) for a in self._agents.values()]

    def get_source_label(self, name: str) -> str:
        entry = self._agents.get(name)
        return entry.source if entry is not None else "builtin"
