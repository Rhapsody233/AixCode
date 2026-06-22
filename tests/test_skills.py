"""ch11 Skill 系统测试。"""

import asyncio

import pytest

from aixcode.skills.parser import (
    SkillDef,
    SkillParseError,
    parse_frontmatter,
    parse_skill_file,
    substitute_arguments,
)

VALID = """---
name: commit
description: Generate a conventional commit
mode: inline
allowedTools: [Bash, ReadFile]
---
Do the commit.
"""


def _write(tmp_path, content, name="s.md"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# --- parse_frontmatter ---

def test_parse_frontmatter_valid():
    meta, body = parse_frontmatter(VALID)
    assert meta["name"] == "commit"
    assert body.strip() == "Do the commit."


def test_parse_frontmatter_missing_open():
    with pytest.raises(SkillParseError):
        parse_frontmatter("no frontmatter here")


def test_parse_frontmatter_unclosed():
    with pytest.raises(SkillParseError):
        parse_frontmatter("---\nname: x\nbody without close")


def test_parse_frontmatter_invalid_yaml():
    with pytest.raises(SkillParseError):
        parse_frontmatter("---\nfoo: [unclosed\n---\nbody")


def test_parse_frontmatter_non_dict():
    with pytest.raises(SkillParseError):
        parse_frontmatter("---\n- a\n- b\n---\nbody")


# --- parse_skill_file ---

def test_parse_skill_file_valid(tmp_path):
    skill = parse_skill_file(_write(tmp_path, VALID))
    assert isinstance(skill, SkillDef)
    assert skill.name == "commit"
    assert skill.mode == "inline"
    assert skill.allowed_tools == ["Bash", "ReadFile"]
    assert skill.context == "full"  # 默认
    assert skill.is_directory is False
    assert "Do the commit" in skill.prompt_body


def test_parse_skill_file_missing_name(tmp_path):
    with pytest.raises(SkillParseError):
        parse_skill_file(_write(tmp_path, "---\ndescription: x\n---\nbody"))


def test_parse_skill_file_missing_description(tmp_path):
    with pytest.raises(SkillParseError):
        parse_skill_file(_write(tmp_path, "---\nname: foo\n---\nbody"))


def test_parse_skill_file_bad_name(tmp_path):
    with pytest.raises(SkillParseError):
        parse_skill_file(_write(tmp_path, "---\nname: Foo_Bar\ndescription: x\n---\nb"))


def test_parse_skill_file_bad_mode(tmp_path):
    with pytest.raises(SkillParseError):
        parse_skill_file(_write(tmp_path, "---\nname: foo\ndescription: x\nmode: weird\n---\nb"))


def test_parse_skill_file_bad_context(tmp_path):
    with pytest.raises(SkillParseError):
        parse_skill_file(_write(tmp_path, "---\nname: foo\ndescription: x\ncontext: bogus\n---\nb"))


def test_parse_skill_file_not_found():
    with pytest.raises(SkillParseError):
        parse_skill_file("/no/such/file.md")


def test_parse_skill_file_fork_with_context(tmp_path):
    skill = parse_skill_file(
        _write(tmp_path, "---\nname: rev\ndescription: review\nmode: fork\ncontext: none\n---\nb")
    )
    assert skill.mode == "fork" and skill.context == "none"


def test_parse_skill_file_is_directory(tmp_path):
    skill = parse_skill_file(_write(tmp_path, VALID, "SKILL.md"), is_directory=True)
    assert skill.is_directory is True


# --- substitute_arguments ---

def test_substitute_with_args():
    assert substitute_arguments("hi $ARGUMENTS done", "world") == "hi world done"


def test_substitute_without_args():
    assert substitute_arguments("hi $ARGUMENTS", "") == "hi "


def test_substitute_no_placeholder():
    assert substitute_arguments("no placeholder", "x") == "no placeholder"


def test_substitute_multiple():
    assert substitute_arguments("$ARGUMENTS and $ARGUMENTS", "a") == "a and a"


# ======================================================================
# T2: SkillLoader 三级搜索 + 热重载
# ======================================================================

from pathlib import Path

from aixcode.skills.loader import SkillLoader


def _skill_text(name, body="body", mode="inline", context=None):
    ctx = f"context: {context}\n" if context else ""
    return f"---\nname: {name}\ndescription: desc-{name}\nmode: {mode}\n{ctx}---\n{body}\n"


def _put(dir_path: Path, name, **kw):
    dir_path.mkdir(parents=True, exist_ok=True)
    f = dir_path / f"{name}.md"
    f.write_text(_skill_text(name, **kw), encoding="utf-8")
    return f


def _loader(tmp_path, user_subdir="user_skills"):
    loader = SkillLoader(str(tmp_path))
    # 把用户级目录重定向到 tmp 下，避免碰真实 ~/.aixcode
    loader._user_dir = tmp_path / user_subdir
    return loader


def test_loader_loads_project_skill(tmp_path):
    _put(tmp_path / ".aixcode" / "skills", "deploy")
    loader = _loader(tmp_path)
    skills = loader.load_all()
    assert "deploy" in skills
    assert skills["deploy"].description == "desc-deploy"


def test_loader_project_overrides_user(tmp_path):
    _put(tmp_path / ".aixcode" / "skills", "dup", body="PROJECT")
    loader = _loader(tmp_path)
    _put(loader._user_dir, "dup", body="USER")
    loader.load_all()
    assert "PROJECT" in loader.get("dup").prompt_body
    assert loader.get_source_label("dup") == "project"


def test_loader_get_catalog(tmp_path):
    _put(tmp_path / ".aixcode" / "skills", "alpha")
    _put(tmp_path / ".aixcode" / "skills", "beta")
    loader = _loader(tmp_path)
    loader.load_all()
    cat = dict(loader.get_catalog())
    assert cat["alpha"] == "desc-alpha" and cat["beta"] == "desc-beta"


def test_loader_get_unknown_returns_none(tmp_path):
    loader = _loader(tmp_path)
    loader.load_all()
    assert loader.get("nope") is None


def test_loader_hot_reload(tmp_path):
    f = _put(tmp_path / ".aixcode" / "skills", "live", body="OLD")
    loader = _loader(tmp_path)
    loader.load_all()
    assert "OLD" in loader.get("live").prompt_body
    f.write_text(_skill_text("live", body="NEW"), encoding="utf-8")
    assert "NEW" in loader.get("live").prompt_body  # 重读生效


def test_loader_hot_reload_fallback(tmp_path):
    f = _put(tmp_path / ".aixcode" / "skills", "fragile", body="GOOD")
    loader = _loader(tmp_path)
    loader.load_all()
    f.write_text("totally broken, no frontmatter", encoding="utf-8")
    # 解析失败回退缓存的旧版本
    assert "GOOD" in loader.get("fragile").prompt_body


def test_loader_directory_skill(tmp_path):
    sk = tmp_path / ".aixcode" / "skills" / "bundle"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(_skill_text("bundle"), encoding="utf-8")
    loader = _loader(tmp_path)
    loader.load_all()
    assert loader.get("bundle").is_directory is True


def test_loader_skips_bad_file(tmp_path):
    d = tmp_path / ".aixcode" / "skills"
    _put(d, "good")
    (d / "bad.md").write_text("no frontmatter at all", encoding="utf-8")
    loader = _loader(tmp_path)
    skills = loader.load_all()
    assert "good" in skills  # 坏文件被跳过、好文件仍加载


def test_loader_reload(tmp_path):
    d = tmp_path / ".aixcode" / "skills"
    _put(d, "one")
    loader = _loader(tmp_path)
    loader.load_all()
    assert "one" in loader.load_all() and "two" not in loader._skills
    _put(d, "two")
    loader.reload()
    assert "two" in dict(loader.get_catalog())


def test_loader_source_label_user(tmp_path):
    loader = _loader(tmp_path)
    _put(loader._user_dir, "ufoo")
    loader.load_all()
    assert loader.get_source_label("ufoo") == "user"


# ======================================================================
# T3: 内置 skill 资源
# ======================================================================

def test_builtins_loaded(tmp_path):
    loader = _loader(tmp_path)  # 无项目/用户 skill
    skills = loader.load_all()
    assert {"commit", "review", "test", "backend-interview"} <= set(skills)
    assert loader.get_source_label("commit") == "builtin"


def test_builtin_modes_and_context():
    loader = SkillLoader(".")
    loader._user_dir = Path("/nonexistent-user-skills-xyz")
    loader.load_all()
    assert loader.get("review").mode == "fork"
    assert loader.get("review").context == "none"
    assert loader.get("commit").mode == "inline"
    assert loader.get("backend-interview").is_directory is True


def test_disk_overrides_builtin(tmp_path):
    _put(tmp_path / ".aixcode" / "skills", "commit", body="MY OWN COMMIT SOP")
    loader = _loader(tmp_path)
    loader.load_all()
    assert "MY OWN COMMIT SOP" in loader.get("commit").prompt_body
    assert loader.get_source_label("commit") == "project"


# ======================================================================
# T4: 系统工具豁免 + 工具白名单过滤
# ======================================================================

from pydantic import BaseModel

from aixcode.skills.executor import (
    SYSTEM_TOOL_NAMES,
    SkillDependencyError,
    filter_tool_registry,
)
from aixcode.tools import create_default_registry
from aixcode.tools.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


class _FakeSystemTool(Tool):
    name = "LoadSkill"
    description = "system tool"
    params_model = _NoParams
    category = "read"
    is_system_tool = True

    async def execute(self, params):
        return ToolResult("ok")


def _reg_with_system():
    reg = create_default_registry()
    reg.register(_FakeSystemTool())
    return reg


def test_filter_empty_allowed_returns_same_object():
    reg = _reg_with_system()
    assert filter_tool_registry(reg, []) is reg


def test_filter_keeps_allowed_plus_system():
    reg = _reg_with_system()
    filtered = filter_tool_registry(reg, ["ReadFile"])
    names = {t.name for t in filtered.list_tools()}
    assert "ReadFile" in names
    assert "LoadSkill" in names  # 系统工具自动透传
    assert "Bash" not in names


def test_filter_missing_tool_raises():
    reg = _reg_with_system()
    with pytest.raises(SkillDependencyError):
        filter_tool_registry(reg, ["NoSuchTool"])


def test_system_tool_names_constant():
    assert "LoadSkill" in SYSTEM_TOOL_NAMES


# ======================================================================
# T5: SkillExecutor.execute_inline
# ======================================================================

from aixcode.skills.executor import SkillExecutor


class _FakeAgent:
    def __init__(self):
        self.activated: dict[str, str] = {}
        self.active_skills: dict[str, str] = {}
        self.catalog = ""

    def activate_skill(self, name, body):
        self.activated[name] = body
        self.active_skills[name] = body

    def clear_active_skills(self):
        self.active_skills = {}

    def set_skill_catalog(self, catalog):
        self.catalog = catalog


def test_execute_inline_activates_rendered_sop():
    agent = _FakeAgent()
    ex = SkillExecutor(agent, client=None, protocol="openai")
    skill = SkillDef(
        name="commit", description="d", prompt_body="do it: $ARGUMENTS", mode="inline"
    )
    asyncio.run(ex.execute_inline(skill, "extra"))
    assert agent.activated["commit"] == "do it: extra"


# ======================================================================
# T6: SkillExecutor.execute_fork
# ======================================================================

from aixcode.conversation import ConversationManager


class _MainAgent:
    def __init__(self, registry):
        self.registry = registry
        self.work_dir = "."
        self.max_iterations = 10
        self.context_window = 8000


def _patch_fork_agent(monkeypatch):
    """把 execute_fork 局部 import 的 Agent 换成假 Agent，捕获 fork_conv。"""
    import aixcode.agent as agent_mod

    class FakeForkAgent:
        last_conv = None

        def __init__(self, client=None, registry=None, **kw):
            self.registry = registry

        async def run(self, conversation):
            FakeForkAgent.last_conv = conversation
            yield agent_mod.StreamText("Hello ")
            yield agent_mod.StreamText("world")
            yield agent_mod.LoopComplete("Hello world")
            yield agent_mod.StreamText("AFTER")  # break 之后不应被收集

    monkeypatch.setattr(agent_mod, "Agent", FakeForkAgent)
    return FakeForkAgent


def test_execute_fork_collects_until_loop_complete(monkeypatch):
    fake = _patch_fork_agent(monkeypatch)
    ex = SkillExecutor(_MainAgent(create_default_registry()), client=object(), protocol="openai")
    skill = SkillDef(
        name="review", description="d", prompt_body="review $ARGUMENTS",
        mode="fork", context="none", allowed_tools=[],
    )
    out = asyncio.run(ex.execute_fork(skill, "the diff", ConversationManager()))
    assert out == "Hello world"  # LoopComplete 后 break，不含 AFTER
    assert fake.last_conv is not None


def test_execute_fork_context_none_isolates(monkeypatch):
    fake = _patch_fork_agent(monkeypatch)
    main_conv = ConversationManager()
    main_conv.add_user_message("主对话历史一条")
    ex = SkillExecutor(_MainAgent(create_default_registry()), client=object(), protocol="openai")
    skill = SkillDef(name="r", description="d", prompt_body="P", mode="fork",
                     context="none", allowed_tools=[])
    asyncio.run(ex.execute_fork(skill, "", main_conv))
    texts = [m.content for m in fake.last_conv.history]
    assert "主对话历史一条" not in texts  # 完全隔离
    assert "P" in texts  # 仅含渲染后的 SOP


def test_execute_fork_context_recent_includes_history(monkeypatch):
    fake = _patch_fork_agent(monkeypatch)
    main_conv = ConversationManager()
    main_conv.add_user_message("最近消息X")
    ex = SkillExecutor(_MainAgent(create_default_registry()), client=object(), protocol="openai")
    skill = SkillDef(name="r", description="d", prompt_body="P", mode="fork",
                     context="recent", allowed_tools=[])
    asyncio.run(ex.execute_fork(skill, "", main_conv))
    texts = [m.content for m in fake.last_conv.history]
    assert "最近消息X" in texts


def test_execute_fork_missing_tool_returns_error(monkeypatch):
    _patch_fork_agent(monkeypatch)
    ex = SkillExecutor(_MainAgent(create_default_registry()), client=object(), protocol="openai")
    skill = SkillDef(name="r", description="d", prompt_body="P", mode="fork",
                     context="none", allowed_tools=["NoSuchTool"])
    out = asyncio.run(ex.execute_fork(skill, "", ConversationManager()))
    assert "NoSuchTool" in out or "无法执行" in out


# ======================================================================
# T7: Agent 集成 active_skills + skill_catalog + 上下文注入
# ======================================================================

def test_build_env_context_without_catalog():
    from aixcode.prompts import build_environment_context

    assert "ZZCATALOG" not in build_environment_context(".")


def test_build_env_context_with_catalog():
    from aixcode.prompts import build_environment_context

    assert "ZZCATALOG" in build_environment_context(".", "ZZCATALOG")


def test_build_active_skills_reminder():
    from aixcode.prompts import build_active_skills_reminder

    out = build_active_skills_reminder({"commit": "SOPBODY"})
    assert "## Active Skills" in out
    assert "### Skill: commit" in out
    assert "SOPBODY" in out


def test_agent_activate_and_clear_skills(tmp_path):
    from aixcode.agent import Agent

    agent = Agent(object(), create_default_registry(), work_dir=str(tmp_path))
    assert agent.active_skills == {}
    agent.activate_skill("commit", "SOP")
    assert agent.active_skills["commit"] == "SOP"
    agent.clear_active_skills()
    assert agent.active_skills == {}


def test_agent_set_skill_catalog(tmp_path):
    from aixcode.agent import Agent

    agent = Agent(object(), create_default_registry(), work_dir=str(tmp_path))
    agent.set_skill_catalog("CATALOG-XYZ")
    assert agent._skill_catalog == "CATALOG-XYZ"


# ======================================================================
# T8: LoadSkill 工具
# ======================================================================

from aixcode.tools.load_skill import LoadSkill, LoadSkillParams


class _Loader:
    def __init__(self, skill=None):
        self._skill = skill

    def get(self, name):
        if self._skill is not None and name == self._skill.name:
            return self._skill
        return None

    def get_catalog(self):
        return [("commit", "do a commit"), ("review", "review code")]


def test_load_skill_attributes():
    t = LoadSkill()
    assert t.name == "LoadSkill"
    assert t.category == "read"
    assert t.is_system_tool is True


def test_load_skill_uninitialized_errors():
    res = asyncio.run(LoadSkill().execute(LoadSkillParams(name="commit")))
    assert res.is_error is True


def test_load_skill_unknown_lists_catalog():
    t = LoadSkill()
    t.set_loader(_Loader())
    t.set_agent(_FakeAgent())
    res = asyncio.run(t.execute(LoadSkillParams(name="nope")))
    assert res.is_error is True
    assert "commit" in res.output


def test_load_skill_activates():
    agent = _FakeAgent()
    skill = SkillDef(name="commit", description="d", prompt_body="SOP-BODY",
                     mode="inline", is_directory=False)
    t = LoadSkill()
    t.set_loader(_Loader(skill))
    t.set_agent(agent)
    res = asyncio.run(t.execute(LoadSkillParams(name="commit")))
    assert res.is_error is False
    assert agent.active_skills["commit"] == "SOP-BODY"
    assert "activated" in res.output.lower()


# ======================================================================
# T9: 目录型 Skill 工具注册
# ======================================================================

from aixcode.skills.directory import parse_tool_json, register_skill_tools
from aixcode.tools import ToolRegistry


def test_parse_tool_json_list(tmp_path):
    p = tmp_path / "tool.json"
    p.write_text('[{"name": "a"}, {"name": "b"}]', encoding="utf-8")
    assert len(parse_tool_json(str(p))) == 2


def test_parse_tool_json_single_dict(tmp_path):
    p = tmp_path / "tool.json"
    p.write_text('{"name": "a"}', encoding="utf-8")
    assert parse_tool_json(str(p)) == [{"name": "a"}]


def test_parse_tool_json_bad(tmp_path):
    p = tmp_path / "tool.json"
    p.write_text("not json at all", encoding="utf-8")
    assert parse_tool_json(str(p)) == []


def _make_skill_dir(tmp_path):
    sk = tmp_path / "sk"
    (sk / "references").mkdir(parents=True)
    (sk / "tool.json").write_text(
        '{"name": "foo", "description": "do foo", '
        '"parameters": {"type": "object", "properties": {}}}',
        encoding="utf-8",
    )
    (sk / "references" / "foo.py").write_text(
        "async def execute(**kwargs):\n    return 'FOO-RAN'\n", encoding="utf-8"
    )
    return sk


def test_register_skill_tools(tmp_path):
    sk = _make_skill_dir(tmp_path)
    reg = ToolRegistry()
    assert register_skill_tools(str(sk), reg) == 1
    tool = reg.get("foo")
    assert tool is not None


def test_register_skill_tools_dynamic_executes(tmp_path):
    sk = _make_skill_dir(tmp_path)
    reg = ToolRegistry()
    register_skill_tools(str(sk), reg)
    tool = reg.get("foo")
    res = asyncio.run(tool.execute(tool.params_model()))
    assert "FOO-RAN" in res.output


def test_register_skill_tools_no_tool_json(tmp_path):
    assert register_skill_tools(str(tmp_path), ToolRegistry()) == 0


def test_register_skill_tools_skips_duplicate(tmp_path):
    sk = _make_skill_dir(tmp_path)
    reg = ToolRegistry()
    register_skill_tools(str(sk), reg)
    assert register_skill_tools(str(sk), reg) == 0  # 同名已存在，跳过


def test_register_backend_interview_parse_resume():
    from importlib.resources import files

    sk_dir = str(files("aixcode.skills.builtins") / "backend-interview")
    reg = ToolRegistry()
    assert register_skill_tools(sk_dir, reg) == 1
    assert reg.get("parse_resume") is not None


# ======================================================================
# T11: 命令集成（/skill + skill_register + /clear 钩）
# ======================================================================

from aixcode.commands.handlers import register_all_commands
from aixcode.commands.handlers.skill import handle_skill
from aixcode.commands.handlers.skill_register import register_skill_commands
from aixcode.commands.registry import CommandContext, CommandRegistry


class _CmdLoader:
    def __init__(self):
        self._skills = {
            "commit": SkillDef("commit", "commit code", "BODY", mode="inline"),
            "review": SkillDef("review", "review code", "BODY", mode="fork", context="none"),
        }
        self.reloaded = False

    def get_catalog(self):
        return [(n, s.description) for n, s in self._skills.items()]

    def get(self, name):
        return self._skills.get(name)

    def get_source_label(self, name):
        return "builtin"

    def reload(self):
        self.reloaded = True
        return self._skills


class _CmdExecutor:
    def __init__(self):
        self.inline = []
        self.fork = []

    async def execute_inline(self, skill, args):
        self.inline.append((skill.name, args))

    async def execute_fork(self, skill, args, conv):
        self.fork.append(skill.name)
        return "FORK RESULT"


class _UI:
    def __init__(self):
        self.msgs = []
        self.sent = []

    def add_system_message(self, t):
        self.msgs.append(t)

    async def send_user_message(self, t):
        self.sent.append(t)

    def set_plan_mode(self, on):
        pass

    def get_token_count(self):
        return 0

    def refresh_status(self):
        pass

    @property
    def last(self):
        return self.msgs[-1] if self.msgs else ""


def _skill_ctx(args, loader=None, executor=None, registry=None, ui=None, agent=None, config=None):
    cfg = {"skill_loader": loader, "skill_executor": executor, "registry": registry}
    if config:
        cfg.update(config)
    return CommandContext(
        args=args, agent=agent, conversation=ConversationManager(), session=None,
        session_manager=None, memory_manager=None, ui=ui or _UI(), config=cfg,
    )


def test_register_skill_commands_adds_with_marker():
    reg = CommandRegistry()
    register_all_commands(reg)
    register_skill_commands(reg, _CmdLoader(), _CmdExecutor())
    assert reg.find("commit") is not None
    assert "[skill]" in reg.find("commit").description


def test_skill_overrides_builtin_review():
    reg = CommandRegistry()
    register_all_commands(reg)
    assert "[skill]" not in reg.find("review").description  # ch10 内置
    register_skill_commands(reg, _CmdLoader(), _CmdExecutor())
    assert "[skill]" in reg.find("review").description  # 被 skill 覆盖


def test_register_skill_commands_idempotent():
    reg = CommandRegistry()
    loader, ex = _CmdLoader(), _CmdExecutor()
    register_skill_commands(reg, loader, ex)
    register_skill_commands(reg, loader, ex)  # 不应抛 ValueError
    assert reg.find("commit") is not None


def test_skill_inline_command_triggers_executor():
    reg = CommandRegistry()
    loader, ex = _CmdLoader(), _CmdExecutor()
    register_skill_commands(reg, loader, ex)
    ui = _UI()
    cmd = reg.find("commit")
    asyncio.run(cmd.handler(_skill_ctx("arg1", loader=loader, executor=ex, ui=ui)))
    assert ex.inline and ex.inline[0][0] == "commit"


def test_skill_command_list():
    ui = _UI()
    asyncio.run(handle_skill(_skill_ctx("list", loader=_CmdLoader(), ui=ui)))
    assert "commit" in ui.last and "review" in ui.last and "builtin" in ui.last


def test_skill_command_info():
    ui = _UI()
    asyncio.run(handle_skill(_skill_ctx("info commit", loader=_CmdLoader(), ui=ui)))
    assert "commit" in ui.last and "inline" in ui.last


def test_skill_command_reload():
    reg = CommandRegistry()
    loader, ex = _CmdLoader(), _CmdExecutor()
    ui = _UI()
    asyncio.run(handle_skill(_skill_ctx("reload", loader=loader, executor=ex, registry=reg, ui=ui)))
    assert loader.reloaded is True
    assert reg.find("commit") is not None


def test_clear_handler_clears_active_skills():
    from aixcode.commands.handlers.clear import handle_clear

    agent = _FakeAgent()
    agent.active_skills = {"x": "y"}
    ui = _UI()
    ctx = _skill_ctx("", ui=ui, agent=agent, config={"clear_chat": lambda: None})
    asyncio.run(handle_clear(ctx))
    assert agent.active_skills == {}


def test_skill_command_in_all_commands():
    from aixcode.commands.handlers import ALL_COMMANDS

    assert any(c.name == "skill" for c in ALL_COMMANDS)


# ======================================================================
# T10: 接入 app
# ======================================================================

def test_app_registers_skill_commands():
    from aixcode.app import AixCodeApp

    loader, ex = _CmdLoader(), _CmdExecutor()
    app = AixCodeApp(
        _FakeAgent(), ConversationManager(), model="x",
        skill_loader=loader, skill_executor=ex,
    )
    assert app.command_registry.find("commit") is not None
    assert "[skill]" in app.command_registry.find("commit").description
    # /review 被 skill 覆盖
    assert "[skill]" in app.command_registry.find("review").description


def test_app_without_skills_backward_compatible():
    from aixcode.app import AixCodeApp

    app = AixCodeApp(_FakeAgent(), ConversationManager(), model="x")
    assert app.command_registry.find("help") is not None
    assert app.command_registry.find("commit") is None
