"""tmux 后端：在新 pane 里拉起一个 `python -m aixcode -p` 实例（强进程隔离）。

本机无 Unix 环境，真实启动属 Out of Scope；本模块仅移植代码 + mock 单测覆盖。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class TmuxPaneInfo:
    """一个 tmux pane 标识。"""

    pane_id: str


class TmuxSpawnError(Exception):
    """tmux pane 创建失败。"""


def _run_tmux(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


def build_cli_command(
    team_name: str,
    teammate_name: str,
    mailbox_dir: str,
    work_dir: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
) -> str:
    """拼出带团队环境变量前缀的单次执行 CLI 命令；prompt 内单引号转义为 '\\''。"""
    escaped = prompt.replace("'", "'\\''")
    parts = [
        f"AIXCODE_TEAM_NAME={team_name}",
        f"AIXCODE_TEAMMATE_NAME={teammate_name}",
        f"AIXCODE_MAILBOX_DIR={mailbox_dir}",
        "python -m aixcode -p",
        f"--work-dir {work_dir}",
    ]
    if agent_type:
        parts.append(f"--agent-type {agent_type}")
    if model:
        parts.append(f"--model {model}")
    parts.append(f"'{escaped}'")
    return " ".join(parts)


def _create_pane(team_name: str) -> str:
    """三级 fallback 创建 pane，返回 pane_id。"""
    # 1) 在团队窗口里横向分屏
    r = _run_tmux(["split-window", "-h", "-t", team_name, "-P", "-F", "#{pane_id}"])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    # 2) 新建窗口再分屏
    w = _run_tmux(["new-window", "-t", team_name, "-P", "-F", "#{pane_id}"])
    if w.returncode == 0 and w.stdout.strip():
        r2 = _run_tmux(
            ["split-window", "-h", "-t", w.stdout.strip(), "-P", "-F", "#{pane_id}"]
        )
        if r2.returncode == 0 and r2.stdout.strip():
            return r2.stdout.strip()
    # 3) 新建独立 detached 会话，取首个 pane
    s = _run_tmux(["new-session", "-d", "-s", team_name])
    if s.returncode == 0:
        lp = _run_tmux(["list-panes", "-t", team_name, "-F", "#{pane_id}"])
        if lp.returncode == 0 and lp.stdout.strip():
            return lp.stdout.strip().splitlines()[0]
    raise TmuxSpawnError(f"无法为团队 {team_name!r} 创建 tmux pane")


def spawn_tmux_teammate(
    team_name: str,
    teammate_name: str,
    mailbox_dir: str,
    work_dir: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
) -> TmuxPaneInfo:
    """创建 pane → send-keys 启动队员 CLI 实例。"""
    cmd = build_cli_command(
        team_name, teammate_name, mailbox_dir, work_dir, prompt, agent_type, model
    )
    pane_id = _create_pane(team_name)
    _run_tmux(["send-keys", "-t", pane_id, cmd, "Enter"])
    return TmuxPaneInfo(pane_id=pane_id)


def send_keys_to_pane(pane_id: str, keys: str) -> None:
    """向 pane 发送按键（唤醒读新消息用）；best-effort 静默失败。"""
    try:
        _run_tmux(["send-keys", "-t", pane_id, keys, "Enter"])
    except Exception:  # noqa: BLE001
        pass


def kill_pane(pane_id: str) -> None:
    """杀掉 pane；best-effort 静默失败。"""
    try:
        _run_tmux(["kill-pane", "-t", pane_id])
    except Exception:  # noqa: BLE001
        pass
