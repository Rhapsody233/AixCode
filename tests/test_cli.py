"""ch16 T1：CLI 参数解析与团队 env 读取测试。"""

import pytest

from aixcode.cli import CliArgs, TeamEnv, parse_args, read_team_env


def test_parse_print_mode_with_prompt():
    args = parse_args(["-p", "do X"])
    assert args.print_mode is True
    assert args.prompt == "do X"


def test_parse_no_print_mode_defaults():
    args = parse_args([])
    assert args.print_mode is False
    assert args.prompt == ""
    assert args.config_path == "config.yaml"
    assert args.permission_mode == "default"
    assert args.work_dir == ""


def test_parse_flags():
    args = parse_args(
        ["-p", "task", "--work-dir", "/wt", "--agent-type", "explore",
         "--model", "deepseek-pro", "--config", "alt.yaml",
         "--permission-mode", "accept"]
    )
    assert args.work_dir == "/wt"
    assert args.agent_type == "explore"
    assert args.model == "deepseek-pro"
    assert args.config_path == "alt.yaml"
    assert args.permission_mode == "accept"


def test_parse_long_print_flag():
    args = parse_args(["--print", "hi"])
    assert args.print_mode is True
    assert args.prompt == "hi"


def test_parse_invalid_permission_mode_exits():
    with pytest.raises(SystemExit):
        parse_args(["-p", "x", "--permission-mode", "nope"])


def test_read_team_env():
    env = {
        "AIXCODE_TEAM_NAME": "refactor-x",
        "AIXCODE_TEAMMATE_NAME": "alice",
        "AIXCODE_MAILBOX_DIR": "/mb",
    }
    te = read_team_env(env)
    assert te.team_name == "refactor-x"
    assert te.teammate_name == "alice"
    assert te.mailbox_dir == "/mb"
    assert te.is_teammate is True


def test_team_env_not_teammate_when_empty():
    te = read_team_env({})
    assert te.team_name == ""
    assert te.is_teammate is False


def test_cli_args_defaults_dataclass():
    a = CliArgs()
    assert a.print_mode is False
    assert a.config_path == "config.yaml"
    assert a.permission_mode == "default"
