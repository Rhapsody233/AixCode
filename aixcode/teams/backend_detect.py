"""后端探测：按环境优先级自动选 tmux / iTerm2 / in-process，失败抛错不静默回退。"""

from __future__ import annotations

import os
import shutil

from aixcode.teams.models import BackendType


class BackendDetectionError(Exception):
    """无法确定可用后端（且未显式选 in-process）。"""


def _in_tmux_session() -> bool:
    return bool(os.environ.get("TMUX"))


def _in_iterm2() -> bool:
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def _it2_available() -> bool:
    return shutil.which("it2") is not None


def _tmux_installed() -> bool:
    return shutil.which("tmux") is not None


def detect_backend(teammate_mode: str, is_interactive: bool) -> BackendType:
    """优先级：显式 in-process / 非交互 → TMUX env → iTerm2+it2 → tmux 可执行 → 抛错。"""
    if teammate_mode == "in-process" or not is_interactive:
        return BackendType.IN_PROCESS
    if _in_tmux_session():
        return BackendType.TMUX
    if _in_iterm2() and _it2_available():
        return BackendType.ITERM2
    if _tmux_installed():
        return BackendType.TMUX
    raise BackendDetectionError(
        "无法确定团队队员的运行后端。请任选其一：\n"
        "  - 安装 tmux（macOS: brew install tmux）后在 tmux 会话内运行；\n"
        "  - 安装 iTerm2 及其 it2 CLI；\n"
        '  - 或在 config.yaml 设 teammate_mode: "in-process" 走同进程后端。'
    )
