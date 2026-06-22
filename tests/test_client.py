import asyncio

import httpx
import openai
import pytest

from aixcode.client import (
    AuthenticationError,
    LLMClient,
    NetworkError,
    OpenAIClient,
    RateLimitError,
    StreamEnd,
    TextDelta,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    create_client,
)
from aixcode.config import ProviderConfig


# --- fakes ------------------------------------------------------------------

class _FuncDelta:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _ToolCallChunk:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = _FuncDelta(name, arguments)


class _Delta:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Usage:
    def __init__(self, prompt_tokens, completion_tokens, prompt_cache_hit_tokens=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        if prompt_cache_hit_tokens is not None:
            self.prompt_cache_hit_tokens = prompt_cache_hit_tokens


class _Chunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


async def _aiter(chunks):
    for c in chunks:
        yield c


class _FakeCompletions:
    def __init__(self, chunks=None, exc=None):
        self._chunks = chunks
        self._exc = exc

    async def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _aiter(self._chunks)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


class _FakeConversation:
    def serialize(self):
        return [{"role": "user", "content": "hi"}]


def _make_client(monkeypatch, chunks=None, exc=None):
    config = ProviderConfig("openai", "deepseek-reasoner", "https://x", "sk-test")
    client = OpenAIClient(config)
    client._client = _FakeOpenAI(_FakeCompletions(chunks=chunks, exc=exc))
    return client


def _collect(stream):
    """把 async generator 收成 list，供同步测试断言。"""
    async def run():
        return [event async for event in stream]

    return asyncio.run(run())


def _response(status, headers=None):
    return httpx.Response(
        status,
        headers=headers,
        request=httpx.Request("POST", "https://x"),
    )


# --- stream parsing ---------------------------------------------------------

def test_stream_yields_thinking_then_text_then_end(monkeypatch):
    chunks = [
        _Chunk([_Choice(_Delta(reasoning_content="let me "))]),
        _Chunk([_Choice(_Delta(reasoning_content="think"))]),
        _Chunk([_Choice(_Delta(content="Hello"))]),
        _Chunk([_Choice(_Delta(content=" world"))]),
        _Chunk(choices=[], usage=_Usage(prompt_tokens=11, completion_tokens=7)),
    ]
    client = _make_client(monkeypatch, chunks=chunks)

    events = _collect(client.stream(_FakeConversation()))

    assert events[0] == ThinkingDelta("let me ")
    assert events[1] == ThinkingDelta("think")
    assert events[2] == TextDelta("Hello")
    assert events[3] == TextDelta(" world")
    assert events[4] == StreamEnd(input_tokens=11, output_tokens=7)


def test_stream_prepends_system_message(monkeypatch):
    captured = {}

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return _aiter([_Chunk(choices=[], usage=_Usage(1, 1))])

    config = ProviderConfig("openai", "deepseek-chat", "https://x", "sk-test")
    client = OpenAIClient(config)
    client._client = _FakeOpenAI(_CapturingCompletions())

    _collect(client.stream(_FakeConversation(), system="你是助手"))

    assert captured["messages"][0] == {"role": "system", "content": "你是助手"}
    assert captured["messages"][1] == {"role": "user", "content": "hi"}


def test_stream_no_system_message_when_absent(monkeypatch):
    captured = {}

    class _CapturingCompletions(_FakeCompletions):
        async def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return _aiter([_Chunk(choices=[], usage=_Usage(1, 1))])

    config = ProviderConfig("openai", "deepseek-chat", "https://x", "sk-test")
    client = OpenAIClient(config)
    client._client = _FakeOpenAI(_CapturingCompletions())

    _collect(client.stream(_FakeConversation()))

    assert all(m["role"] != "system" for m in captured["messages"])


def test_stream_skips_empty_deltas(monkeypatch):
    chunks = [
        _Chunk([_Choice(_Delta(content=None, reasoning_content=None))]),
        _Chunk([_Choice(_Delta(content="x"))]),
        _Chunk(choices=[], usage=_Usage(1, 1)),
    ]
    client = _make_client(monkeypatch, chunks=chunks)

    events = _collect(client.stream(_FakeConversation()))

    assert events == [TextDelta("x"), StreamEnd(1, 1)]


def test_stream_reads_cache_hit_tokens(monkeypatch):
    chunks = [
        _Chunk([_Choice(_Delta(content="hi"))]),
        _Chunk(choices=[], usage=_Usage(20, 5, prompt_cache_hit_tokens=18)),
    ]
    client = _make_client(monkeypatch, chunks=chunks)

    events = _collect(client.stream(_FakeConversation()))

    assert events[-1].cache_hit_tokens == 18


def test_stream_parses_streamed_tool_call(monkeypatch):
    chunks = [
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCallChunk(0, id="call_1", name="ReadFile")]))]),
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCallChunk(0, arguments='{"file_path": ')]))]),
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCallChunk(0, arguments='"a.txt"}')]))]),
        _Chunk([_Choice(_Delta(), finish_reason="tool_calls")]),
        _Chunk(choices=[], usage=_Usage(3, 4)),
    ]
    client = _make_client(monkeypatch, chunks=chunks)

    events = _collect(client.stream(_FakeConversation()))

    assert events[0] == ToolCallStart("call_1", "ReadFile")
    assert all(isinstance(e, ToolCallDelta) for e in events[1:3])
    assert events[-2] == ToolCallComplete("call_1", "ReadFile", {"file_path": "a.txt"})
    assert events[-1] == StreamEnd(3, 4)


def test_stream_tolerates_invalid_tool_call_json(monkeypatch):
    # 模型给出截断/非法的参数 JSON：必须兜底为空 dict 而非抛异常崩溃
    chunks = [
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCallChunk(0, id="c1", name="ReadFile")]))]),
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCallChunk(0, arguments='{"file_path": ')]))]),
        _Chunk([_Choice(_Delta(), finish_reason="tool_calls")]),
        _Chunk(choices=[], usage=_Usage(1, 1)),
    ]
    client = _make_client(monkeypatch, chunks=chunks)

    events = _collect(client.stream(_FakeConversation()))

    completes = [e for e in events if isinstance(e, ToolCallComplete)]
    assert len(completes) == 1
    assert completes[0].arguments == {}
    assert isinstance(events[-1], StreamEnd)


# --- error classification ---------------------------------------------------

def test_auth_error_classified(monkeypatch):
    exc = openai.AuthenticationError("bad key", response=_response(401), body=None)
    client = _make_client(monkeypatch, exc=exc)

    with pytest.raises(AuthenticationError):
        _collect(client.stream(_FakeConversation()))


def test_rate_limit_error_carries_retry_after(monkeypatch):
    exc = openai.RateLimitError(
        "slow down",
        response=_response(429, headers={"retry-after": "12"}),
        body=None,
    )
    client = _make_client(monkeypatch, exc=exc)

    with pytest.raises(RateLimitError) as got:
        _collect(client.stream(_FakeConversation()))

    assert got.value.retry_after == 12.0


def test_connection_error_classified_as_network(monkeypatch):
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://x"))
    client = _make_client(monkeypatch, exc=exc)

    with pytest.raises(NetworkError):
        _collect(client.stream(_FakeConversation()))


# --- construction & factory -------------------------------------------------

def test_missing_api_key_raises_auth_error():
    config = ProviderConfig("openai", "deepseek-chat", "https://x", "")

    with pytest.raises(AuthenticationError):
        OpenAIClient(config)


def test_create_client_routes_openai():
    config = ProviderConfig("openai", "deepseek-chat", "https://x", "sk-test")

    client = create_client(config)

    assert isinstance(client, OpenAIClient)
    assert isinstance(client, LLMClient)


def test_create_client_unknown_protocol_raises():
    config = ProviderConfig("mystery", "m", "https://x", "sk-test")

    with pytest.raises(ValueError, match="Unknown protocol"):
        create_client(config)
