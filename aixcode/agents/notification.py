"""后台任务完成通知：格式化 <task-notification> 并注入主对话。"""

from __future__ import annotations

from aixcode.agents.task_manager import BackgroundTask

MAX_NOTIFICATION_RESULT_LENGTH = 5000


def format_task_notification(task: BackgroundTask) -> str:
    """把一个已结束的后台任务包成 <task-notification> 文本。"""
    if task.end_time is not None and task.start_time:
        elapsed = f"{task.end_time - task.start_time:.1f}s"
    else:
        elapsed = "-"

    body = task.result if task.result is not None else (task.error or "")
    if len(body) > MAX_NOTIFICATION_RESULT_LENGTH:
        body = body[:MAX_NOTIFICATION_RESULT_LENGTH] + "\n... (truncated)"

    return (
        "<task-notification>\n"
        f"Task ID: {task.task_id}\n"
        f"Agent: {task.agent_type}\n"
        f"Status: {task.status}\n"
        f"Elapsed: {elapsed}\n"
        f"Tokens: in={task.input_tokens} out={task.output_tokens}\n"
        f"Result:\n{body}\n"
        "</task-notification>"
    )


def inject_task_notifications(
    conversation, completed: list[BackgroundTask]
) -> None:
    """把每个已完成任务包成 user 消息追加到对话。"""
    for task in completed:
        conversation.add_user_message(format_task_notification(task))
