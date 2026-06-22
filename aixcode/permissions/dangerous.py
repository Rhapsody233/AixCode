"""Layer 1：硬编码危险命令检测 + 只读安全命令白名单。

模式硬编码进本模块，不依赖外部下载或环境变量，避免被绕过（N1）。
"""

from __future__ import annotations

import re

# (编译后的正则, 拦截理由)；用 search 匹配。Unix 8 条 + Windows 3 条。
_DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/|\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+/"), "递归强制删除根目录"),
    (re.compile(r"\bmkfs\."), "格式化文件系统"),
    (re.compile(r"\bdd\b.*\bif=.*\bof=/dev/"), "dd 直写块设备"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/"), "递归放开根目录权限"),
    (re.compile(r":\(\)\s*\{.*\|.*&.*\}"), "fork 炸弹"),
    (re.compile(r"\bcurl\b.*\|\s*sh\b"), "curl 管道执行远端脚本"),
    (re.compile(r"\bwget\b.*\|\s*sh\b"), "wget 管道执行远端脚本"),
    (re.compile(r">\s*/dev/sd"), "覆写块设备"),
    (re.compile(r"\bdel\b.*/(s|q)\b", re.IGNORECASE), "Windows 递归/静默删除"),
    (re.compile(r"\bformat\s", re.IGNORECASE), "Windows 格式化磁盘"),
    (re.compile(r"\brd\s+/s\b", re.IGNORECASE), "Windows 递归删除目录"),
]

# 只读命令前缀白名单（Unix + Windows）。
_SAFE_COMMANDS = {
    "ls", "pwd", "cat", "dir", "type", "echo", "head", "tail", "wc",
    "git status", "git diff", "git log", "git branch", "git show",
    "python --version", "python -V", "pip --version", "node --version",
    "whoami", "hostname", "date",
}

# 命令含这些 shell 元字符则不算安全（可能串联危险操作）。
_UNSAFE_CHARS = ("|", ";", "&&", ">", "$(", "`")


class DangerousCommandDetector:
    """检测明显危险的命令，命中即建议拒绝（任何模式不可绕过）。"""

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        self._patterns = list(_DANGEROUS_PATTERNS)
        for raw, reason in extra_patterns or []:
            self._patterns.append((re.compile(raw), reason))

    def detect(self, command: str) -> tuple[bool, str]:
        for pattern, reason in self._patterns:
            if pattern.search(command):
                return (True, reason)
        return (False, "")


def is_safe_command(command: str) -> bool:
    """命令是否为已知只读安全命令：空串否；含 shell 元字符否；命中前缀为是。"""
    stripped = command.strip()
    if not stripped:
        return False
    if any(ch in stripped for ch in _UNSAFE_CHARS):
        return False
    return any(
        stripped == safe or stripped.startswith(safe + " ")
        for safe in _SAFE_COMMANDS
    )
