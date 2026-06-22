"""工具注册中心：登记/查找/启停/披露跟踪/schema 导出，以及默认注册工厂。"""

from __future__ import annotations

from typing import Any

from aixcode.tools.base import Tool


class ToolRegistry:
    """集中登记工具。装配阶段写入，运行期只读（非并发安全）。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._enabled: dict[str, bool] = {}
        self._discovered: set[str] = set()

    # --- 基础 ---------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._enabled[tool.name] = True

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    # --- 启停 ---------------------------------------------------------------

    def enable(self, name: str) -> None:
        self._enabled[name] = True

    def disable(self, name: str) -> None:
        self._enabled[name] = False

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    # --- deferred 披露跟踪 --------------------------------------------------

    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered

    def get_deferred_tool_names(self) -> list[str]:
        """should_defer 且未 discovered 且 enabled 的工具名。"""
        return [
            t.name
            for t in self._tools.values()
            if t.should_defer
            and not self.is_discovered(t.name)
            and self.is_enabled(t.name)
        ]

    # --- schema 导出（chat-completions 工具格式）---------------------------

    def _format(self, tool: Tool) -> dict[str, Any]:
        return {"type": "function", "function": tool.get_schema()}

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """默认工具列表：跳过 disabled 与「deferred 且未 discovered」的工具。"""
        schemas = []
        for tool in self._tools.values():
            if not self.is_enabled(tool.name):
                continue
            if tool.should_defer and not self.is_discovered(tool.name):
                continue
            schemas.append(self._format(tool))
        return schemas

    # --- deferred 查询入口 --------------------------------------------------

    def find_deferred_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        """按名精确选 deferred 工具，命中后 mark_discovered。"""
        results = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None or not tool.should_defer or not self.is_enabled(name):
                continue
            self.mark_discovered(name)
            results.append(self._format(tool))
        return results

    def search_deferred(
        self, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]:
        """在 deferred 工具的 name/description 中按词打分，命中后 mark_discovered。"""
        q = query.lower()
        tokens = q.split()
        scored: list[tuple[int, Tool]] = []
        for tool in self._tools.values():
            if not tool.should_defer or not self.is_enabled(tool.name):
                continue
            name_l = tool.name.lower()
            desc_l = tool.description.lower()
            score = 0
            if q in name_l:
                score += 10
            if q in desc_l:
                score += 5
            for tok in tokens:
                if tok in name_l:
                    score += 3
                if tok in desc_l:
                    score += 1
            if score > 0:
                scored.append((score, tool))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = []
        for _, tool in scored[:max_results]:
            self.mark_discovered(tool.name)
            results.append(self._format(tool))
        return results


def create_default_registry() -> ToolRegistry:
    """一次性注册 6 个核心工具，返回可用的 Registry。"""
    from aixcode.tools.bash import Bash
    from aixcode.tools.edit_file import EditFile
    from aixcode.tools.glob import Glob
    from aixcode.tools.grep import Grep
    from aixcode.tools.read_file import ReadFile
    from aixcode.tools.write_file import WriteFile

    registry = ToolRegistry()
    registry.register(ReadFile())
    registry.register(WriteFile())
    registry.register(EditFile())
    registry.register(Bash())
    registry.register(Glob())
    registry.register(Grep())
    return registry
