"""Agent 定义解析：AgentDef 数据结构 + frontmatter 解析 + 校验。"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

VALID_MODELS = {"inherit", "deepseek-chat", "deepseek-pro", ""}
VALID_PERMISSION_MODES = {"", "strict", "default", "accept", "bypass"}


class AgentParseError(Exception):
    """frontmatter 缺失 / 格式错误 / 元信息校验失败。"""


@dataclass
class AgentDef:
    """一个子 Agent 类型的定义（Markdown frontmatter + body）。"""

    agent_type: str
    when_to_use: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 50
    permission_mode: str = "default"
    background: bool = False
    isolation: str | None = None
    file_path: str | None = None
    source: str = "builtin"


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """切分 `---\\n<yaml>\\n---\\n<body>`，返回 (meta dict, body)。"""
    if not raw.startswith("---"):
        raise AgentParseError("缺少起始 frontmatter（应以 '---' 开头）")
    rest = raw[3:].lstrip("\n")
    parts = rest.split("\n---", 1)
    if len(parts) != 2:
        raise AgentParseError("frontmatter 未闭合（缺少结束 '---'）")
    yaml_part, body = parts
    try:
        meta = yaml.safe_load(yaml_part)
    except yaml.YAMLError as e:
        raise AgentParseError(f"frontmatter YAML 解析失败：{e}") from e
    if not isinstance(meta, dict):
        raise AgentParseError("frontmatter 必须是键值映射")
    return meta, body.lstrip("\n")


def parse_agent_file(path: str, source: str = "builtin") -> AgentDef:
    """读盘并组装 AgentDef；任何读/解析/校验失败抛 AgentParseError。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise AgentParseError(f"无法读取 agent 文件 {path}：{e}") from e
    meta, body = parse_frontmatter(raw)

    name = meta.get("name")
    if not name:
        raise AgentParseError(f"缺少 name：{path}")
    description = meta.get("description")
    if not description:
        raise AgentParseError(f"缺少 description：{path}")

    model = str(meta.get("model", "inherit")) if meta.get("model") is not None else "inherit"
    if model not in VALID_MODELS:
        raise AgentParseError(f"model 非法（{VALID_MODELS}）：{model!r}")

    permission_mode = str(meta.get("permissionMode", "default"))
    if permission_mode not in VALID_PERMISSION_MODES:
        raise AgentParseError(
            f"permissionMode 非法（{VALID_PERMISSION_MODES}）：{permission_mode!r}"
        )

    max_turns = meta.get("maxTurns", 50)
    if not isinstance(max_turns, int) or max_turns <= 0:
        raise AgentParseError(f"maxTurns 必须是正整数：{max_turns!r}")

    return AgentDef(
        agent_type=str(name),
        when_to_use=str(description),
        system_prompt=body,
        tools=list(meta.get("tools", []) or []),
        disallowed_tools=list(meta.get("disallowedTools", []) or []),
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        background=bool(meta.get("background", False)),
        isolation=meta.get("isolation") or None,
        file_path=path,
        source=source,
    )
