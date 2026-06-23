"""python -m aixcode 入口：解析 CLI → 装配 runtime → headless 或 REPL。"""

from __future__ import annotations

import asyncio
import os
import sys

from aixcode.app import AixCodeApp
from aixcode.cli import parse_args, read_team_env
from aixcode.client import AuthenticationError
from aixcode.commands.handlers.mode import parse_mode_name
from aixcode.config import load_config, load_team_settings
from aixcode.conversation import ConversationManager
from aixcode.headless import run_headless
from aixcode.hooks import HookConfigError
from aixcode.permissions import PermissionMode
from aixcode.runtime import assemble_runtime


def main() -> int:
    # 强制 UTF-8 输出，避免中文 Windows 控制台（GBK）遇到非 GBK 字符崩溃
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    args = parse_args(sys.argv[1:])

    try:
        config = load_config(args.config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"配置错误：{e}", file=sys.stderr)
        return 1

    try:
        teammate_mode, enable_coordinator_mode = load_team_settings(args.config_path)
    except ValueError as e:
        print(f"团队配置警告（已忽略）：{e}", file=sys.stderr)
        teammate_mode, enable_coordinator_mode = "", False

    cwd = args.work_dir or os.getcwd()
    team_env = read_team_env()
    permission_mode = parse_mode_name(args.permission_mode) or PermissionMode.DEFAULT

    try:
        runtime = assemble_runtime(
            config,
            cwd,
            teammate_mode=teammate_mode,
            enable_coordinator_mode=enable_coordinator_mode,
            team_env=team_env,
            permission_mode=permission_mode,
        )
    except AuthenticationError as e:
        print(f"认证错误：{e}", file=sys.stderr)
        return 1
    except HookConfigError as e:
        print(f"Hook 配置错误：{e}", file=sys.stderr)
        return 1

    if args.print_mode:
        return asyncio.run(run_headless(runtime, args.prompt, permission_mode))

    conversation = ConversationManager()
    asyncio.run(
        AixCodeApp(
            runtime.agent,
            conversation,
            model=config.model,
            mcp_servers=runtime.mcp_servers,
            skill_loader=runtime.skill_loader,
            skill_executor=runtime.skill_executor,
            hook_engine=runtime.hook_engine,
            task_manager=runtime.task_manager,
            trace_manager=runtime.trace_manager,
            worktree_manager=runtime.worktree_manager,
        ).run()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
