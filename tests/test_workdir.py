"""work_dir contextvar 注入测试（修复工具相对路径基准）。"""

import asyncio
import os
from pathlib import Path

from aixcode.tools.workdir import (
    current_work_dir,
    pop_work_dir,
    push_work_dir,
    resolve_path,
)


def test_resolve_absolute_unchanged(tmp_path):
    p = tmp_path / "a.txt"
    assert resolve_path(str(p)) == Path(str(p))


def test_resolve_relative_falls_back_to_cwd():
    # 无 contextvar 时回退进程 cwd（向后兼容）
    assert resolve_path("a.txt") == Path(os.getcwd()) / "a.txt"


def test_resolve_relative_uses_work_dir(tmp_path):
    token = push_work_dir(str(tmp_path))
    try:
        assert resolve_path("a.txt") == Path(str(tmp_path)) / "a.txt"
        assert current_work_dir() == str(tmp_path)
    finally:
        pop_work_dir(token)


def test_push_pop_restores(tmp_path):
    assert current_work_dir() is None
    t1 = push_work_dir(str(tmp_path))
    sub = tmp_path / "sub"
    t2 = push_work_dir(str(sub))
    assert current_work_dir() == str(sub)
    pop_work_dir(t2)
    assert current_work_dir() == str(tmp_path)
    pop_work_dir(t1)
    assert current_work_dir() is None


# --- 文件工具按 work_dir 解析相对路径 ---

def _under(tmp_path, fn):
    token = push_work_dir(str(tmp_path))
    try:
        return asyncio.run(fn())
    finally:
        pop_work_dir(token)


def test_writefile_uses_work_dir(tmp_path):
    from aixcode.tools.write_file import WriteFile, WriteFileParams

    _under(tmp_path, lambda: WriteFile().execute(
        WriteFileParams(file_path="rel.txt", content="hi")))
    assert (tmp_path / "rel.txt").read_text(encoding="utf-8") == "hi"


def test_readfile_uses_work_dir(tmp_path):
    (tmp_path / "r.txt").write_text("line1\nline2", encoding="utf-8")
    from aixcode.tools.read_file import ReadFile, ReadFileParams

    res = _under(tmp_path, lambda: ReadFile().execute(ReadFileParams(file_path="r.txt")))
    assert "line1" in res.output


def test_editfile_uses_work_dir(tmp_path):
    (tmp_path / "e.txt").write_text("foo", encoding="utf-8")
    from aixcode.tools.edit_file import EditFile, EditFileParams

    _under(tmp_path, lambda: EditFile().execute(
        EditFileParams(file_path="e.txt", old_string="foo", new_string="bar")))
    assert (tmp_path / "e.txt").read_text(encoding="utf-8") == "bar"


def test_glob_uses_work_dir(tmp_path):
    (tmp_path / "x.py").write_text("", encoding="utf-8")
    from aixcode.tools.glob import Glob, GlobParams

    res = _under(tmp_path, lambda: Glob().execute(GlobParams(pattern="*.py")))
    assert "x.py" in res.output


def test_grep_uses_work_dir(tmp_path):
    (tmp_path / "g.txt").write_text("needle here", encoding="utf-8")
    from aixcode.tools.grep import Grep, GrepParams

    res = _under(tmp_path, lambda: Grep().execute(GrepParams(pattern="needle")))
    assert "needle" in res.output


def test_bash_uses_work_dir(tmp_path):
    from aixcode.tools.bash import Bash, BashParams

    # 在 work_dir 下跑 pwd/cd 等价命令：用 python 打印 cwd 最跨平台
    res = _under(tmp_path, lambda: Bash().execute(
        BashParams(command="python -c \"import os;print(os.getcwd())\"")))
    assert str(tmp_path) in res.output


def test_agent_run_tool_injects_work_dir(tmp_path):
    from pydantic import BaseModel

    from aixcode.agent import Agent
    from aixcode.tools import ToolRegistry
    from aixcode.tools.base import Tool, ToolCallComplete, ToolResult

    seen = {}

    class _P(BaseModel):
        pass

    class _Probe(Tool):
        name = "Probe"
        description = "p"
        params_model = _P
        category = "read"

        async def execute(self, params):
            seen["wd"] = current_work_dir()
            return ToolResult("ok")

    reg = ToolRegistry()
    reg.register(_Probe())
    agent = Agent(client=None, registry=reg, work_dir=str(tmp_path))
    tc = ToolCallComplete(tool_id="1", tool_name="Probe", arguments={})
    asyncio.run(agent._run_tool(tc))
    assert seen["wd"] == str(tmp_path)
    # 执行完毕后 contextvar 恢复（无泄漏）
    assert current_work_dir() is None
