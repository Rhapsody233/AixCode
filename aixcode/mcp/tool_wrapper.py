"""把一个 MCP tool 适配成 AixCode 的 Tool：动态参数模型 + 内容块提取。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model

from aixcode.tools.base import Tool, ToolResult

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _json_type_to_python(json_type: str | None) -> type:
    """把 JSON Schema 的 type 映射成 Python 类型；未识别/缺省回退 Any。"""
    return _JSON_TYPE_MAP.get(json_type, Any)


def _build_params_model(name: str, input_schema: dict) -> type[BaseModel]:
    """由 MCP 的 inputSchema 动态生成 pydantic 参数模型。

    required 字段标 ``...``（必填），其余标默认 ``None``（可选）。
    """
    properties = (input_schema or {}).get("properties", {}) or {}
    required = set((input_schema or {}).get("required", []) or [])
    fields: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        py_type = _json_type_to_python((field_schema or {}).get("type"))
        if field_name in required:
            fields[field_name] = (py_type, ...)
        else:
            fields[field_name] = (py_type | None if py_type is not Any else Any, None)
    return create_model(f"{name}Params", **fields)


def _extract_text(content: list) -> str:
    """把 MCP 返回的内容块（TextContent/ImageContent/EmbeddedResource）拼成字符串。"""
    parts: list[str] = []
    for block in content or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", ""))
        elif btype == "image":
            parts.append(f"[image {getattr(block, 'mimeType', '')}]".strip())
        elif btype == "resource":
            resource = getattr(block, "resource", None)
            parts.append(getattr(resource, "text", "") or "[embedded resource]")
        else:
            parts.append(str(block))
    if not parts:
        return "(no output)"
    return "\n".join(parts)


class MCPToolWrapper(Tool):
    """把一个远端 MCP tool 包成 Tool，注册进 ToolRegistry 后 Agent 无感调用。"""

    def __init__(self, manager, server_name: str, tool_def) -> None:
        self.manager = manager
        self.server_name = server_name
        self._tool_def = tool_def
        self._tool_name = tool_def.name
        self.name = f"mcp_{server_name}_{tool_def.name}"
        self.description = tool_def.description or ""
        self.category = "command"
        self.should_defer = True
        self.is_concurrency_safe = False
        self._input_schema = dict(tool_def.inputSchema or {})
        self.params_model = _build_params_model(self.name, self._input_schema)

    def get_schema(self) -> dict[str, Any]:
        """直接返回原始 inputSchema，避免 pydantic 转换破坏 schema 语义。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._input_schema,
        }

    async def execute(self, params: BaseModel) -> ToolResult:
        try:
            client = await self.manager.get_client(self.server_name)
            result = await client.call_tool(
                self._tool_name, params.model_dump(exclude_none=True)
            )
        except Exception as e:  # noqa: BLE001 远端任何异常都包成结构化错误
            return ToolResult(f"Error: MCP 调用失败：{e}", is_error=True)
        return ToolResult(
            _extract_text(result.content), is_error=bool(getattr(result, "isError", False))
        )
