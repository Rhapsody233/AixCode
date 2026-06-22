"""两层上下文管理 + 压缩后恢复。

Layer 1（廉价救火）：tool result 写盘 + 字节稳定替换，命中 Deepseek 自动前缀缓存。
Layer 2（花钱兜底）：整段 LLM 摘要 + 熔断。
恢复（files-only）：摘要后补回最近读过的文件 / 可用工具 / 提示。
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from aixcode.conversation import ConversationManager, Message

# --- Layer 1 常量 -----------------------------------------------------------

SINGLE_RESULT_CHAR_LIMIT = 5_000
AGGREGATE_CHAR_LIMIT = 20_000
PREVIEW_CHARS = 2_000
KEEP_RECENT_TURNS = 10
OLD_RESULT_SNIP_CHARS = 2_000
SNIPPED_TAG = "<snipped>"
PERSISTED_TAG = "<persisted-output>"

# --- Layer 2 常量 -----------------------------------------------------------

SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_SAFETY_MARGIN = 13_000
MANUAL_COMPACT_SAFETY_MARGIN = 3_000
DEFAULT_CONTEXT_WINDOW = 65_536  # deepseek-chat 上下文窗口

# --- session 目录 -----------------------------------------------------------

SESSION_SUBDIR = ".aixcode/session/tool-results"
REPLACEMENT_RECORDS_FILENAME = "replacement_records.jsonl"


def ensure_session_dir(work_dir: str) -> Path:
    """创建并返回 <work_dir>/.aixcode/session/tool-results 目录。"""
    session = Path(work_dir) / SESSION_SUBDIR
    session.mkdir(parents=True, exist_ok=True)
    return session


def cleanup_tool_results(session_dir: Path) -> None:
    """清空 session 目录（rmtree + 重建）。"""
    session_dir = Path(session_dir)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    session_dir.mkdir(parents=True, exist_ok=True)


# --- 状态容器 ---------------------------------------------------------------

@dataclass
class CompactEvent:
    """一次成功压缩；携带压缩前的 token 数。"""

    before_tokens: int


@dataclass
class ContentReplacementState:
    """跨轮持久的「替换决策日志」。replacements.keys() ⊆ seen_ids。"""

    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)


@dataclass
class ContentReplacementRecord:
    """一条替换决策，落 JSONL 用于 transcript / resume。"""

    tool_use_id: str
    replacement: str
    kind: str = "tool-result"


def create_replacement_state() -> ContentReplacementState:
    return ContentReplacementState()


def clone_replacement_state(src: ContentReplacementState) -> ContentReplacementState:
    """浅拷贝出独立 state：子端 mutate 不影响父端（值是字符串与 hash key）。"""
    return ContentReplacementState(
        seen_ids=set(src.seen_ids), replacements=dict(src.replacements)
    )


# --- transcript JSONL -------------------------------------------------------

def _records_path(session_dir: Path) -> Path:
    return Path(session_dir) / REPLACEMENT_RECORDS_FILENAME


def append_replacement_records(
    session_dir: Path, records: list[ContentReplacementRecord]
) -> None:
    """把替换决策追加写到 replacement_records.jsonl，每行一个 JSON。"""
    if not records:
        return
    path = _records_path(session_dir)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(
                json.dumps(
                    {"kind": r.kind, "tool_use_id": r.tool_use_id, "replacement": r.replacement},
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_replacement_records(session_dir: Path) -> list[ContentReplacementRecord]:
    """逐行读 replacement_records.jsonl；缺文件返回空列表。"""
    path = _records_path(session_dir)
    if not Path(path).exists():
        return []
    records: list[ContentReplacementRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append(
                ContentReplacementRecord(
                    tool_use_id=obj["tool_use_id"],
                    replacement=obj["replacement"],
                    kind=obj.get("kind", "tool-result"),
                )
            )
    return records


def reconstruct_replacement_state(
    messages,
    records: list[ContentReplacementRecord],
    inherited_replacements: dict[str, str] | None = None,
) -> ContentReplacementState:
    """从历史消息 + records 重建 state（用于 resume）。

    seen_ids = 所有 role=="tool" 消息的 tool_call_id；只对出现过的 candidate 写
    replacements；inherited 仅对未被 records 覆盖的 candidate gap-fill。
    """
    candidates = {
        msg.tool_call_id
        for msg in messages
        if msg.role == "tool" and msg.tool_call_id
    }
    state = ContentReplacementState(seen_ids=set(candidates))
    for r in records:
        if r.kind == "tool-result" and r.tool_use_id in candidates:
            state.replacements[r.tool_use_id] = r.replacement
    for tid, replacement in (inherited_replacements or {}).items():
        if tid in candidates and tid not in state.replacements:
            state.replacements[tid] = replacement
    return state


# --- Layer 1：写盘 + preview ------------------------------------------------

def persist_tool_result(tool_use_id: str, content: str, session_dir: Path) -> str:
    """把完整 tool result 写到 <session_dir>/<id>.txt；幂等（已存在静默跳过）。"""
    path = Path(session_dir) / f"{tool_use_id}.txt"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return str(path)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return str(path)


def make_persisted_preview(content: str, file_path: str) -> str:
    """byte-stable preview 字符串：一旦写入 state.replacements 即逐字节复读，勿改格式。"""
    kb = max(1, len(content) // 1024)
    return (
        f"{PERSISTED_TAG}\n"
        f"输出太大（{kb}KB），完整内容已保存到：\n"
        f"{file_path}\n\n"
        f"预览（前 2KB）：\n"
        f"{content[:PREVIEW_CHARS]}\n"
        f"</persisted-output>"
    )


# --- Layer 1：陈旧裁剪 ------------------------------------------------------

def _count_turns(history: list[Message]) -> int:
    """assistant 且不带 tool_calls 计作一轮。"""
    return sum(
        1 for msg in history if msg.role == "assistant" and not msg.tool_calls
    )


def _is_tagged(content: str) -> bool:
    return content.startswith(PERSISTED_TAG) or content.startswith(SNIPPED_TAG)


def _snip_one(content: str) -> str:
    return (
        f"{SNIPPED_TAG}\n"
        f"(旧结果已裁剪，原始长度 {len(content)} 字符)\n"
        f"{content[:200]}\n"
        f"… (snipped)"
    )


def _snip_stale_messages(history: list[Message]) -> list[Message]:
    """对超过 KEEP_RECENT_TURNS 轮的陈旧、超长、未标记的 tool result 整体裁剪。"""
    total = _count_turns(history)
    if total <= KEEP_RECENT_TURNS:
        return history
    old_turns = total - KEEP_RECENT_TURNS
    seen = 0
    boundary = len(history)
    for i, msg in enumerate(history):
        if msg.role == "assistant" and not msg.tool_calls:
            seen += 1
            if seen == old_turns:
                boundary = i + 1
                break
    new_history: list[Message] = []
    for i, msg in enumerate(history):
        if (
            i < boundary
            and msg.role == "tool"
            and len(msg.content) > OLD_RESULT_SNIP_CHARS
            and not _is_tagged(msg.content)
        ):
            new_history.append(
                Message(role="tool", content=_snip_one(msg.content), tool_call_id=msg.tool_call_id)
            )
        else:
            new_history.append(msg)
    return new_history


def apply_tool_result_budget(
    conversation: ConversationManager,
    session_dir: Path,
    state: ContentReplacementState,
) -> tuple[ConversationManager, list[ContentReplacementRecord]]:
    """两遍预算控制 + 陈旧裁剪，返回新 ConversationManager（不修改入参）。"""
    history = conversation.history
    records: list[ContentReplacementRecord] = []
    decisions: dict[str, str] = {}  # tool_call_id -> 最终 content
    fresh: list[tuple[str, str]] = []  # 待决策的 (id, content)

    # 阶段 1：四类分类
    for msg in history:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        tid = msg.tool_call_id
        content = msg.content
        if tid in state.replacements:
            decisions[tid] = state.replacements[tid]  # 字节相同复读
        elif tid in state.seen_ids:
            decisions[tid] = content  # 冻结原文
        elif content.startswith(PERSISTED_TAG):
            state.seen_ids.add(tid)
            state.replacements[tid] = content
            records.append(ContentReplacementRecord(tid, content))
            decisions[tid] = content
        else:
            fresh.append((tid, content))

    # 阶段 2（Pass 1）：单条超限 → 写盘
    remaining: list[tuple[str, str]] = []
    for tid, content in fresh:
        if len(content) > SINGLE_RESULT_CHAR_LIMIT:
            path = persist_tool_result(tid, content, session_dir)
            preview = make_persisted_preview(content, path)
            state.seen_ids.add(tid)
            state.replacements[tid] = preview
            records.append(ContentReplacementRecord(tid, preview))
            decisions[tid] = preview
        else:
            remaining.append((tid, content))

    # 阶段 3（Pass 2）：聚合超限 → 按 content 长度降序挑 fresh 直到压回上限
    total = sum(len(v) for v in decisions.values()) + sum(len(c) for _, c in remaining)
    if total > AGGREGATE_CHAR_LIMIT:
        for tid, content in sorted(remaining, key=lambda x: len(x[1]), reverse=True):
            if total <= AGGREGATE_CHAR_LIMIT:
                break
            path = persist_tool_result(tid, content, session_dir)
            preview = make_persisted_preview(content, path)
            state.seen_ids.add(tid)
            state.replacements[tid] = preview
            records.append(ContentReplacementRecord(tid, preview))
            decisions[tid] = preview
            total -= len(content) - len(preview)
        remaining = [(t, c) for t, c in remaining if t not in decisions]

    # 阶段 4：剩余 fresh 冻结为「不替换」
    for tid, content in remaining:
        state.seen_ids.add(tid)
        decisions[tid] = content

    # 末段：用 decisions 重组新 history，跑陈旧裁剪，产新 ConversationManager
    new_history: list[Message] = []
    for msg in history:
        if msg.role == "tool" and msg.tool_call_id in decisions:
            new_history.append(
                Message(
                    role="tool",
                    content=decisions[msg.tool_call_id],
                    tool_call_id=msg.tool_call_id,
                )
            )
        else:
            new_history.append(
                Message(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id,
                )
            )
    new_history = _snip_stale_messages(new_history)
    new_conv = ConversationManager(history=new_history, env_injected=conversation.env_injected)
    new_conv.last_input_tokens = getattr(conversation, "last_input_tokens", 0)
    return new_conv, records


# --- Layer 2：阈值 ----------------------------------------------------------

def compute_compact_threshold(context_window: int, manual: bool = False) -> int:
    """触发阈值 = 窗口 - 摘要输出预留 - 安全余量（手动余量更小）。"""
    margin = MANUAL_COMPACT_SAFETY_MARGIN if manual else AUTO_COMPACT_SAFETY_MARGIN
    return context_window - SUMMARY_OUTPUT_RESERVE - margin


def should_auto_compact(last_input_tokens: int, context_window: int) -> bool:
    return last_input_tokens >= compute_compact_threshold(context_window)


# --- Layer 2：摘要 prompt 与 helpers ---------------------------------------

SUMMARY_PROMPT = """\
你是一个对话压缩器。请把下面这段对话浓缩成一份结构化摘要，供后续继续工作。

**重要：在生成摘要的整个过程中，禁止调用任何工具。** 你只输出文本。

请先在 <analysis> 标签里写一段分析草稿（梳理脉络，用完即弃，不会保留），
再在 <summary> 标签里按以下九节输出正式摘要：

1. 主要请求：用户最初要做什么。
2. 关键概念：涉及的技术、库、约定。
3. 文件与代码段：改动过/读过的文件路径与关键片段。
4. 错误与修复：遇到的报错与如何解决。
5. 解决过程：已完成的主要步骤。
6. 用户原话：保留用户的关键原始措辞，不要改写。
7. 待办：还没做的事。
8. 当前工作：此刻正在做什么。
9. 下一步：接下来该做什么。

**再次强调：禁止调用工具，只输出 <analysis> 与 <summary> 两段文本。**
"""

COMPACT_BOUNDARY_MESSAGE = (
    "（以上为压缩后的会话摘要。如需文件或代码的精确细节，请用 ReadFile 重新读取，"
    "不要根据摘要猜测不存在的内容。）"
)


def extract_summary(llm_output: str) -> str:
    """剥掉 <analysis> 草稿，取 <summary> 内部；找不到完整标签对则返回原文整体。"""
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start != -1 and end != -1 and end > start:
        return llm_output[start + len("<summary>"):end].strip()
    return llm_output.strip()


def build_compact_messages(summary: str, attachment: str = "") -> list[Message]:
    """构造替换历史的两条消息：[摘要(+恢复块)] user + 边界提示 assistant。"""
    body = f"[摘要]\n{summary}"
    if attachment:
        body = f"{body}\n\n---\n\n{attachment}"
    return [
        Message(role="user", content=body),
        Message(role="assistant", content=COMPACT_BOUNDARY_MESSAGE),
    ]


def _group_messages_by_turn(messages: list[Message]) -> list[list[Message]]:
    """按 assistant(无 tool_calls) 收尾切轮。"""
    turns: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages:
        current.append(msg)
        if msg.role == "assistant" and not msg.tool_calls:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


@dataclass
class CompactCircuitBreaker:
    """连续失败 max_failures 次后熔断，停止自动触发避免死循环。"""

    max_failures: int = 3
    consecutive_failures: int = field(init=False, default=0)

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def is_open(self) -> bool:
        return self.consecutive_failures >= self.max_failures


# --- 压缩后恢复（files-only）-----------------------------------------------

RECOVERY_FILE_LIMIT = 5
RECOVERY_TOKENS_PER_FILE = 5_000
_RECOVERY_CHARS_PER_TOKEN = 3.5


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: float


class RecoveryState:
    """跨轮记录每次 ReadFile 的字节快照；线程安全（并发工具执行下回写可能交错）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file_read(self, path: str, content: str) -> None:
        if not path:
            return
        with self._lock:
            self._files.pop(path, None)  # 重读则移到末尾（视为最新）
            self._files[path] = FileReadRecord(path, content, time.time())

    def snapshot_files(self, limit: int) -> list[FileReadRecord]:
        with self._lock:
            recs = list(self._files.values())
        recs.reverse()  # 最近读的在最前
        return recs[:limit]


def _approx_tokens(s: str) -> int:
    return int(len(s) / _RECOVERY_CHARS_PER_TOKEN)


def _truncate_by_tokens(s: str, budget_tokens: int) -> str:
    max_chars = int(budget_tokens * _RECOVERY_CHARS_PER_TOKEN)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n… (内容已截断)"


def _first_line(s: str) -> str:
    for line in s.splitlines():
        if line.strip():
            return line.strip()
    return ""


def build_recovery_attachment(state: RecoveryState | None, tool_schemas) -> str:
    """渲染恢复块：最近读过的文件 / 可用工具 / 提示；空段跳过、全空返回空串。"""
    parts: list[str] = []

    files = state.snapshot_files(RECOVERY_FILE_LIMIT) if state is not None else []
    if files:
        section = ["## 最近读过的文件"]
        for rec in files:
            body = _truncate_by_tokens(rec.content, RECOVERY_TOKENS_PER_FILE)
            section.append(f"### {rec.path}\n```\n{body}\n```")
        parts.append("\n\n".join(section))

    tools = list(tool_schemas or [])
    if tools:
        lines = ["## 可用工具"]
        for schema in tools:
            fn = schema.get("function", schema)
            lines.append(f"- {fn.get('name', '')} — {_first_line(fn.get('description', ''))}")
        parts.append("\n".join(lines))

    if parts:
        parts.append(
            "## 提示\n如需文件或代码的精确细节，请用 ReadFile 重新读取，不要根据摘要猜测不存在的内容。"
        )
    return "\n\n".join(parts)


# --- Layer 2：auto_compact -------------------------------------------------

_PTL_MARKERS = ("too long", "maximum context", "context length", "too many tokens")
_PTL_MAX_RETRIES = 3


def _is_prompt_too_long(err: Exception) -> bool:
    msg = str(err).lower()
    return any(marker in msg for marker in _PTL_MARKERS)


async def auto_compact(
    conversation: ConversationManager,
    client,
    context_window: int,
    session_dir: Path,
    manual: bool = False,
    breaker: CompactCircuitBreaker | None = None,
    recovery: RecoveryState | None = None,
    tool_schemas=None,
):
    """整段 LLM 摘要替换会话。返回 CompactEvent（成功）/ 错误字符串（失败/熔断）/ None（无需压缩）。"""
    from aixcode.tools.base import TextDelta as _TextDelta  # 局部导入避免循环

    before = conversation.last_input_tokens
    threshold = compute_compact_threshold(context_window, manual=manual)
    if not manual and before < threshold:
        return None
    if not conversation.history:
        return None
    if breaker is not None and breaker.is_open():
        return "上下文压缩已熔断（连续失败过多），暂停自动压缩。"

    current = list(conversation.history)
    summary_text: str | None = None
    for _ in range(_PTL_MAX_RETRIES):
        summary_conv = ConversationManager(history=list(current))
        summary_conv.add_user_message("请现在按要求生成摘要（禁止调用任何工具）。")
        try:
            text = ""
            async for ev in client.stream(summary_conv, system=SUMMARY_PROMPT):
                if isinstance(ev, _TextDelta):
                    text += ev.text
            summary_text = text
            break
        except Exception as e:  # noqa: BLE001
            if not _is_prompt_too_long(e):
                if breaker is not None:
                    breaker.record_failure()
                return f"上下文压缩失败：{e}"
            turns = _group_messages_by_turn(current)
            drop = max(1, len(turns) // 5)
            current = [msg for turn in turns[drop:] for msg in turn]
            if not current:
                break

    if summary_text is None:
        if breaker is not None:
            breaker.record_failure()
        return "上下文压缩失败：摘要请求多次超长。"

    summary = extract_summary(summary_text)
    attachment = build_recovery_attachment(recovery, tool_schemas)
    conversation.replace_history(build_compact_messages(summary, attachment))
    cleanup_tool_results(session_dir)
    if breaker is not None:
        breaker.record_success()
    return CompactEvent(before_tokens=before)
