"""Layer 2：路径沙箱。把写/读限制在 项目根 + 系统临时目录 + extra 之内。

构造时一次性 resolve 各允许根；检查时 resolve(strict=True) 解 symlink，防符号
链接逃逸（N2）。不存在的新文件回退到父目录 resolve 再拼接，支持写前预检。
"""

from __future__ import annotations

import tempfile
from pathlib import Path


class PathSandbox:
    """对任意路径判定是否落在允许根之内。"""

    def __init__(self, project_root: str, extra_allowed: list[str] | None = None) -> None:
        roots = [Path(project_root), Path(tempfile.gettempdir())]
        roots.extend(Path(p) for p in (extra_allowed or []))
        self._project_root = Path(project_root).expanduser().resolve()
        self._allowed_roots = [r.expanduser().resolve() for r in roots]

    def _resolve(self, path: str) -> Path:
        """绝对化并解 symlink；不存在时回退父目录 resolve 再拼接文件名。"""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self._project_root / p
        try:
            return p.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return p.parent.resolve() / p.name

    def check(self, path: str) -> tuple[bool, str]:
        resolved = self._resolve(path)
        for root in self._allowed_roots:
            try:
                resolved.relative_to(root)
                return (True, "")
            except ValueError:
                continue
        return (False, f"路径 {resolved} 超出沙箱范围")
