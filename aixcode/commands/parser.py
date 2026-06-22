"""Slash 输入解析 + 命令名补全（纯函数，无副作用）。"""

from __future__ import annotations

from aixcode.commands.registry import CommandRegistry


def parse_command(text: str) -> tuple[str, str, bool]:
    """把一行输入解析成 (name, args, is_command)。

    - 非 `/` 前缀（含空串 / 纯空白）→ ("", "", False)
    - 只有 `/` → ("", "", True)
    - `/Foo bar baz` → ("foo", "bar baz", True)（name 小写、首个空白切分）

    永不抛异常。
    """
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return ("", "", False)
    body = stripped[1:]
    parts = body.split(None, 1)
    if not parts:
        return ("", "", True)
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return (name, args, True)


def complete(registry: CommandRegistry, prefix: str) -> list[str]:
    """按 prefix（形如 `/h`）前缀补全命令名与别名。

    剥前导 `/`，遍历所有非 hidden 命令的 name + aliases 前缀匹配，
    返回字典序、去重、带前导 `/` 的列表。
    """
    needle = prefix[1:] if prefix.startswith("/") else prefix
    matches: set[str] = set()
    for cmd in registry.list_commands():
        if cmd.hidden:
            continue
        for token in (cmd.name, *cmd.aliases):
            if token.startswith(needle):
                matches.add("/" + token)
    return sorted(matches)
