"""ch16 T9：MCP prompts 注册为 slash command 测试。"""

import asyncio

from aixcode.commands.handlers.mcp_prompt import (
    _parse_prompt_args,
    build_mcp_prompt_command,
    register_mcp_prompts,
)
from aixcode.commands.registry import CommandContext, CommandRegistry, CommandType


class _FakeUI:
    def __init__(self):
        self.sent = []

    def add_system_message(self, t):
        pass

    async def send_user_message(self, t):
        self.sent.append(t)

    def set_plan_mode(self, on):
        pass

    def get_token_count(self):
        return 0

    def refresh_status(self):
        pass


class _PromptManager:
    def __init__(self, prompts, text=""):
        self._prompts = prompts
        self._text = text

    async def list_all_prompts(self):
        return self._prompts

    async def get_prompt(self, server, name, args):
        return f"{self._text}|{server}:{name}:{args}"


def _ctx(args, ui):
    return CommandContext(
        args=args, agent=None, conversation=None, session=None,
        session_manager=None, memory_manager=None, ui=ui, config={},
    )


def test_parse_prompt_args():
    assert _parse_prompt_args("a=1 b=2") == {"a": "1", "b": "2"}
    assert _parse_prompt_args("") == {}
    assert _parse_prompt_args("noeq token") == {}  # 无 = 的 token 忽略


def test_register_mcp_prompts_registers():
    reg = CommandRegistry()
    mgr = _PromptManager([("srv", "p1", "desc1"), ("srv", "p2", "")])
    n = asyncio.run(register_mcp_prompts(reg, mgr))
    assert n == 2
    cmd = reg.find("mcp__srv__p1")
    assert cmd is not None
    assert cmd.type == CommandType.PROMPT


def test_register_mcp_prompts_skips_conflict():
    reg = CommandRegistry()
    mgr = _PromptManager([("srv", "p1", ""), ("srv", "p1", "")])  # 同名
    n = asyncio.run(register_mcp_prompts(reg, mgr))
    assert n == 1  # 第二个冲突被跳过


def test_mcp_prompt_command_handler_sends():
    mgr = _PromptManager([], text="PROMPT-BODY")
    cmd = build_mcp_prompt_command(mgr, "srv", "p1", "desc")
    ui = _FakeUI()
    asyncio.run(cmd.handler(_ctx("a=1", ui)))
    assert any("PROMPT-BODY" in s for s in ui.sent)
    assert any("a" in s for s in ui.sent)  # 参数透传
