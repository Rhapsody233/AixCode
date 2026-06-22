import asyncio

from aixcode.tools.ask_user import AskUserTool


def test_metadata():
    tool = AskUserTool()
    assert tool.should_defer is True
    assert tool.is_system_tool is True


def test_resolves_numbered_choice(monkeypatch):
    tool = AskUserTool()
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    params = tool.params_model(
        questions=[{"name": "color", "message": "pick a color", "options": ["red", "green", "blue"]}]
    )

    result = asyncio.run(tool.execute(params))

    assert "color: green" in result.output


def test_free_text_answer(monkeypatch):
    tool = AskUserTool()
    monkeypatch.setattr("builtins.input", lambda *a: "teal")
    params = tool.params_model(
        questions=[{"name": "color", "message": "pick", "options": []}]
    )

    result = asyncio.run(tool.execute(params))

    assert "color: teal" in result.output


def test_timeout_returns_error(monkeypatch):
    tool = AskUserTool()
    tool.timeout = 0.01

    async def _slow(_params):
        await asyncio.sleep(1)

    monkeypatch.setattr(tool, "_ask", _slow)

    result = asyncio.run(tool.execute(tool.params_model(questions=[])))

    assert result.is_error is True
    assert "did not respond within 5 minutes" in result.output
