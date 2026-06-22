"""/trace —— 查看父子 Agent 调用树（LOCAL）。"""

from __future__ import annotations

from aixcode.commands.registry import Command, CommandContext, CommandType

_NO_MANAGER = "调用树追踪不可用（trace_manager 未装配）。"


def _render_tree(tmgr, trace_id: str) -> str:
    nodes = tmgr.get_tree(trace_id)
    if not nodes:
        return f"没有该调用树：{trace_id}"
    by_parent: dict = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    lines = [f"调用树 {trace_id}："]

    def walk(parent_id, depth):
        for n in by_parent.get(parent_id, []):
            indent = "  " * depth
            lines.append(
                f"{indent}- {n.agent_type} [{n.status}] "
                f"in={n.input_tokens} out={n.output_tokens}"
            )
            walk(n.agent_id, depth + 1)

    # 根：parent_id 不在本树内的节点
    ids = {n.agent_id for n in nodes}
    for n in nodes:
        if n.parent_id not in ids:
            walk(n.parent_id, 1)
            break

    in_tok, out_tok = tmgr.get_total_tokens(trace_id)
    lines.append(f"合计 token：in={in_tok} out={out_tok}")
    return "\n".join(lines)


async def handle_trace(ctx: CommandContext) -> None:
    tmgr = ctx.config.get("trace_manager")
    if tmgr is None:
        ctx.ui.add_system_message(_NO_MANAGER)
        return

    trace_id = ctx.args.strip()
    if trace_id:
        ctx.ui.add_system_message(_render_tree(tmgr, trace_id))
        return

    traces = tmgr.list_traces()
    if not traces:
        ctx.ui.add_system_message("当前没有调用记录。")
        return
    lines = ["最近调用树（用 /trace <id> 看详情）："]
    for tid in traces:
        in_tok, out_tok = tmgr.get_total_tokens(tid)
        count = len(tmgr.get_tree(tid))
        lines.append(f"- {tid}｜{count} 节点｜in={in_tok} out={out_tok}")
    ctx.ui.add_system_message("\n".join(lines))


TRACE_COMMAND = Command(
    name="trace",
    description="查看父子 Agent 调用树与 token 汇总",
    handler=handle_trace,
    type=CommandType.LOCAL,
    usage="用法：/trace [trace_id]",
)
