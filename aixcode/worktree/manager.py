"""WorktreeManager：worktree 创建/进出/清理/恢复的统一入口。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from aixcode.worktree.changes import (
    CleanupResult,
    count_worktree_changes,
    describe_changes,
    has_worktree_changes,
)
from aixcode.worktree.models import Worktree, WorktreeSession
from aixcode.worktree.session import load_worktree_session, save_worktree_session
from aixcode.worktree.setup import perform_post_creation_setup
from aixcode.worktree.slug import flatten_slug, validate_slug

log = logging.getLogger(__name__)

# 关终端密码提示，绝不挂起等输入
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


class WorktreeError(Exception):
    """worktree 操作失败（含变更保护拒绝）。"""


class WorktreeManager:
    """所有 worktree 操作的入口。create 用 asyncio.Lock 串行。"""

    def __init__(
        self,
        repo_root: str,
        file_cache=None,
        symlink_directories: list[str] | None = None,
        worktree_dir: str | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.file_cache = file_cache
        self.symlink_directories = symlink_directories or []
        self._aixcode_dir = str(Path(repo_root) / ".aixcode")
        self.worktree_dir = worktree_dir or str(Path(self._aixcode_dir) / "worktrees")
        self._lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self.current_session = None
        self._cache_clear_callbacks: list = []
        self._work_dir_callbacks: list = []

    # --- 缓存清理 ---

    def add_cache_clear_callback(self, callback) -> None:
        self._cache_clear_callbacks.append(callback)

    def add_work_dir_callback(self, callback) -> None:
        """注册 work_dir 切换回调（enter 切进 worktree、exit 切回原目录时调用）。"""
        self._work_dir_callbacks.append(callback)

    def _notify_work_dir(self, path: str) -> None:
        for cb in self._work_dir_callbacks:
            try:
                cb(path)
            except Exception as e:  # noqa: BLE001
                log.warning("work_dir 切换回调失败：%s", e)

    def _clear_all_caches(self) -> None:
        """清文件缓存 + 跑所有注册回调（切 worktree 时防用旧内容做决策）。"""
        if isinstance(self.file_cache, dict):
            self.file_cache.clear()
        elif self.file_cache is not None and hasattr(self.file_cache, "clear"):
            try:
                self.file_cache.clear()
            except Exception as e:  # noqa: BLE001
                log.warning("清文件缓存失败：%s", e)
        for cb in self._cache_clear_callbacks:
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                log.warning("缓存清理回调失败：%s", e)

    # --- git 子进程安全壳 ---

    def _run_git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo_root,
            env={**os.environ, **GIT_ENV},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def _get_current_branch(self) -> str:
        try:
            r = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            return r.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return ""

    def _get_head_commit(self) -> str:
        try:
            r = self._run_git(["rev-parse", "HEAD"])
            return r.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return ""

    # --- 快速恢复：纯文件系统读 HEAD sha，不跑 git 子进程 ---

    @staticmethod
    def read_worktree_head_sha(path: str) -> str | None:
        """读 worktree 当前 HEAD 的 40 位 sha；任一步失败返 None。"""
        try:
            git_pointer = Path(path) / ".git"
            if git_pointer.is_dir():
                gitdir = git_pointer
            elif git_pointer.is_file():
                content = git_pointer.read_text(encoding="utf-8").strip()
                if not content.startswith("gitdir:"):
                    return None
                gitdir = Path(content.split("gitdir:", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (git_pointer.parent / gitdir).resolve()
            else:
                return None

            commondir_file = gitdir / "commondir"
            if commondir_file.is_file():
                cd = commondir_file.read_text(encoding="utf-8").strip()
                commondir = Path(cd) if Path(cd).is_absolute() else (gitdir / cd).resolve()
            else:
                commondir = gitdir

            head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
            if not head.startswith("ref:"):
                return head or None

            ref = head.split("ref:", 1)[1].strip()
            for base in (gitdir, commondir):
                ref_file = base / ref
                if ref_file.is_file():
                    return ref_file.read_text(encoding="utf-8").strip() or None

            packed = commondir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if not line or line.startswith(("#", "^")):
                        continue
                    sha, _, name = line.partition(" ")
                    if name.strip() == ref:
                        return sha.strip() or None
            return None
        except (OSError, ValueError, IndexError):
            return None

    # --- 路径/分支辅助 ---

    def _paths_for(self, slug: str) -> tuple[str, str]:
        """返回 (worktree 目录路径, 分支名)。"""
        flat = flatten_slug(slug)
        return str(Path(self.worktree_dir) / flat), f"worktree-{flat}"

    # --- 会话级 API ---

    async def create(self, slug: str, base_branch: str = "HEAD") -> Worktree:
        """创建或快速恢复一个 worktree；已存在目录走快速恢复（不重跑创建后设置）。"""
        async with self._lock:
            err = validate_slug(slug)
            if err is not None:
                raise WorktreeError(err)
            if slug in self.active:
                raise WorktreeError(f"worktree '{slug}' 已在使用")
            wt_path, branch = self._paths_for(slug)

            # 快速恢复：目录已存在，纯文件系统读 HEAD，跳过 git 子进程与创建后设置
            sha = self.read_worktree_head_sha(wt_path)
            if sha is not None:
                wt = Worktree(name=slug, path=wt_path, branch=branch,
                              based_on=base_branch, head_commit=sha)
                self.active[slug] = wt
                return wt

            os.makedirs(self.worktree_dir, exist_ok=True)
            result = self._run_git(
                ["worktree", "add", "-B", branch, wt_path, base_branch]
            )
            if result.returncode != 0:
                raise WorktreeError(f"git worktree add 失败：{result.stderr.strip()}")
            head = self._run_git(["rev-parse", "HEAD"], cwd=wt_path).stdout.strip()
            perform_post_creation_setup(
                self.repo_root, wt_path, self.symlink_directories
            )
            wt = Worktree(name=slug, path=wt_path, branch=branch,
                          based_on=base_branch, head_commit=head)
            self.active[slug] = wt
            return wt

    async def enter(self, slug: str) -> WorktreeSession:
        """进入 worktree：记录原始 cwd/分支/HEAD + 切 work_dir + 清缓存 + 持久化。"""
        wt = self.active.get(slug)
        wt_path = wt.path if wt else self._paths_for(slug)[0]
        session = WorktreeSession(
            original_cwd=os.getcwd(),
            worktree_path=wt_path,
            worktree_name=slug,
            original_branch=self._get_current_branch(),
            original_head_commit=self._get_head_commit(),
        )
        self.current_session = session
        save_worktree_session(self._aixcode_dir, session)
        # 先切 work_dir 再清缓存：让 instructions 等按新目录重载
        self._notify_work_dir(wt_path)
        self._clear_all_caches()
        return session

    async def exit(
        self, name: str, action: str, discard_changes: bool = False
    ) -> None:
        """退出 worktree：变更保护 → 清缓存/单例/持久化 → remove 时删 worktree。"""
        wt = self.active.get(name)
        wt_path = wt.path if wt else self._paths_for(name)[0]
        session = self.current_session
        original_cwd = session.original_cwd if session else os.getcwd()
        if action == "remove" and not discard_changes:
            head = wt.head_commit if wt else "HEAD"
            ch = count_worktree_changes(wt_path, head)
            if ch.uncommitted > 0 or ch.new_commits > 0:
                raise WorktreeError(
                    f"worktree '{name}' 有未保存的变更（{describe_changes(ch)}），"
                    f"拒绝删除；如确认丢弃请 discard_changes=True"
                )
        self.current_session = None
        save_worktree_session(self._aixcode_dir, None)
        if action == "remove":
            await self._remove_worktree(name)
        # 切回原目录再清缓存
        self._notify_work_dir(original_cwd)
        self._clear_all_caches()

    async def _remove_worktree(self, name: str) -> None:
        """git worktree remove → 等 lockfile 释放 → 删分支 → 出注册表。"""
        wt_path, branch = self._paths_for(name)
        wt = self.active.get(name)
        if wt:
            wt_path = wt.path
        self._run_git(["worktree", "remove", "--force", wt_path])
        await asyncio.sleep(0.1)  # 等 git lockfile 释放，否则 branch -D 偶发失败
        self._run_git(["branch", "-D", branch])
        self.active.pop(name, None)

    async def auto_cleanup(self, name: str, head_commit: str) -> CleanupResult:
        """子 Agent 完成后：干净则删，脏则保留并返回 path/branch 供 review。"""
        wt = self.active.get(name)
        wt_path, branch = self._paths_for(name)
        if wt:
            wt_path, branch = wt.path, wt.branch
        if has_worktree_changes(wt_path, head_commit):
            return CleanupResult(kept=True, path=wt_path, branch=branch)
        await self._remove_worktree(name)
        return CleanupResult(kept=False)

    def list_worktrees(self) -> list[Worktree]:
        return list(self.active.values())

    def get_current_session(self) -> WorktreeSession | None:
        return self.current_session

    def restore_session(self) -> WorktreeSession | None:
        """启动恢复：读持久化 → 验证 worktree 仍在 → 写回 active；读不到则清脏文件。"""
        session = load_worktree_session(self._aixcode_dir)
        if session is None:
            return None
        sha = self.read_worktree_head_sha(session.worktree_path)
        if sha is None:
            save_worktree_session(self._aixcode_dir, None)
            return None
        _, branch = self._paths_for(session.worktree_name)
        self.active[session.worktree_name] = Worktree(
            name=session.worktree_name,
            path=session.worktree_path,
            branch=branch,
            based_on="HEAD",
            head_commit=sha,
        )
        self.current_session = session
        return session
