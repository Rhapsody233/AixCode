"""命令行参数解析：REPL 与 `-p` headless 单次执行模式共用一份 CliArgs。"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

# 与 commands.handlers.mode.parse_mode_name 一致的四档（plan 走 /plan·/do，不在 CLI）
_PERMISSION_MODES = ("default", "strict", "accept", "bypass")


@dataclass
class CliArgs:
    """一次 `python -m aixcode ...` 调用的解析结果。

    团队信息（team/teammate/mailbox）不在此处——它们经环境变量传入（见 TeamEnv）。
    """

    print_mode: bool = False
    prompt: str = ""
    work_dir: str = ""
    agent_type: str = ""
    model: str = ""
    config_path: str = "config.yaml"
    permission_mode: str = "default"


@dataclass
class TeamEnv:
    """从 AIXCODE_* 环境变量读出的队员上下文（ch15 pane/in-process 队员用）。"""

    team_name: str = ""
    teammate_name: str = ""
    mailbox_dir: str = ""

    @property
    def is_teammate(self) -> bool:
        """team 名与 mailbox 目录都在时，本进程是被 spawn 的队员。"""
        return bool(self.team_name and self.mailbox_dir)


def parse_args(argv: list[str]) -> CliArgs:
    """解析命令行。`-p/--print` 进 headless 单次执行；否则进 REPL。"""
    parser = argparse.ArgumentParser(
        prog="aixcode", description="AixCode 终端 AI 编程助手"
    )
    parser.add_argument("-p", "--print", dest="print_mode", action="store_true",
                        help="单次执行模式：跑完打印结果退出，不进交互 REPL")
    parser.add_argument("prompt", nargs="?", default="", help="单次执行的任务描述")
    parser.add_argument("--work-dir", dest="work_dir", default="", help="工作目录")
    parser.add_argument("--agent-type", dest="agent_type", default="",
                        help="作为队员时的子 Agent 类型")
    parser.add_argument("--model", dest="model", default="", help="覆盖模型")
    parser.add_argument("--config", dest="config_path", default="config.yaml",
                        help="配置文件路径")
    parser.add_argument("--permission-mode", dest="permission_mode", default="default",
                        choices=_PERMISSION_MODES, help="权限模式")
    ns = parser.parse_args(argv)
    return CliArgs(
        print_mode=ns.print_mode,
        prompt=ns.prompt,
        work_dir=ns.work_dir,
        agent_type=ns.agent_type,
        model=ns.model,
        config_path=ns.config_path,
        permission_mode=ns.permission_mode,
    )


def read_team_env(environ: dict | None = None) -> TeamEnv:
    """从环境变量读队员上下文（AIXCODE_TEAM_NAME / TEAMMATE_NAME / MAILBOX_DIR）。"""
    env = environ if environ is not None else os.environ
    return TeamEnv(
        team_name=env.get("AIXCODE_TEAM_NAME", ""),
        teammate_name=env.get("AIXCODE_TEAMMATE_NAME", ""),
        mailbox_dir=env.get("AIXCODE_MAILBOX_DIR", ""),
    )
