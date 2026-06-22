"""自动记忆：每 N 轮调 LLM 把对话里的偏好/反馈/项目/参考四类写进 memories.md。"""

from __future__ import annotations

from pathlib import Path

from aixcode.conversation import ConversationManager, Message
from aixcode.tools.base import TextDelta

USER_MEMORIES_RELPATH = ".aixcode/memories.md"
PROJECT_MEMORIES_RELPATH = ".aixcode/memories.md"

_USER_LEVEL_HEADERS = {"用户偏好", "纠正反馈"}
_PROJECT_LEVEL_HEADERS = {"项目知识", "参考资料"}
_PLACEHOLDERS = {"", "...", "…", "无", "暂无", "N/A", "n/a"}

MEMORY_EXTRACTION_PROMPT = """\
你是一个记忆提取助手。请阅读「当前 memories.md」与「最近对话」，输出一份**完整的**
更新后的 memories.md（覆盖式重写）。按以下四类分级组织，每类用 `### ` 标题：

### 用户偏好
（用户的编码/沟通偏好，跨项目通用）

### 纠正反馈
（用户对你的纠正、明确表达的「不要这样做」）

### 项目知识
（本项目的技术栈、约定、结构等事实）

### 参考资料
（用户提供的链接、文档、外部资源）

规则：
- 每条用 `- ` 开头，简洁一句话。
- 相同含义的条目**不要重复添加**。
- 某分类没有值得记忆的内容时，该分类下**不要写任何条目，不要写占位符**（如「无」「...」）。
- 只输出 memories.md 正文，**不要调用任何工具**，不要解释。
"""


def _is_placeholder(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("- "):
        stripped = stripped[2:].strip()
    return stripped in _PLACEHOLDERS


class MemoryManager:
    """项目级 + 用户级双路 memories.md 的读写与 LLM 提取。"""

    def __init__(self, project_root: str) -> None:
        self._user_path = Path.home() / USER_MEMORIES_RELPATH
        self._project_path = Path(project_root) / PROJECT_MEMORIES_RELPATH
        self._last_extraction_msg_count = 0

    @property
    def user_path(self) -> Path:
        return self._user_path

    @property
    def project_path(self) -> Path:
        return self._project_path

    def load(self) -> str:
        parts: list[str] = []
        for path in (self._user_path, self._project_path):
            if path.is_file():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
        return "\n\n".join(parts)

    async def extract(self, client, conversation: ConversationManager) -> None:
        """从增量对话跑一次 LLM 提取，把四类记忆分流写两路 memories.md。异常静默。"""
        recent = conversation.history[self._last_extraction_msg_count:]
        if not recent:
            return
        lines = []
        for msg in recent:
            if msg.role == "user":
                lines.append(f"用户: {msg.content}")
            elif msg.role == "assistant" and msg.content:
                lines.append(f"助手: {msg.content}")
        dialogue = "\n".join(lines)
        current = self.load() or "（空）"
        prompt = (
            f"## 当前 memories.md\n{current}\n\n## 最近对话\n{dialogue}"
        )
        extract_conv = ConversationManager()
        extract_conv.history = [Message(role="user", content=prompt)]
        try:
            text = ""
            async for ev in client.stream(extract_conv, system=MEMORY_EXTRACTION_PROMPT):
                if isinstance(ev, TextDelta):
                    text += ev.text
        except Exception:  # noqa: BLE001 提取是 best-effort
            return
        self._last_extraction_msg_count = len(conversation.history)
        self._write_memories(text)

    def _assign_section(
        self, header: str, lines: list[str], user_sections: list[str], project_sections: list[str]
    ) -> None:
        real = [
            ln for ln in lines if ln.strip().startswith("- ") and not _is_placeholder(ln)
        ]
        if not real:
            return
        block = f"### {header}\n" + "\n".join(ln.strip() for ln in real)
        if any(k in header for k in _USER_LEVEL_HEADERS):
            user_sections.append(block)
        elif any(k in header for k in _PROJECT_LEVEL_HEADERS):
            project_sections.append(block)

    def _write_memories(self, content: str) -> None:
        user_sections: list[str] = []
        project_sections: list[str] = []
        header: str | None = None
        buf: list[str] = []
        for line in content.splitlines():
            if line.startswith("### "):
                if header is not None:
                    self._assign_section(header, buf, user_sections, project_sections)
                header = line[4:].strip()
                buf = []
            elif header is not None:
                buf.append(line)
        if header is not None:
            self._assign_section(header, buf, user_sections, project_sections)
        self._flush(self._user_path, user_sections)
        self._flush(self._project_path, project_sections)

    @staticmethod
    def _flush(path: Path, sections: list[str]) -> None:
        if not sections:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n".join(sections).strip() + "\n", encoding="utf-8")

    def clear(self) -> None:
        for path in (self._user_path, self._project_path):
            if path.exists():
                path.write_text("", encoding="utf-8")

    def get_display_text(self) -> str:
        parts: list[str] = []
        for label, path in (("用户级", self._user_path), ("项目级", self._project_path)):
            if path.is_file():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"[{label}] {path}\n{content}")
        if not parts:
            return "当前没有任何自动记忆。"
        return "\n\n".join(parts)
