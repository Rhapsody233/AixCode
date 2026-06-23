"""ch07 MCP 协议客户端测试。"""

import pytest

from aixcode.config import (
    MCPServerConfig,
    build_child_env,
    load_mcp_servers,
    resolve_env_vars,
)


# --- T1: 配置层 -------------------------------------------------------------

def _write_yaml(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_mcp_server_config_is_stdio():
    stdio = MCPServerConfig(name="a", command="npx", args=["-y", "x"])
    http = MCPServerConfig(name="b", url="https://h/mcp")
    assert stdio.is_stdio is True
    assert http.is_stdio is False


def test_load_mcp_servers_stdio(tmp_path):
    p = _write_yaml(tmp_path / "config.yaml", """
protocol: openai
model: deepseek-chat
base_url: https://api.deepseek.com
api_key: sk-x
mcp_servers:
  context7:
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
""")
    servers = load_mcp_servers(p)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "context7" and s.command == "npx"
    assert s.args == ["-y", "@upstash/context7-mcp"]
    assert s.is_stdio is True


def test_load_mcp_servers_http(tmp_path):
    p = _write_yaml(tmp_path / "config.yaml", """
mcp_servers:
  remote:
    url: https://example.com/mcp
    headers:
      Authorization: "Bearer ${MY_TOKEN}"
""")
    servers = load_mcp_servers(p)
    assert len(servers) == 1
    assert servers[0].url == "https://example.com/mcp"
    assert servers[0].is_stdio is False


def test_load_mcp_servers_missing_key_returns_empty(tmp_path):
    p = _write_yaml(tmp_path / "config.yaml", "protocol: openai\n")
    assert load_mcp_servers(p) == []


def test_load_mcp_servers_both_command_and_url_errors(tmp_path):
    p = _write_yaml(tmp_path / "config.yaml", """
mcp_servers:
  bad:
    command: npx
    url: https://x/mcp
""")
    with pytest.raises(ValueError, match="不能同时"):
        load_mcp_servers(p)


def test_load_mcp_servers_neither_errors(tmp_path):
    p = _write_yaml(tmp_path / "config.yaml", """
mcp_servers:
  bad:
    args: ["x"]
""")
    with pytest.raises(ValueError, match="必须至少"):
        load_mcp_servers(p)


def test_resolve_env_vars(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    out = resolve_env_vars({"Authorization": "Bearer ${MY_TOKEN}", "X": "plain"})
    assert out["Authorization"] == "Bearer secret123"
    assert out["X"] == "plain"


def test_resolve_env_vars_missing_kept(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    out = resolve_env_vars({"k": "${NOPE}"})
    assert out["k"] == "${NOPE}"


def test_build_child_env_whitelist(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = build_child_env({"MCP_FOO": "bar"})
    assert env.get("MCP_FOO") == "bar"
    assert "PATH" in env
    # 宿主机敏感变量不应被整体复制进子进程环境
    assert "ANTHROPIC_API_KEY" not in env


# --- T2: tool_wrapper 纯函数 -----------------------------------------------

from typing import Any  # noqa: E402

from aixcode.mcp.tool_wrapper import (  # noqa: E402
    _build_params_model,
    _extract_text,
    _json_type_to_python,
)


@pytest.mark.parametrize(
    "json_type,py",
    [
        ("string", str),
        ("integer", int),
        ("number", float),
        ("boolean", bool),
        ("object", dict),
        ("array", list),
        ("weird", Any),
        (None, Any),
    ],
)
def test_json_type_to_python(json_type, py):
    assert _json_type_to_python(json_type) is py


def test_build_params_model_required_and_optional():
    schema = {
        "type": "object",
        "properties": {
            "q": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["q"],
    }
    Model = _build_params_model("Search", schema)
    # required 缺失应报错
    with pytest.raises(Exception):
        Model()
    m = Model(q="next.js")
    assert m.q == "next.js"
    assert m.limit is None  # optional 默认 None


def test_build_params_model_empty_schema():
    Model = _build_params_model("Empty", {})
    assert Model() is not None  # 空模型可实例化


class _Text:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Img:
    def __init__(self):
        self.type = "image"
        self.data = "base64..."
        self.mimeType = "image/png"


def test_extract_text_joins_text_blocks():
    out = _extract_text([_Text("hello"), _Text("world")])
    assert "hello" in out and "world" in out


def test_extract_text_empty_is_no_output():
    assert _extract_text([]) == "(no output)"


def test_extract_text_image_placeholder():
    out = _extract_text([_Img()])
    assert "image" in out.lower()


# --- T3: MCPToolWrapper -----------------------------------------------------

from aixcode.mcp.tool_wrapper import MCPToolWrapper  # noqa: E402


class _ToolDef:
    def __init__(self, name, description="desc", input_schema=None):
        self.name = name
        self.description = description
        self.inputSchema = input_schema or {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }


class _CallResult:
    def __init__(self, content, is_error=False):
        self.content = content
        self.isError = is_error


class _FakeClient:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if self.raises:
            raise self.raises
        return self.result


class _FakeManager:
    def __init__(self, client):
        self._client = client

    async def get_client(self, name):
        return self._client


def _wrapper(client, tool_name="resolve_library_id"):
    return MCPToolWrapper(_FakeManager(client), "context7", _ToolDef(tool_name))


def test_wrapper_name_and_meta():
    w = _wrapper(_FakeClient())
    assert w.name == "mcp_context7_resolve_library_id"
    assert w.category == "command"
    assert w.should_defer is True


def test_wrapper_get_schema_returns_raw_input_schema():
    w = _wrapper(_FakeClient())
    schema = w.get_schema()
    assert schema["name"] == "mcp_context7_resolve_library_id"
    assert schema["parameters"]["required"] == ["q"]


def test_wrapper_execute_passthrough_text():
    import asyncio

    client = _FakeClient(_CallResult([_Text("next.js v15")]))
    w = _wrapper(client)
    params = w.params_model(q="next.js")
    result = asyncio.run(w.execute(params))
    assert result.is_error is False
    assert "next.js v15" in result.output
    assert client.calls == [("resolve_library_id", {"q": "next.js"})]


def test_wrapper_execute_passes_is_error():
    import asyncio

    client = _FakeClient(_CallResult([_Text("boom")], is_error=True))
    w = _wrapper(client)
    result = asyncio.run(w.execute(w.params_model(q="x")))
    assert result.is_error is True


def test_wrapper_execute_wraps_exception():
    import asyncio

    client = _FakeClient(raises=RuntimeError("connection lost"))
    w = _wrapper(client)
    result = asyncio.run(w.execute(w.params_model(q="x")))
    assert result.is_error is True
    assert "connection lost" in result.output


# --- T4: MCPClient ----------------------------------------------------------

import asyncio  # noqa: E402

from aixcode.config import MCPServerConfig as _Cfg  # noqa: E402
from aixcode.mcp.client import MCPClient  # noqa: E402


class _Tools:
    def __init__(self, tools):
        self.tools = tools


class _FakeSession:
    def __init__(self, tools=None, result=None):
        self._tools = tools or []
        self._result = result

    async def list_tools(self):
        return _Tools(self._tools)

    async def call_tool(self, name, args):
        return self._result


def test_client_list_tools_delegates():
    client = MCPClient(_Cfg(name="s", command="x"))
    client._session = _FakeSession(tools=[_ToolDef("a"), _ToolDef("b")])
    tools = asyncio.run(client.list_tools())
    assert [t.name for t in tools] == ["a", "b"]


def test_client_call_tool_delegates():
    client = MCPClient(_Cfg(name="s", command="x"))
    sentinel = _CallResult([_Text("ok")])
    client._session = _FakeSession(result=sentinel)
    assert asyncio.run(client.call_tool("a", {})) is sentinel


def test_client_close_sets_not_alive():
    client = MCPClient(_Cfg(name="s", command="x"))
    client._alive = True

    class _Stack:
        async def aclose(self):
            return None

    client._stack = _Stack()
    asyncio.run(client.close())
    assert client.is_alive is False


def test_cleanup_stack_swallows_cancel_scope_error():
    client = MCPClient(_Cfg(name="s", command="x"))

    class _BadStack:
        async def aclose(self):
            raise RuntimeError("Attempted to exit cancel scope in a different task")

    client._stack = _BadStack()
    # 不应上抛
    asyncio.run(client._cleanup_stack())


# --- T5: MCPManager ---------------------------------------------------------

from aixcode.mcp import MCPManager  # noqa: E402
from aixcode.tools import ToolRegistry  # noqa: E402


class _FakeMCPClient:
    def __init__(self, config, tools=None, connect_error=None):
        self.config = config
        self.name = config.name
        self._tools = tools if tools is not None else [_ToolDef("ping")]
        self._connect_error = connect_error
        self._alive = False
        self.connects = 0
        self.closes = 0

    @property
    def is_alive(self):
        return self._alive

    async def connect(self):
        self.connects += 1
        if self._connect_error:
            raise self._connect_error
        self._alive = True

    async def list_tools(self):
        return self._tools

    async def close(self):
        self._alive = False
        self.closes += 1


def _manager_with(behaviors):
    """behaviors: name -> kwargs for _FakeMCPClient。返回 (manager, created dict)。"""
    created = {}

    def factory(config):
        client = _FakeMCPClient(config, **behaviors.get(config.name, {}))
        created[config.name] = client
        return client

    return MCPManager(client_factory=factory), created


def test_register_all_tools_two_servers():
    mgr, created = _manager_with({})
    mgr.load_configs([_Cfg(name="s1", command="x"), _Cfg(name="s2", command="y")])
    registry = ToolRegistry()
    errors = asyncio.run(mgr.register_all_tools(registry))
    assert errors == []
    assert registry.get("mcp_s1_ping") is not None
    assert registry.get("mcp_s2_ping") is not None


def test_register_all_tools_partial_failure_does_not_block():
    mgr, created = _manager_with({"bad": {"connect_error": RuntimeError("boom")}})
    mgr.load_configs([_Cfg(name="bad", command="x"), _Cfg(name="good", command="y")])
    registry = ToolRegistry()
    errors = asyncio.run(mgr.register_all_tools(registry))
    assert any("bad" in e for e in errors)
    # good 仍被注册
    assert registry.get("mcp_good_ping") is not None


def test_get_client_caches():
    mgr, created = _manager_with({})
    mgr.load_configs([_Cfg(name="s", command="x")])
    c1 = asyncio.run(mgr.get_client("s"))
    c2 = asyncio.run(mgr.get_client("s"))
    assert c1 is c2
    assert c1.connects == 1  # 缓存命中不重连


def test_get_client_reconnects_when_dead():
    mgr, created = _manager_with({})
    mgr.load_configs([_Cfg(name="s", command="x")])
    c1 = asyncio.run(mgr.get_client("s"))
    c1._alive = False  # 模拟失活
    c2 = asyncio.run(mgr.get_client("s"))
    assert c2 is not c1  # 重建


def test_shutdown_idempotent():
    mgr, created = _manager_with({})
    mgr.load_configs([_Cfg(name="s", command="x")])
    asyncio.run(mgr.get_client("s"))
    asyncio.run(mgr.shutdown())
    assert created["s"].closes == 1
    # 二次 shutdown 不抛
    asyncio.run(mgr.shutdown())


# --- ch16 T6: MCPClient resources/prompts -----------------------------------

class _Resources:
    def __init__(self, resources):
        self.resources = resources


class _ReadResult:
    def __init__(self, contents):
        self.contents = contents


class _Prompts:
    def __init__(self, prompts):
        self.prompts = prompts


class _PromptMsg:
    def __init__(self, text):
        self.content = _Text(text)


class _GetPromptResult:
    def __init__(self, messages):
        self.messages = messages


class _ResPromptSession:
    def __init__(self, resources=None, read=None, prompts=None, prompt_result=None):
        self._resources = resources or []
        self._read = read
        self._prompts = prompts or []
        self._prompt_result = prompt_result

    async def list_resources(self):
        return _Resources(self._resources)

    async def read_resource(self, uri):
        return self._read

    async def list_prompts(self):
        return _Prompts(self._prompts)

    async def get_prompt(self, name, args):
        return self._prompt_result


class _Res:
    def __init__(self, uri, name="", description=""):
        self.uri = uri
        self.name = name
        self.description = description


def test_client_list_resources_delegates():
    client = MCPClient(_Cfg(name="s", command="x"))
    client._session = _ResPromptSession(resources=[_Res("mem://a"), _Res("mem://b")])
    res = asyncio.run(client.list_resources())
    assert [r.uri for r in res] == ["mem://a", "mem://b"]


def test_client_read_resource_joins_text():
    client = MCPClient(_Cfg(name="s", command="x"))
    client._session = _ResPromptSession(
        read=_ReadResult([_Text("part1"), _Text("part2")])
    )
    text = asyncio.run(client.read_resource("mem://a"))
    assert "part1" in text and "part2" in text


def test_client_list_prompts_delegates():
    client = MCPClient(_Cfg(name="s", command="x"))

    class _P:
        def __init__(self, name):
            self.name = name
            self.description = ""

    client._session = _ResPromptSession(prompts=[_P("p1"), _P("p2")])
    prompts = asyncio.run(client.list_prompts())
    assert [p.name for p in prompts] == ["p1", "p2"]


def test_client_get_prompt_joins_messages():
    client = MCPClient(_Cfg(name="s", command="x"))
    client._session = _ResPromptSession(
        prompt_result=_GetPromptResult([_PromptMsg("hello"), _PromptMsg("world")])
    )
    text = asyncio.run(client.get_prompt("p1", {"a": "1"}))
    assert "hello" in text and "world" in text


# --- ch16 T7: MCPManager 资源/提示发现 + 路由 -------------------------------

class _ResFakeClient:
    def __init__(self, config, resources=None, prompts=None, read_map=None,
                 prompt_text="", connect_error=None):
        self.config = config
        self.name = config.name
        self._resources = resources or []
        self._prompts = prompts or []
        self._read_map = read_map or {}
        self._prompt_text = prompt_text
        self._connect_error = connect_error
        self._alive = False

    @property
    def is_alive(self):
        return self._alive

    async def connect(self):
        if self._connect_error:
            raise self._connect_error
        self._alive = True

    async def list_resources(self):
        return list(self._resources)

    async def read_resource(self, uri):
        return self._read_map.get(str(uri), "")

    async def list_prompts(self):
        return list(self._prompts)

    async def get_prompt(self, name, args):
        return f"{self.name}:{name}:{self._prompt_text}"

    async def close(self):
        self._alive = False


class _Prompt:
    def __init__(self, name, description=""):
        self.name = name
        self.description = description


def _res_manager(behaviors):
    def factory(config):
        return _ResFakeClient(config, **behaviors.get(config.name, {}))
    return MCPManager(client_factory=factory)


def test_register_all_resources_builds_index():
    mgr = _res_manager({
        "s1": {"resources": [_Res("mem://a", "A"), _Res("mem://b", "B")],
               "read_map": {"mem://a": "content-A"}},
        "s2": {"resources": [_Res("doc://c", "C")]},
    })
    mgr.load_configs([_Cfg(name="s1", command="x"), _Cfg(name="s2", command="y")])
    listing = asyncio.run(mgr.register_all_resources())
    uris = {row[1] for row in listing}
    assert uris == {"mem://a", "mem://b", "doc://c"}
    # 路由读取到正确 server
    assert asyncio.run(mgr.read_resource("mem://a")) == "content-A"


def test_register_all_resources_partial_failure():
    mgr = _res_manager({
        "bad": {"connect_error": RuntimeError("boom")},
        "good": {"resources": [_Res("mem://x", "X")]},
    })
    mgr.load_configs([_Cfg(name="bad", command="x"), _Cfg(name="good", command="y")])
    listing = asyncio.run(mgr.register_all_resources())
    assert {row[1] for row in listing} == {"mem://x"}


def test_read_resource_unknown_uri_raises():
    mgr = _res_manager({})
    mgr.load_configs([])
    with pytest.raises(KeyError):
        asyncio.run(mgr.read_resource("mem://nope"))


def test_list_all_prompts_and_get_prompt():
    mgr = _res_manager({
        "s1": {"prompts": [_Prompt("greet"), _Prompt("bye")], "prompt_text": "hi"},
    })
    mgr.load_configs([_Cfg(name="s1", command="x")])
    prompts = asyncio.run(mgr.list_all_prompts())
    assert ("s1", "greet", "") in prompts
    assert asyncio.run(mgr.get_prompt("s1", "greet", {})) == "s1:greet:hi"


# --- ch16 T8: ReadMcpResource 工具 ------------------------------------------

from aixcode.tools.read_mcp_resource import ReadMcpResource  # noqa: E402


class _RMRManager:
    def __init__(self, mapping):
        self._m = mapping

    async def read_resource(self, uri):
        if uri not in self._m:
            raise KeyError(uri)
        return self._m[uri]


def test_read_mcp_resource_returns_text():
    tool = ReadMcpResource(_RMRManager({"mem://a": "hello resource"}))
    res = asyncio.run(tool.execute(tool.params_model(uri="mem://a")))
    assert not res.is_error
    assert "hello resource" in res.output


def test_read_mcp_resource_unknown_is_error():
    tool = ReadMcpResource(_RMRManager({}))
    res = asyncio.run(tool.execute(tool.params_model(uri="mem://nope")))
    assert res.is_error


def test_read_mcp_resource_meta():
    assert ReadMcpResource.name == "ReadMcpResource"
    assert ReadMcpResource.should_defer is True
    assert ReadMcpResource.category == "read"
