"""LLM 客户端：统一 Provider 抽象、流式事件、错误分层与 OpenAI 兼容实现。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from aixcode.config import ProviderConfig
from aixcode.tools.base import (
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


# --- 错误分层 ---------------------------------------------------------------

class LLMError(Exception):
    """所有 LLM 通信错误的统一基类。上层只需 except 这一个。"""


class AuthenticationError(LLMError):
    """认证失败（api_key 缺失或无效）。"""


class RateLimitError(LLMError):
    """触发限流。"""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NetworkError(LLMError):
    """网络连接错误。"""


# --- 客户端抽象 -------------------------------------------------------------

class LLMClient(ABC):
    """统一的 Provider 接口。新增后端只需实现本类并在工厂登记。"""

    @abstractmethod
    def stream(
        self,
        conversation,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """把会话历史、工具列表与系统提示发出去，逐事件 yield StreamEvent。"""
        raise NotImplementedError


# --- OpenAI 兼容实现（承载 Deepseek）---------------------------------------

class OpenAIClient(LLMClient):
    """基于 OpenAI 兼容 chat/completions 协议，承载 Deepseek。"""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.api_key:
            raise AuthenticationError("缺少 api_key，请检查 config.yaml")
        self._model = config.model
        self._client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    async def stream(
        self,
        conversation,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        try:
            messages = conversation.serialize()
            if system:
                messages = [{"role": "system", "content": system}, *messages]
            kwargs: dict[str, Any] = dict(
                model=self._model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            if tools:
                kwargs["tools"] = tools
            chunks = await self._client.chat.completions.create(**kwargs)

            input_tokens = 0
            output_tokens = 0
            cache_hit_tokens = 0
            # index -> {"id", "name", "args"} 累积流式工具调用碎片
            tool_acc: dict[int, dict[str, str]] = {}
            async for chunk in chunks:
                if chunk.usage is not None:
                    input_tokens = chunk.usage.prompt_tokens
                    output_tokens = chunk.usage.completion_tokens
                    cache_hit_tokens = getattr(
                        chunk.usage, "prompt_cache_hit_tokens", 0
                    ) or 0
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield ThinkingDelta(reasoning)
                if delta.content:
                    yield TextDelta(delta.content)

                for tc in delta.tool_calls or []:
                    acc = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        acc["id"] = tc.id
                        acc["name"] = tc.function.name or ""
                        yield ToolCallStart(acc["id"], acc["name"])
                    fragment = tc.function.arguments if tc.function else None
                    if fragment:
                        acc["args"] += fragment
                        yield ToolCallDelta(acc["id"], fragment)

                if choice.finish_reason == "tool_calls":
                    for acc in tool_acc.values():
                        try:
                            args = json.loads(acc["args"]) if acc["args"] else {}
                        except json.JSONDecodeError:
                            # 模型给的参数 JSON 非法/截断：兜底空 dict，
                            # 交给下游参数校验回灌结构化错误让模型重试，绝不崩溃
                            args = {}
                        yield ToolCallComplete(acc["id"], acc["name"], args)
                    tool_acc.clear()

            yield StreamEnd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_hit_tokens=cache_hit_tokens,
            )
        except openai.AuthenticationError as e:
            raise AuthenticationError(f"认证失败: {e}") from e
        except openai.RateLimitError as e:
            retry = e.response.headers.get("retry-after")
            raise RateLimitError(
                f"触发限流: {e}",
                retry_after=float(retry) if retry else None,
            ) from e
        except openai.APIConnectionError as e:
            raise NetworkError(f"网络连接错误: {e}") from e
        except openai.APIStatusError as e:
            raise LLMError(f"API 错误 ({e.status_code}): {e}") from e


def create_client(config: ProviderConfig) -> LLMClient:
    """按 protocol 路由到具体客户端实现。"""
    if config.protocol == "openai":
        return OpenAIClient(config)
    raise ValueError(f"Unknown protocol: {config.protocol}")
