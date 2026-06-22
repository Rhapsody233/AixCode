"""共享任务清单：单文件 tasks.json 实现，团队全员读同一份。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SharedTask:
    """一条共享任务。

    status 四档：pending | in_progress | completed | blocked。
    blocks/blocked_by 存任务 id，依赖推断交给 Lead LLM 从列表文本读出。
    """

    id: int
    title: str
    description: str = ""
    status: str = "pending"
    assignee: str = ""
    blocks: list = field(default_factory=list)
    blocked_by: list = field(default_factory=list)
    created_by: str = ""


class SharedTaskStore:
    """基于单文件 tasks.json 的共享任务存储，结构 {"next_id", "tasks": [...]}。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._tasks: list[SharedTask] = []
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._next_id = data.get("next_id", 1)
        self._tasks = [SharedTask(**t) for t in data.get("tasks", [])]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"next_id": self._next_id, "tasks": [asdict(t) for t in self._tasks]}
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def init_empty(self) -> None:
        """清空 + 重置 next_id + 落盘。"""
        self._tasks = []
        self._next_id = 1
        self._save()

    def create(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        blocks: list | None = None,
        blocked_by: list | None = None,
        created_by: str = "",
    ) -> SharedTask:
        """自增 id 新建任务并落盘。"""
        task = SharedTask(
            id=self._next_id,
            title=title,
            description=description,
            status="pending",
            assignee=assignee,
            blocks=list(blocks or []),
            blocked_by=list(blocked_by or []),
            created_by=created_by,
        )
        self._next_id += 1
        self._tasks.append(task)
        self._save()
        return task

    def get(self, task_id: int) -> SharedTask | None:
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    def list_tasks(
        self, status: str | None = None, assignee: str | None = None
    ) -> list[SharedTask]:
        out = list(self._tasks)
        if status:
            out = [t for t in out if t.status == status]
        if assignee:
            out = [t for t in out if t.assignee == assignee]
        return out

    def update(self, task_id: int, **fields) -> SharedTask | None:
        """部分字段更新；add_blocks/add_blocked_by 去重追加。"""
        task = self.get(task_id)
        if task is None:
            return None
        add_blocks = fields.pop("add_blocks", None)
        add_blocked_by = fields.pop("add_blocked_by", None)
        for key, value in fields.items():
            if value is not None and value != "" and hasattr(task, key):
                setattr(task, key, value)
        for b in add_blocks or []:
            if b not in task.blocks:
                task.blocks.append(b)
        for b in add_blocked_by or []:
            if b not in task.blocked_by:
                task.blocked_by.append(b)
        self._save()
        return task
