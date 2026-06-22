"""TeamManager：团队注册表 + 多类资源缓存，Lead 进程的"团队服务总线"。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from aixcode.teams.backend_detect import detect_backend as _detect_backend
from aixcode.teams.mailbox import Mailbox, create_message
from aixcode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from aixcode.teams.registry import AgentNameRegistry
from aixcode.teams.shared_task import SharedTaskStore

log = logging.getLogger(__name__)


class TeamError(Exception):
    """团队操作失败（如删除时仍有活跃成员）。"""


class TeamManager:
    """团队的创建/查找/成员注册/删除统一入口；后端探测结果整生命周期缓存。"""

    def __init__(self, worktree_manager=None, trace_manager=None) -> None:
        self.worktree_manager = worktree_manager
        self.trace_manager = trace_manager
        self._teams: dict[str, AgentTeam] = {}
        self._task_stores: dict[str, SharedTaskStore] = {}
        self._mailboxes: dict[str, Mailbox] = {}
        self._inprocess_handles: dict[str, object] = {}
        self._pane_ids: dict[str, str] = {}
        self._teammate_team_map: dict[str, str] = {}
        self._detected_backend: BackendType | None = None

    # --- 后端探测（首次后缓存）---

    def detect_backend(
        self, teammate_mode: str = "", is_interactive: bool = True
    ) -> BackendType:
        if self._detected_backend is None:
            self._detected_backend = _detect_backend(teammate_mode, is_interactive)
        return self._detected_backend

    # --- 创建 / 查找 ---

    def create_team(
        self,
        name: str,
        lead_agent_id: str,
        description: str = "",
        teammate_mode: str = "",
        is_interactive: bool = True,
    ) -> AgentTeam:
        """探测后端 → 唯一名 → mkdir → 落 config/tasks/mailbox → 缓存。"""
        self.detect_backend(teammate_mode, is_interactive)
        final_name = unique_team_name(name)
        team_dir = resolve_team_dir(final_name)
        team_dir.mkdir(parents=True, exist_ok=True)
        config_path = team_dir / "config.json"
        team = AgentTeam(
            name=final_name,
            lead_agent_id=lead_agent_id,
            config_path=str(config_path),
            description=description,
        )
        team.save()
        store = SharedTaskStore(str(team_dir / "tasks.json"))
        store.init_empty()
        (team_dir / "mailbox").mkdir(parents=True, exist_ok=True)
        mailbox = Mailbox(str(team_dir / "mailbox"))
        self._teams[final_name] = team
        self._task_stores[final_name] = store
        self._mailboxes[final_name] = mailbox
        return team

    def get_team(self, team_name: str) -> AgentTeam | None:
        return self._teams.get(team_name)

    def get_task_store(self, team_name: str) -> SharedTaskStore | None:
        return self._task_stores.get(team_name)

    def get_mailbox(self, team_name: str) -> Mailbox | None:
        return self._mailboxes.get(team_name)

    # --- 成员 ---

    def register_member(self, team_name: str, info: TeammateInfo) -> None:
        """加入名册 + 注册 name→agent_id + 写 teammate→team 反查映射。"""
        team = self._teams.get(team_name)
        if team is None:
            return
        team.add_member(info)
        team.save()
        AgentNameRegistry.instance().register(info.name, info.agent_id)
        self._teammate_team_map[info.agent_id] = team_name

    def set_member_idle(self, team_name: str, name: str) -> None:
        """翻 is_active=False 并写一条 idle 通知到 Lead 邮箱。"""
        team = self._teams.get(team_name)
        if team is None:
            return
        member = team.get_member(name)
        if member is None:
            return
        team.set_member_active(name, False)
        team.save()
        mailbox = self._mailboxes.get(team_name)
        if mailbox is not None and team.lead_agent_id:
            msg = create_message(
                member.agent_id,
                team.lead_agent_id,
                f"Teammate '{member.name}' is now idle.",
                summary="teammate idle",
            )
            mailbox.write(team.lead_agent_id, msg)

    def register_inprocess_handle(self, agent_id: str, handle) -> None:
        self._inprocess_handles[agent_id] = handle

    def register_pane_id(self, agent_id: str, pane_id: str) -> None:
        self._pane_ids[agent_id] = pane_id

    def get_pane_id(self, agent_id: str) -> str | None:
        return self._pane_ids.get(agent_id)

    def get_team_for_teammate(self, agent_id: str) -> AgentTeam | None:
        team_name = self._teammate_team_map.get(agent_id)
        return self._teams.get(team_name) if team_name else None

    def on_teammate_completed(self, agent_id: str) -> None:
        """队员协程完成回调：标记其 idle（写 Lead 邮箱）。异常吞掉。"""
        try:
            team_name = self._teammate_team_map.get(agent_id)
            if team_name is None:
                return
            team = self._teams.get(team_name)
            if team is None:
                return
            member = team.get_member(agent_id)
            if member is not None:
                self.set_member_idle(team_name, member.name)
        except Exception as e:  # noqa: BLE001
            log.debug("on_teammate_completed 失败：%s", e)

    # --- 删除 ---

    async def delete_team(self, team_name: str) -> None:
        """先校验全员 idle，再清各资源 + cleanup mailbox + 删目录 + 弹三缓存。"""
        team = self._teams.get(team_name)
        if team is None:
            raise TeamError(f"Team {team_name!r} not found")
        active = [m.name for m in team.members if m.is_active is not False]
        if active:
            raise TeamError(f"Cannot delete team: active members: {', '.join(active)}")

        registry = AgentNameRegistry.instance()
        for member in team.members:
            registry.unregister(member.name)
            handle = self._inprocess_handles.pop(member.agent_id, None)
            if handle is not None:
                try:
                    handle.cancel()
                except Exception as e:  # noqa: BLE001
                    log.debug("cancel handle 失败：%s", e)
            pane_id = self._pane_ids.pop(member.agent_id, None)
            if pane_id is not None:
                self._kill_pane(pane_id)
            await self._cleanup_worktree(team_name, member)
            if self.trace_manager is not None:
                try:
                    self.trace_manager.complete(member.agent_id, "completed")
                except Exception as e:  # noqa: BLE001
                    log.debug("trace cleanup 失败：%s", e)
            self._teammate_team_map.pop(member.agent_id, None)

        mailbox = self._mailboxes.get(team_name)
        if mailbox is not None:
            mailbox.cleanup_all()
        self._remove_dir(Path(team.config_path).parent)
        self._teams.pop(team_name, None)
        self._task_stores.pop(team_name, None)
        self._mailboxes.pop(team_name, None)

    def _kill_pane(self, pane_id: str) -> None:
        from aixcode.teams.spawn_tmux import kill_pane

        kill_pane(pane_id)

    async def _cleanup_worktree(self, team_name: str, member: TeammateInfo) -> None:
        if self.worktree_manager is None:
            return
        slug = f"team-{team_name}/{member.name}"
        try:
            await self.worktree_manager._remove_worktree(slug)
        except Exception as e:  # noqa: BLE001
            log.debug("删除队员 worktree 失败：%s", e)

    @staticmethod
    def _remove_dir(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
