"""ch16 T3：run_headless 单次执行驱动测试。"""

import asyncio

from aixcode.agent import ErrorEvent, LoopComplete, PermissionRequest, StreamText
from aixcode.headless import run_headless


class _Runtime:
    def __init__(self, agent):
        self.agent = agent


class _StreamAgent:
    async def run(self, conversation):
        yield StreamText("final ")
        yield StreamText("answer")
        yield LoopComplete("final answer")


class _OnlyLoopAgent:
    async def run(self, conversation):
        yield LoopComplete("only-final")


class _ErrorAgent:
    async def run(self, conversation):
        yield ErrorEvent("boom")


class _PermAgent:
    def __init__(self):
        self.captured = None

    async def run(self, conversation):
        fut = asyncio.get_event_loop().create_future()
        yield PermissionRequest("Bash", "rm -rf", fut)
        self.captured = await fut
        yield LoopComplete("done")


def test_headless_streams_to_stdout(capsys):
    rc = asyncio.run(run_headless(_Runtime(_StreamAgent()), "go"))
    out = capsys.readouterr().out
    assert "final answer" in out
    assert rc == 0


def test_headless_only_loopcomplete_prints_text(capsys):
    rc = asyncio.run(run_headless(_Runtime(_OnlyLoopAgent()), "go"))
    out = capsys.readouterr().out
    assert "only-final" in out
    assert rc == 0


def test_headless_error_returns_nonzero(capsys):
    rc = asyncio.run(run_headless(_Runtime(_ErrorAgent()), "go"))
    err = capsys.readouterr().err
    assert "boom" in err
    assert rc == 1


def test_headless_permission_denied(capsys):
    from aixcode.agent import PermissionResponse

    agent = _PermAgent()
    rc = asyncio.run(run_headless(_Runtime(agent), "go"))
    assert agent.captured == PermissionResponse.DENY
    assert rc == 0
