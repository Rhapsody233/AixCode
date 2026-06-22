"""iTerm2 后端：经官方 it2 CLI 在新 pane 里拉起队员 CLI 实例。

本机无 iTerm2/it2，真实启动属 Out of Scope；本模块仅移植代码 + mock 单测覆盖。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from aixcode.teams.spawn_tmux import build_cli_command


@dataclass
class ITermPaneInfo:
    """一个 iTerm2 pane（session）标识。"""

    session_id: str


class ITermSpawnError(Exception):
    """iTerm2 pane 创建失败。"""


def _run_it2(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["it2", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


def spawn_iterm2_teammate(
    team_name: str,
    teammate_name: str,
    mailbox_dir: str,
    work_dir: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
) -> ITermPaneInfo:
    """复用 build_cli_command，经 it2 split-pane 创建 pane；失败抛 ITermSpawnError。"""
    cmd = build_cli_command(
        team_name, teammate_name, mailbox_dir, work_dir, prompt, agent_type, model
    )
    wrapped = f"/bin/zsh -c '{cmd}'"
    r = _run_it2(["split-pane", "--command", wrapped])
    if r.returncode != 0:
        raise ITermSpawnError(r.stderr.strip() or "it2 split-pane 失败")
    return ITermPaneInfo(session_id=r.stdout.strip())
