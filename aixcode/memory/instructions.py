"""项目指令文件：三层优先级加载 AIXCODE.md + `@include` 模块化递归展开。"""

from __future__ import annotations

from pathlib import Path

MAX_INCLUDE_DEPTH = 5
INCLUDE_PREFIX = "@include "

# 三层优先级（高 → 低）：项目根 / 项目 .aixcode / 用户级
_LAYER_PATHS = (
    "AIXCODE.md",
    ".aixcode/AIXCODE.md",
)


def process_includes(
    content: str, base_dir, project_root, depth: int = 0
) -> str:
    """递归展开 `@include <path>` 行；越界/缺文件落注释，超深度返回原文。"""
    if depth >= MAX_INCLUDE_DEPTH:
        return content
    base_dir = Path(base_dir)
    root = Path(project_root).resolve()
    out: list[str] = []
    for line in content.splitlines():
        if not line.startswith(INCLUDE_PREFIX):
            out.append(line)
            continue
        rel = line[len(INCLUDE_PREFIX):].strip()
        abs_path = (base_dir / rel).resolve()
        try:
            abs_path.relative_to(root)
        except ValueError:
            out.append("<!-- @include blocked: path outside project -->")
            continue
        if not abs_path.is_file():
            out.append("<!-- @include skipped: file not found -->")
            continue
        sub = abs_path.read_text(encoding="utf-8")
        out.append(process_includes(sub, abs_path.parent, root, depth + 1))
    return "\n".join(out)


def load_instructions(project_root: str) -> str:
    """三层优先级拼装 AIXCODE.md（各自跑 @include 展开），`\\n---\\n` 拼接；无文件返回空。"""
    root = Path(project_root)
    layers = [root / rel for rel in _LAYER_PATHS]
    layers.append(Path.home() / ".aixcode/AIXCODE.md")
    parts: list[str] = []
    for path in layers:
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            parts.append(process_includes(content, path.parent, root))
    return "\n---\n".join(parts)
