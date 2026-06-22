"""TaskManager：后台子 Agent 生命周期 + 完成通知队列（asyncio 单线程）。"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class BackgroundTask:
    """一个后台子 Agent 任务的状态。"""

    task_id: str
    agent_type: str
    status: str = "running"  # running / completed / failed / cancelled
    result: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    start_time: float = 0.0
    end_time: float | None = None


class TaskManager:
    """登记后台任务、跑 asyncio.Task、完成入队供主循环 poll。"""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}
        self._notify_queue: asyncio.Queue[str] = asyncio.Queue()

    def launch(
        self, coro_factory: Callable[[], Awaitable], agent_type: str
    ) -> str:
        """建后台任务立即返回 task_id；coro 返回 str 或 (text, in_tok, out_tok)。"""
        task_id = uuid.uuid4().hex[:12]
        record = BackgroundTask(
            task_id=task_id, agent_type=agent_type, start_time=time.time()
        )
        self._tasks[task_id] = record
        self._async_tasks[task_id] = asyncio.create_task(
            self._run_background(task_id, coro_factory)
        )
        return task_id

    async def _run_background(
        self, task_id: str, coro_factory: Callable[[], Awaitable]
    ) -> None:
        record = self._tasks[task_id]
        try:
            result = await coro_factory()
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.end_time = time.time()
            await self._notify_queue.put(task_id)
            raise
        except Exception as e:  # noqa: BLE001
            record.status = "failed"
            record.error = str(e)
            record.end_time = time.time()
            await self._notify_queue.put(task_id)
            return
        self._store_result(record, result)
        record.status = "completed"
        record.end_time = time.time()
        await self._notify_queue.put(task_id)

    @staticmethod
    def _store_result(record: BackgroundTask, result) -> None:
        if isinstance(result, tuple) and len(result) == 3:
            text, in_tok, out_tok = result
            record.result = text
            record.input_tokens = in_tok
            record.output_tokens = out_tok
        else:
            record.result = result

    def adopt_running(
        self, async_task: asyncio.Task, agent_type: str
    ) -> str:
        """把一个正在跑的 asyncio.Task 挂为后台任务（中断主回合时用）。"""
        task_id = uuid.uuid4().hex[:12]
        record = BackgroundTask(
            task_id=task_id, agent_type=agent_type, start_time=time.time()
        )
        self._tasks[task_id] = record
        self._async_tasks[task_id] = async_task

        def _on_done(t: asyncio.Task) -> None:
            if record.status != "running":
                return
            if t.cancelled():
                record.status = "cancelled"
            elif t.exception() is not None:
                record.status = "failed"
                record.error = str(t.exception())
            else:
                self._store_result(record, t.result())
                record.status = "completed"
            record.end_time = time.time()
            self._notify_queue.put_nowait(task_id)

        async_task.add_done_callback(_on_done)
        return task_id

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        """取消 running 任务；非 running 或不存在返回 False。"""
        record = self._tasks.get(task_id)
        if record is None or record.status != "running":
            return False
        async_task = self._async_tasks.get(task_id)
        if async_task is None:
            return False
        async_task.cancel()
        return True

    def poll_completed(self) -> list[BackgroundTask]:
        """抽空通知队列，返回已结束（completed/failed/cancelled）的任务。"""
        done: list[BackgroundTask] = []
        while True:
            try:
                task_id = self._notify_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            record = self._tasks.get(task_id)
            if record is not None:
                done.append(record)
        return done
