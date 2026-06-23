"""ch16 T2/T4：assemble_runtime 抽取（零回归）+ 队员 env 接线测试。"""

import pytest

from aixcode.cli import TeamEnv
from aixcode.config import ProviderConfig
from aixcode.permissions import PermissionMode
from aixcode.runtime import Runtime, assemble_runtime
from aixcode.teams.registry import AgentNameRegistry


@pytest.fixture(autouse=True)
def _reset_name_registry():
    AgentNameRegistry.reset()
    yield
    AgentNameRegistry.reset()


def _provider():
    return ProviderConfig(
        protocol="openai", model="deepseek-chat",
        base_url="https://api.deepseek.com", api_key="sk-test",
    )


def test_assemble_runtime_builds_full_runtime(tmp_path):
    rt = assemble_runtime(_provider(), str(tmp_path))
    assert isinstance(rt, Runtime)
    assert rt.agent is not None
    assert rt.agent.agent_id and len(rt.agent.agent_id) == 12
    # ch15 七工具 + ch13 Agent 工具都注册了
    assert rt.registry.get("Agent") is not None
    assert rt.registry.get("TeamCreate") is not None
    assert rt.registry.get("SendMessage") is not None
    assert rt.registry.get("ReadFile") is not None
    # team_manager 写回主 Agent
    assert rt.agent._team_manager is rt.team_manager
    assert rt.team_manager is not None
    assert rt.hook_engine is not None


def test_assemble_runtime_permission_mode(tmp_path):
    rt = assemble_runtime(
        _provider(), str(tmp_path), permission_mode=PermissionMode.ACCEPT_EDITS
    )
    assert rt.agent.permission_checker.mode == PermissionMode.ACCEPT_EDITS


def test_attach_external_mailbox(tmp_path):
    from aixcode.teams.manager import TeamManager
    from aixcode.teams.mailbox import create_message

    tm = TeamManager()
    mb = tm.attach_external_mailbox("t", str(tmp_path / "mb"))
    assert tm.get_mailbox("t") is mb
    mb.write("a1", create_message("x", "a1", "hi", summary="s"))
    assert len(tm.get_mailbox("t").read("a1")) == 1


def test_assemble_runtime_teammate_wiring(tmp_path):
    mailbox_dir = str(tmp_path / "shared_mb")
    team_env = TeamEnv(team_name="t", teammate_name="alice", mailbox_dir=mailbox_dir)
    rt = assemble_runtime(_provider(), str(tmp_path), team_env=team_env)
    assert rt.agent.team_name == "t"
    assert rt.agent._team_manager.get_mailbox("t") is not None
    assert AgentNameRegistry.instance().resolve("alice") == rt.agent.agent_id


def test_assemble_runtime_no_team_env(tmp_path):
    rt = assemble_runtime(_provider(), str(tmp_path))
    assert rt.agent.team_name == ""  # 非队员，team_name 不被设置
