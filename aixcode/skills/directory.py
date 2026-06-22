"""目录型 Skill：从 tool.json + references/*.py 动态注册专属工具。"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from aixcode.tools import ToolRegistry
from aixcode.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


def parse_tool_json(path: str) -> list[dict]:
    """读 tool.json；单 dict 包装成 list，失败 warning 返回 []。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("解析 tool.json 失败 %s：%s", path, e)
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    log.warning("tool.json 顶层应是 dict 或 list：%s", path)
    return []


def load_tool_implementation(references_dir: str, tool_name: str) -> Callable | None:
    """动态加载 references/<tool_name>.py 里的 execute 函数。"""
    path = Path(references_dir) / f"{tool_name}.py"
    if not path.is_file():
        log.warning("找不到工具实现文件：%s", path)
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"aixcode_skill_tool_{tool_name}", path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:  # 用户脚本任何错误都不应拉崩加载
        log.warning("加载工具实现 %s 失败：%s", path, e)
        return None
    impl = getattr(module, "execute", None)
    if impl is None:
        log.warning("工具实现 %s 缺少 execute 函数", path)
    return impl


class _DynamicParams(BaseModel):
    """动态参数模型：接受任意键（由 tool.json 的 schema 约束实际形状）。"""

    model_config = {"extra": "allow"}


class SkillCustomTool(Tool):
    """包裹 references/*.py 里 execute 函数的动态 Tool。"""

    params_model = _DynamicParams
    category = "read"

    def __init__(
        self, tool_name: str, description: str, schema: dict, impl: Callable
    ) -> None:
        self.name = tool_name
        self.description = description
        self._schema = schema
        self._impl = impl

    def get_schema(self) -> dict[str, Any]:
        parameters = (
            self._schema.get("parameters")
            or self._schema.get("input_schema")
            or {"type": "object", "properties": {}}
        )
        return {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }

    async def execute(self, params: BaseModel) -> ToolResult:
        kwargs = params.model_dump()
        try:
            if inspect.iscoroutinefunction(self._impl):
                result = await self._impl(**kwargs)
            else:
                result = self._impl(**kwargs)
        except Exception as e:
            return ToolResult(f"{self.name} 执行失败：{e}", is_error=True)
        return ToolResult(str(result))


def register_skill_tools(skill_dir: str, registry: ToolRegistry) -> int:
    """读 skill_dir/tool.json，把声明的工具注册进 registry，返回新增数量。"""
    tool_json = Path(skill_dir) / "tool.json"
    if not tool_json.is_file():
        return 0
    references_dir = Path(skill_dir) / "references"
    count = 0
    for schema in parse_tool_json(str(tool_json)):
        tool_name = schema.get("name")
        if not tool_name or registry.get(tool_name) is not None:
            continue
        impl = load_tool_implementation(str(references_dir), tool_name)
        if impl is None:
            continue
        registry.register(
            SkillCustomTool(tool_name, schema.get("description", ""), schema, impl)
        )
        count += 1
    return count
