"""python -m aixcode 入口：装配 config → client → conversation → REPL。"""

from __future__ import annotations

import asyncio
import os
import sys

from aixcode.agent import Agent
from aixcode.agents.loader import AgentLoader
from aixcode.agents.task_manager import TaskManager
from aixcode.agents.trace import TraceManager
from aixcode.app import AixCodeApp
from aixcode.worktree import WorktreeManager
from aixcode.client import AuthenticationError, create_client
from aixcode.config import (
    load_config,
    load_mcp_servers,
    load_raw_hooks,
    load_team_settings,
)
from aixcode.hooks import HookConfigError, HookEngine, load_hooks
from aixcode.memory import MemoryManager
from aixcode.conversation import ConversationManager
from aixcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from aixcode.skills.executor import SkillExecutor
from aixcode.skills.loader import SkillLoader
from aixcode.teams.manager import TeamManager
from aixcode.tools import create_default_registry
from aixcode.tools.agent_tool import AgentTool
from aixcode.tools.ask_user import AskUserTool
from aixcode.tools.enter_worktree import EnterWorktreeTool
from aixcode.tools.exit_worktree import ExitWorktreeTool
from aixcode.tools.load_skill import LoadSkill
from aixcode.tools.send_message import SendMessageTool
from aixcode.tools.task_create import TaskCreateTool
from aixcode.tools.task_get import TaskGetTool
from aixcode.tools.task_list import TaskListTool
from aixcode.tools.task_update import TaskUpdateTool
from aixcode.tools.team_create import TeamCreateTool
from aixcode.tools.team_delete import TeamDeleteTool
from aixcode.tools.tool_search import ToolSearchTool


def _build_skill_catalog(loader: SkillLoader) -> str:
    """把 skill 清单拼成一段静态 catalog 注入对话（progressive disclosure）。"""
    catalog = loader.get_catalog()
    if not catalog:
        return ""
    lines = "\n".join(f"- {name}: {desc}" for name, desc in catalog)
    return (
        "You can use the following Skills:\n\n"
        f"{lines}\n\n"
        "If the user's request matches a Skill, call LoadSkill to activate it."
    )


def main() -> int:
    # 强制 UTF-8 输出，避免中文 Windows 控制台（GBK）遇到非 GBK 字符崩溃
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"配置错误：{e}", file=sys.stderr)
        return 1

    try:
        client = create_client(config)
    except AuthenticationError as e:
        print(f"认证错误：{e}", file=sys.stderr)
        return 1

    registry = create_default_registry()
    registry.register(ToolSearchTool(registry))
    registry.register(AskUserTool())
    # LoadSkill 须在建 Agent 前注册进 registry（系统工具，read-only）
    load_skill_tool = LoadSkill()
    registry.register(load_skill_tool)

    cwd = os.getcwd()
    permission_checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(project_root=cwd),
        rule_engine=RuleEngine(
            user_rules_path=os.path.expanduser("~/.aixcode/permissions.yaml"),
            project_rules_path=os.path.join(cwd, ".aixcode", "permissions.yaml"),
        ),
        mode=PermissionMode.DEFAULT,
    )

    # ch12 Hook 系统：加载并校验 hooks，非法配置打 stderr 并退出
    try:
        hook_engine = HookEngine(load_hooks(load_raw_hooks()))
    except HookConfigError as e:
        print(f"Hook 配置错误：{e}", file=sys.stderr)
        return 1

    agent = Agent(
        client,
        registry,
        protocol=config.protocol,
        work_dir=cwd,
        permission_checker=permission_checker,
        memory_manager=MemoryManager(cwd),
        hook_engine=hook_engine,
    )
    try:
        mcp_servers = load_mcp_servers()
    except ValueError as e:
        print(f"MCP 配置警告（已忽略）：{e}", file=sys.stderr)
        mcp_servers = []

    # ch11 Skill 系统：加载 skill、注入 LoadSkill 依赖、注入 catalog、建 executor
    skill_loader = SkillLoader(cwd)
    skill_loader.load_all()
    load_skill_tool.set_loader(skill_loader)
    load_skill_tool.set_agent(agent)
    agent.set_skill_catalog(_build_skill_catalog(skill_loader))
    skill_executor = SkillExecutor(agent, client, config.protocol)

    # ch14 Worktree 系统：建 manager、恢复上次 session、注册两工具
    worktree_manager = WorktreeManager(
        repo_root=cwd, file_cache=None, symlink_directories=[]
    )
    restored = worktree_manager.restore_session()
    if restored is not None:
        agent.work_dir = restored.worktree_path
    registry.register(EnterWorktreeTool(worktree_manager))
    registry.register(ExitWorktreeTool(worktree_manager))

    # ch15 AgentTeam 系统：读团队设置、建 TeamManager（复用 worktree/trace）
    try:
        teammate_mode, enable_coordinator_mode = load_team_settings()
    except ValueError as e:
        print(f"团队配置警告（已忽略）：{e}", file=sys.stderr)
        teammate_mode, enable_coordinator_mode = "", False
    trace_manager = TraceManager()
    team_manager = TeamManager(worktree_manager, trace_manager)

    # ch13 SubAgent 系统：加载子 Agent 定义、建后台管理器、注册 Agent 工具
    agent_loader = AgentLoader(cwd)
    agent_loader.load_all()
    task_manager = TaskManager()
    agent_tool = AgentTool(
        agent_loader=agent_loader,
        task_manager=task_manager,
        trace_manager=trace_manager,
        parent_agent=agent,
        provider_config=config,
        enable_fork=True,
        worktree_manager=worktree_manager,
        team_manager=team_manager,
    )
    registry.register(agent_tool)

    # ch15：注册团队七工具 + 写回主 Agent 的 team_manager（agent_id 已在构造时生成）
    registry.register(
        TeamCreateTool(
            team_manager, agent, teammate_mode=teammate_mode, is_interactive=True,
            enable_coordinator_mode=enable_coordinator_mode,
        )
    )
    registry.register(TeamDeleteTool(team_manager, agent))
    registry.register(SendMessageTool(team_manager, agent))
    registry.register(TaskCreateTool(team_manager, agent))
    registry.register(TaskGetTool(team_manager, agent))
    registry.register(TaskListTool(team_manager, agent))
    registry.register(TaskUpdateTool(team_manager, agent))
    agent._team_manager = team_manager

    conversation = ConversationManager()
    asyncio.run(
        AixCodeApp(
            agent,
            conversation,
            model=config.model,
            mcp_servers=mcp_servers,
            skill_loader=skill_loader,
            skill_executor=skill_executor,
            hook_engine=hook_engine,
            task_manager=task_manager,
            trace_manager=trace_manager,
            worktree_manager=worktree_manager,
        ).run()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
