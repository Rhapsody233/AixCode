"""worktree 创建后设置四项：本地配置复制 / git hooks / 软链接 / .worktreeinclude。

A 必做；B/C/D best-effort——单项失败只 log.warning 不抛，保证主路径鲁棒。
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
from pathlib import Path

from aixcode.worktree.changes import GIT_ENV

log = logging.getLogger(__name__)

LOCAL_CONFIG_FILES = ["settings.local.json", ".env"]


def perform_post_creation_setup(
    repo_root: str, worktree_path: str, symlink_directories: list[str] | None
) -> None:
    """依序执行 A/B/C/D 四项创建后设置。"""
    _copy_local_configs(repo_root, worktree_path)
    _setup_git_hooks(repo_root, worktree_path)
    _create_symlinks(symlink_directories or [], worktree_path)
    _copy_ignored_files(repo_root, worktree_path)


def _copy_local_configs(repo_root: str, worktree_path: str) -> None:
    """A：复制本地配置文件（不存在静默跳过）。"""
    for name in LOCAL_CONFIG_FILES:
        src = Path(repo_root) / name
        if not src.exists():
            continue
        try:
            shutil.copy2(src, Path(worktree_path) / name)
        except OSError as e:
            log.warning("复制本地配置 %s 失败：%s", name, e)


def _setup_git_hooks(repo_root: str, worktree_path: str) -> None:
    """B：优先 <repo>/.husky 回退 <repo>/.git/hooks，在 worktree 配 core.hooksPath。"""
    husky = Path(repo_root) / ".husky"
    git_hooks = Path(repo_root) / ".git" / "hooks"
    hooks_dir = husky if husky.is_dir() else (git_hooks if git_hooks.is_dir() else None)
    if hooks_dir is None:
        return
    try:
        subprocess.run(
            ["git", "config", "core.hooksPath", str(hooks_dir)],
            cwd=worktree_path,
            env={**os.environ, **GIT_ENV},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("配置 git hooks 失败：%s", e)


def _create_symlinks(directories: list[str], worktree_path: str) -> None:
    """C：把大型依赖目录软链接进 worktree（best-effort）。"""
    for src in directories:
        src_path = Path(src)
        if not src_path.exists():
            continue
        dst = Path(worktree_path) / src_path.name
        if dst.exists():
            continue
        try:
            os.symlink(src_path, dst)
        except OSError as e:
            log.warning("创建软链接 %s 失败：%s", src, e)


def _copy_ignored_files(repo_root: str, worktree_path: str) -> None:
    """D：按 .worktreeinclude 把父仓 gitignored 但运行需要的文件复制进 worktree。"""
    include_file = Path(repo_root) / ".worktreeinclude"
    if not include_file.is_file():
        return
    patterns = [
        ln.strip()
        for ln in include_file.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not patterns:
        return
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard",
             "--directory"],
            cwd=repo_root,
            env={**os.environ, **GIT_ENV},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("列举 gitignored 文件失败：%s", e)
        return
    for rel in result.stdout.splitlines():
        rel = rel.strip().rstrip("/")
        if not rel or not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            continue
        src = Path(repo_root) / rel
        dst = Path(worktree_path) / rel
        try:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        except OSError as e:
            log.warning("复制 gitignored 文件 %s 失败：%s", rel, e)
            continue
