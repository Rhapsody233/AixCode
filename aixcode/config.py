"""配置加载：从 YAML 读取供应商信息与 MCP server 列表。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

import yaml

_REQUIRED_FIELDS = ("protocol", "model", "base_url", "api_key")

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


@dataclass
class ProviderConfig:
    """一个 LLM 供应商的配置。"""

    protocol: str
    model: str
    base_url: str
    api_key: str


def load_config(path: str = "config.yaml") -> ProviderConfig:
    """从 ``path`` 加载配置文件并构造 ProviderConfig。

    缺文件抛 FileNotFoundError，缺字段抛 ValueError，均带可读提示。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"找不到配置文件 {path!r}，请在项目目录创建 config.yaml"
        )

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    missing = [field for field in _REQUIRED_FIELDS if not data.get(field)]
    if missing:
        raise ValueError(
            f"配置文件 {path!r} 缺少字段: {', '.join(missing)}"
        )

    return ProviderConfig(
        protocol=data["protocol"],
        model=data["model"],
        base_url=data["base_url"],
        api_key=data["api_key"],
    )


# --- MCP server 配置 --------------------------------------------------------

@dataclass
class MCPServerConfig:
    """一个 MCP server 的连接配置（stdio 或 Streamable HTTP）。"""

    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_stdio(self) -> bool:
        return self.command is not None


def resolve_env_vars(mapping: dict[str, str]) -> dict[str, str]:
    """把值里的 ``${VAR}`` 从 os.environ 展开；缺失变量保留原占位符；非字符串原样。"""
    resolved: dict[str, str] = {}
    for key, value in mapping.items():
        if isinstance(value, str):
            resolved[key] = _ENV_VAR_RE.sub(
                lambda m: os.environ.get(m.group(1), m.group(0)), value
            )
        else:
            resolved[key] = value
    return resolved


# stdio 子进程默认带上的宿主机环境键白名单（按平台扩展），不整体复制 os.environ。
_ENV_WHITELIST = ("PATH",)
_WIN_ENV_WHITELIST = ("SYSTEMROOT", "SYSTEMDRIVE", "APPDATA", "USERPROFILE", "TEMP", "TMP")


def build_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造 stdio 子进程环境：白名单宿主机键 + 展开后的 extra，避免泄露 API key。"""
    keys = list(_ENV_WHITELIST)
    if sys.platform == "win32":
        keys += list(_WIN_ENV_WHITELIST)
    env = {k: os.environ[k] for k in keys if k in os.environ}
    env.update(resolve_env_vars(extra or {}))
    return env


def _parse_server(name: str, spec: dict) -> MCPServerConfig:
    spec = spec or {}
    command = spec.get("command")
    url = spec.get("url")
    if command and url:
        raise ValueError(f"MCP server {name!r}：command 与 url 不能同时配置")
    if not command and not url:
        raise ValueError(f"MCP server {name!r}：必须至少配置 command 或 url 其一")
    return MCPServerConfig(
        name=name,
        command=command,
        args=list(spec.get("args") or []),
        url=url,
        headers=dict(spec.get("headers") or {}),
        env=dict(spec.get("env") or {}),
    )


def load_mcp_servers(path: str = "config.yaml") -> list[MCPServerConfig]:
    """从 ``path`` 的 ``mcp_servers`` map 解析出 server 列表；缺该键返回空列表。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    servers = data.get("mcp_servers") or {}
    return [_parse_server(name, spec) for name, spec in servers.items()]


# --- Hook 配置 --------------------------------------------------------------

def load_raw_hooks(path: str = "config.yaml") -> list[dict]:
    """从 ``path`` 的 ``hooks`` 数组取原始 dict 列表；缺文件/缺键返回空列表。

    仅读原始声明，校验交给 ``aixcode.hooks.load_hooks``。
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("hooks") or [])
