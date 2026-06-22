"""Skill 解析：SkillDef 数据结构 + frontmatter 解析 + 参数替换。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]*$")
_VALID_MODES = {"inline", "fork"}
_VALID_CONTEXTS = {"full", "recent", "none"}


class SkillParseError(Exception):
    """frontmatter 缺失 / 格式错误 / 元信息校验失败。"""


@dataclass
class SkillDef:
    """一个 Skill 的解析结果。"""

    name: str
    description: str
    prompt_body: str
    allowed_tools: list[str] = field(default_factory=list)
    mode: str = "inline"
    model: str = ""
    context: str = "full"
    source_path: str | None = None
    is_directory: bool = False


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """切分 `---\\n<yaml>\\n---\\n<body>`，返回 (meta dict, body)。"""
    if not raw.startswith("---"):
        raise SkillParseError("缺少起始 frontmatter（应以 '---' 开头）")
    # 去掉首行 '---' 后找闭合 '---'
    rest = raw[3:].lstrip("\n")
    parts = rest.split("\n---", 1)
    if len(parts) != 2:
        raise SkillParseError("frontmatter 未闭合（缺少结束 '---'）")
    yaml_part, body = parts
    try:
        meta = yaml.safe_load(yaml_part)
    except yaml.YAMLError as e:
        raise SkillParseError(f"frontmatter YAML 解析失败：{e}") from e
    if not isinstance(meta, dict):
        raise SkillParseError("frontmatter 必须是键值映射")
    return meta, body.lstrip("\n")


def _validate_meta(meta: dict) -> None:
    name = meta.get("name")
    if not name or not _NAME_RE.match(str(name)):
        raise SkillParseError(f"name 非法（需匹配 {_NAME_RE.pattern}）：{name!r}")
    if not meta.get("description"):
        raise SkillParseError("description 不能为空")
    mode = meta.get("mode", "inline")
    if mode not in _VALID_MODES:
        raise SkillParseError(f"mode 非法（{_VALID_MODES}）：{mode!r}")
    context = meta.get("context", "full")
    if context not in _VALID_CONTEXTS:
        raise SkillParseError(f"context 非法（{_VALID_CONTEXTS}）：{context!r}")


def parse_skill_file(path: str, is_directory: bool = False) -> SkillDef:
    """读盘并组装 SkillDef；任何读/解析/校验失败抛 SkillParseError。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise SkillParseError(f"无法读取 skill 文件 {path}：{e}") from e
    meta, body = parse_frontmatter(raw)
    _validate_meta(meta)
    return SkillDef(
        name=str(meta["name"]),
        description=str(meta["description"]),
        prompt_body=body,
        allowed_tools=list(meta.get("allowedTools", meta.get("allowed_tools", []))),
        mode=meta.get("mode", "inline"),
        model=str(meta.get("model", "")),
        context=meta.get("context", "full"),
        source_path=path,
        is_directory=is_directory,
    )


def substitute_arguments(prompt_body: str, args: str) -> str:
    """把 `$ARGUMENTS` 全部替换为 args；无占位符原样返回。"""
    return prompt_body.replace("$ARGUMENTS", args)
