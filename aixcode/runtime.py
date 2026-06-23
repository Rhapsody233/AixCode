"""运行时装配：把 config → client → registry → ... → agent 整段装配抽成纯函数，
供 REPL（__main__ → AixCodeApp）与 headless（run_headless）两路复用，杜绝装配漂移。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from aixcode.agent import Agent
from aixcode.agents.loader import AgentLoader
from aixcode.agents.task_manager import TaskManager
from aixcode.agents.trace import TraceManager
from aixcode.client import create_client
from aixcode.config import (
    ProviderConfig,
    load_mcp_servers,
    load_raw_hooks,
)
from aixcode.hooks import HookEngine, load_hooks
from aixcode.memory import MemoryManager
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
from aixcode.teams.registry import AgentNameRegistry
from aixcode.tools import create_default_registry
from aixcode.tools.agent_tool import AgentTool, AgentToolParams
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


@dataclass
class Runtime:
    """assemble_runtime 装好的运行时部件集合（REPL 与 headless 共用）。"""

    agent: Agent
    registry: object
    agent_tool: AgentTool
    team_manager: TeamManager
    hook_engine: HookEngine
    mcp_servers: list
    skill_loader: SkillLoader
    skill_executor: SkillExecutor
    task_manager: TaskManager
    trace_manager: TraceManager
    worktree_manager: object
    config: ProviderConfig


def build_skill_catalog(loader: SkillLoader) -> str:
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


def _make_agent_runner(agent_tool: AgentTool):
    """Hook 的 `agent` 动作 runner：复用 agent_tool spawn general-purpose 子 Agent。"""

    async def runner(prompt: str) -> str:
        result = await agent_tool.execute(
            AgentToolParams(
                prompt=prompt, description="hook agent", subagent_type="general-purpose"
            )
        )
        return result.output

    return runner


def assemble_runtime(
    config: ProviderConfig,
    cwd: str,
    *,
    teammate_mode: str = "",
    enable_coordinator_mode: bool = False,
    team_env=None,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
) -> Runtime:
    """装配整套运行时；team_env 非空时把主 Agent 接成队员（连共享 mailbox）。"""
    client = create_client(config)

    registry = create_default_registry()
    registry.register(ToolSearchTool(registry))
    registry.register(AskUserTool())
    load_skill_tool = LoadSkill()
    registry.register(load_skill_tool)

    permission_checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(project_root=cwd),
        rule_engine=RuleEngine(
            user_rules_path=os.path.expanduser("~/.aixcode/permissions.yaml"),
            project_rules_path=os.path.join(cwd, ".aixcode", "permissions.yaml"),
        ),
        mode=permission_mode,
    )

    hook_engine = HookEngine(load_hooks(load_raw_hooks()))

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
    except ValueError:
        mcp_servers = []

    # ch11 Skill
    skill_loader = SkillLoader(cwd)
    skill_loader.load_all()
    load_skill_tool.set_loader(skill_loader)
    load_skill_tool.set_agent(agent)
    agent.set_skill_catalog(build_skill_catalog(skill_loader))
    skill_executor = SkillExecutor(agent, client, config.protocol)

    # ch14 Worktree
    from aixcode.worktree import WorktreeManager

    worktree_manager = WorktreeManager(
        repo_root=cwd, file_cache=None, symlink_directories=[]
    )
    restored = worktree_manager.restore_session()
    if restored is not None:
        agent.work_dir = restored.worktree_path
    registry.register(EnterWorktreeTool(worktree_manager))
    registry.register(ExitWorktreeTool(worktree_manager))

    # ch15 AgentTeam
    trace_manager = TraceManager()
    team_manager = TeamManager(worktree_manager, trace_manager)

    # ch13 SubAgent
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

    # ch15 七工具 + 写回 team_manager
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

    # ch16 A：本进程是被 spawn 的队员时，接进共享 mailbox（让 _consume_mailbox 收到消息）
    if team_env is not None and team_env.is_teammate:
        team_manager.attach_external_mailbox(team_env.team_name, team_env.mailbox_dir)
        agent.team_name = team_env.team_name
        resolved = AgentNameRegistry.instance().resolve(team_env.teammate_name)
        if resolved is not None:
            agent.agent_id = resolved
        elif team_env.teammate_name:
            AgentNameRegistry.instance().register(team_env.teammate_name, agent.agent_id)
        agent._team_manager = team_manager

    # ch16 B：Hook 的 agent 动作执行器注入 runner（复用 agent_tool spawn 子 Agent）
    hook_engine.set_agent_runner(_make_agent_runner(agent_tool))

    return Runtime(
        agent=agent,
        registry=registry,
        agent_tool=agent_tool,
        team_manager=team_manager,
        hook_engine=hook_engine,
        mcp_servers=mcp_servers,
        skill_loader=skill_loader,
        skill_executor=skill_executor,
        task_manager=task_manager,
        trace_manager=trace_manager,
        worktree_manager=worktree_manager,
        config=config,
    )
