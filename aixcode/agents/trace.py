"""TraceManager：父子 Agent 调用树追踪 + token 汇总。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


@dataclass
class TraceNode:
    """一次 spawn 的追踪节点。"""

    agent_id: str
    parent_id: str | None
    trace_id: str
    agent_type: str
    status: str = "running"
    input_tokens: int = 0
    output_tokens: int = 0
    start_time: float = 0.0
    end_time: float | None = None


class TraceManager:
    """登记调用树节点；对不存在的 agent_id 操作一律 no-op。"""

    def __init__(self) -> None:
        self._nodes: dict[str, TraceNode] = {}

    def create(
        self,
        agent_type: str,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> TraceNode:
        agent_id = uuid.uuid4().hex[:12]
        node = TraceNode(
            agent_id=agent_id,
            parent_id=parent_id,
            trace_id=trace_id or uuid.uuid4().hex[:12],
            agent_type=agent_type,
            start_time=time.time(),
        )
        self._nodes[agent_id] = node
        return node

    def update(self, agent_id: str, **kw) -> None:
        node = self._nodes.get(agent_id)
        if node is None:
            return
        for key, value in kw.items():
            if hasattr(node, key):
                setattr(node, key, value)

    def complete(self, agent_id: str, status: str) -> None:
        node = self._nodes.get(agent_id)
        if node is None:
            return
        node.status = status
        node.end_time = time.time()

    def get_tree(self, trace_id: str) -> list[TraceNode]:
        return [n for n in self._nodes.values() if n.trace_id == trace_id]

    def get_total_tokens(self, trace_id: str) -> tuple[int, int]:
        nodes = self.get_tree(trace_id)
        return (
            sum(n.input_tokens for n in nodes),
            sum(n.output_tokens for n in nodes),
        )

    def list_traces(self) -> list[str]:
        """去重的 trace_id 列表（最近优先）。"""
        seen: list[str] = []
        for node in self._nodes.values():
            if node.trace_id not in seen:
                seen.append(node.trace_id)
        return seen
