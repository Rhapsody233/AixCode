"""SkillLoader：三级搜索（项目 > 用户 > 内置）+ 热重载。"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from aixcode.skills.parser import SkillDef, SkillParseError, parse_skill_file

log = logging.getLogger(__name__)

PROJECT_SKILLS_DIR = ".aixcode/skills"
USER_SKILLS_DIR = "~/.aixcode/skills"

_BUILTINS_PACKAGE = "aixcode.skills.builtins"


class SkillLoader:
    """加载并缓存所有 skill；`get` 每次重读源文件实现热重载。"""

    def __init__(self, work_dir: str) -> None:
        self._project_dir = Path(work_dir) / PROJECT_SKILLS_DIR
        self._user_dir = Path(USER_SKILLS_DIR).expanduser()
        self._skills: dict[str, SkillDef] = {}
        self._cache: dict[str, SkillDef] = {}

    # --- 加载 ---

    def load_all(self) -> dict[str, SkillDef]:
        """按 项目 → 用户 → 内置 扫描；首次出现的 name 占位，后续同名跳过。"""
        self._skills = {}
        self._scan_directory(self._project_dir)
        self._scan_directory(self._user_dir)
        self._load_builtins()
        self._cache = dict(self._skills)
        return self._skills

    def reload(self) -> dict[str, SkillDef]:
        return self.load_all()

    def _scan_directory(self, dir_path: Path) -> None:
        if not dir_path.is_dir():
            return
        for entry in sorted(dir_path.iterdir(), key=lambda p: p.name):
            if entry.is_file() and entry.name.endswith(".md"):
                self._try_add(str(entry), is_directory=False)
            elif entry.is_dir():
                skill_md = entry / "SKILL.md"
                if skill_md.is_file():
                    self._try_add(str(skill_md), is_directory=True)

    def _load_builtins(self) -> None:
        try:
            root = importlib.resources.files(_BUILTINS_PACKAGE)
        except (ModuleNotFoundError, FileNotFoundError, TypeError):
            return
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                skill_md = entry / "SKILL.md"
                if skill_md.is_file():
                    self._try_add(str(skill_md), is_directory=True)
            elif entry.name.endswith(".md"):
                self._try_add(str(entry), is_directory=False)

    def _try_add(self, source_path: str, is_directory: bool) -> None:
        try:
            skill = parse_skill_file(source_path, is_directory=is_directory)
        except SkillParseError as e:
            log.warning("Skipping skill at %s: %s", source_path, e)
            return
        if skill.name not in self._skills:
            self._skills[skill.name] = skill

    # --- 查询 ---

    def get(self, name: str) -> SkillDef | None:
        """重读源文件实现热重载；失败回退缓存旧版本并 warning。"""
        entry = self._skills.get(name)
        if entry is None:
            return None
        if entry.source_path is None:
            return entry
        try:
            fresh = parse_skill_file(entry.source_path, is_directory=entry.is_directory)
        except SkillParseError as e:
            log.warning("Hot-reload of skill '%s' failed, using cached: %s", name, e)
            return self._cache.get(name, entry)
        self._skills[name] = fresh
        self._cache[name] = fresh
        return fresh

    def get_catalog(self) -> list[tuple[str, str]]:
        return [(s.name, s.description) for s in self._skills.values()]

    def get_source_label(self, name: str) -> str:
        entry = self._skills.get(name)
        if entry is None or entry.source_path is None:
            return "builtin"
        p = str(Path(entry.source_path).resolve())
        if p.startswith(str(self._project_dir.resolve())):
            return "project"
        if p.startswith(str(self._user_dir.resolve())):
            return "user"
        return "builtin"
