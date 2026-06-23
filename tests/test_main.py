"""ch16 T4：__main__ 按 -p 分发 headless / REPL 测试。"""

from types import SimpleNamespace

import aixcode.__main__ as m


def _fake_runtime():
    return SimpleNamespace(
        agent=object(), mcp_servers=[], skill_loader=None, skill_executor=None,
        hook_engine=None, task_manager=None, trace_manager=None, worktree_manager=None,
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(m, "load_config", lambda path="config.yaml": SimpleNamespace(model="deepseek-chat"))
    monkeypatch.setattr(m, "load_team_settings", lambda path="config.yaml": ("", False))
    monkeypatch.setattr(m, "assemble_runtime", lambda *a, **k: _fake_runtime())


def test_main_print_mode_calls_headless(monkeypatch):
    _patch_common(monkeypatch)
    called = {}

    async def fake_headless(runtime, prompt, mode=None):
        called["prompt"] = prompt
        return 7

    monkeypatch.setattr(m, "run_headless", fake_headless)
    monkeypatch.setattr(m.sys, "argv", ["aixcode", "-p", "hello world"])
    rc = m.main()
    assert called["prompt"] == "hello world"
    assert rc == 7


def test_main_repl_mode_builds_app(monkeypatch):
    _patch_common(monkeypatch)
    built = {}

    class _FakeApp:
        def __init__(self, *a, **k):
            built["yes"] = True

        async def run(self):
            return None

    monkeypatch.setattr(m, "AixCodeApp", _FakeApp)
    monkeypatch.setattr(m.sys, "argv", ["aixcode"])
    rc = m.main()
    assert built.get("yes") is True
    assert rc == 0
