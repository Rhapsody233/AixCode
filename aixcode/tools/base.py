"""工具基础：Tool 抽象、统一结果、分类、跳过目录、结果上限与流式事件类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

# 检索类工具统一跳过的目录子树
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}

# 单工具结果回灌上限，超出由编排层截断
MAX_OUTPUT_CHARS = 10000

ToolCategory = Literal["read", "write", "command"]


@dataclass
class ToolResult:
    """所有工具的统一返回形状。"""

    output: str
    is_error: bool = False


class Tool(ABC):
    """所有工具的抽象基类。

    子类用类属性声明元信息，用 Pydantic 模型描述参数，实现 async execute。
    """

    name: ClassVar[str]
    description: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]
    category: ClassVar[ToolCategory]
    should_defer: ClassVar[bool] = False
    is_system_tool: ClassVar[bool] = False
    is_concurrency_safe: ClassVar[bool] = False

    @property
    def is_read_only(self) -> bool:
        return self.category == "read"

    def get_schema(self) -> dict[str, Any]:
        """由参数模型出 JSON Schema，返回 {name, description, parameters}。"""
        parameters = self.params_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }

    @abstractmethod
    async def execute(self, params: BaseModel) -> ToolResult:
        """执行工具，返回统一结果。"""
        raise NotImplementedError


# --- 流式事件（client 与编排层共享）---------------------------------------

@dataclass
class TextDelta:
    """正文增量。"""

    text: str


@dataclass
class ThinkingDelta:
    """思考过程增量。"""

    text: str


@dataclass
class ToolCallStart:
    """一个工具调用开始（首次拿到 id 与名称）。"""

    tool_id: str
    tool_name: str


@dataclass
class ToolCallDelta:
    """工具调用参数的 JSON 碎片。"""

    tool_id: str
    arguments_fragment: str


@dataclass
class ToolCallComplete:
    """一个工具调用解析完成（参数已拼接并解析为 dict）。"""

    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class StreamEnd:
    """流结束，携带 token 用量与缓存命中。"""

    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int = 0


StreamEvent = (
    TextDelta
    | ThinkingDelta
    | ToolCallStart
    | ToolCallDelta
    | ToolCallComplete
    | StreamEnd
)
