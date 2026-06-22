"""worktree slug 安全校验与命名映射。

任何 git 命令或路径拼接前先跑 validate_slug，防 LLM 输入触发路径遍历。
"""

from __future__ import annotations

import re

MAX_SLUG_LENGTH = 64
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(slug: str) -> str | None:
    """合法返回 None，非法返回带原因的错误字符串。"""
    if not slug:
        return "worktree 名不能为空"
    if len(slug) > MAX_SLUG_LENGTH:
        return f"worktree 名过长（上限 {MAX_SLUG_LENGTH}）：{len(slug)}"
    for segment in slug.split("/"):
        if not segment:
            return f"worktree 名含空段：{slug!r}"
        if segment in (".", ".."):
            return f"worktree 名含非法段 {segment!r}：{slug!r}"
        if not _SEGMENT_RE.match(segment):
            return f"worktree 名段含非法字符（仅允许 a-zA-Z0-9._-）：{segment!r}"
    return None


def flatten_slug(slug: str) -> str:
    """把 `/` 替换为 `+`，避免嵌套 slug 导致目录或分支 D/F conflict。"""
    return slug.replace("/", "+")
