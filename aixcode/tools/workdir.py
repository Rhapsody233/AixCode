"""工具工作目录注入：用 contextvar 让文件工具按 Agent 的 work_dir 解析相对路径。

不存在注入时回退进程 cwd，保持向后兼容。Agent 执行工具前 push、执行后 pop，
配对的 set/reset 在并发批次（各自独立 context）与嵌套子 Agent 下均正确。
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from pathlib import Path

_WORK_DIR: ContextVar[str | None] = ContextVar("aixcode_work_dir", default=None)


def current_work_dir() -> str | None:
    """当前注入的 work_dir；未注入返回 None。"""
    return _WORK_DIR.get()


def push_work_dir(work_dir: str) -> Token:
    """设置当前 work_dir，返回用于恢复的 token。"""
    return _WORK_DIR.set(work_dir)


def pop_work_dir(token: Token) -> None:
    """恢复到 push 之前的 work_dir。"""
    _WORK_DIR.reset(token)


def resolve_path(path: str) -> Path:
    """绝对路径原样返回；相对路径基于当前 work_dir（无则回退进程 cwd）。"""
    p = Path(path)
    if p.is_absolute():
        return p
    base = current_work_dir() or os.getcwd()
    return Path(base) / p
