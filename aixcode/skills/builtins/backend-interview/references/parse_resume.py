"""backend-interview skill 专属工具：解析简历文件。

目录型 skill 的工具实现：必须暴露一个 `execute` 函数（可同步可异步）。
"""

from __future__ import annotations

import os


async def execute(file_path: str = "", **kwargs) -> str:
    """读取简历文件并返回粗结构化摘要（关键词命中 + 体量）。"""
    if not file_path:
        return "未提供 file_path，无法解析简历。"
    if not os.path.isfile(file_path):
        return f"文件不存在：{file_path}"
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return f"读取失败：{e}"

    keywords = [
        "Python", "Go", "Java", "Rust", "MySQL", "PostgreSQL", "Redis",
        "Kafka", "Docker", "Kubernetes", "gRPC", "微服务", "高并发", "分布式",
    ]
    hits = [kw for kw in keywords if kw.lower() in text.lower()]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return (
        f"简历摘要：共 {len(lines)} 行有效内容。\n"
        f"命中技术关键词：{', '.join(hits) if hits else '（无明显技术关键词）'}\n"
        "建议据此深挖对应方向的项目经历与系统设计能力。"
    )
