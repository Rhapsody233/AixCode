"""ch14 Worktree 系统测试。"""

import asyncio

import pytest

from aixcode.worktree.slug import MAX_SLUG_LENGTH, flatten_slug, validate_slug


# --- T1: slug 校验 + 命名映射 ---

def test_max_slug_length():
    assert MAX_SLUG_LENGTH == 64


def test_validate_slug_valid_single():
    assert validate_slug("feature-x") is None


def test_validate_slug_valid_nested():
    assert validate_slug("team/feature_1.2") is None


def test_validate_slug_empty():
    assert validate_slug("") is not None


def test_validate_slug_too_long():
    assert validate_slug("a" * 65) is not None


def test_validate_slug_empty_segment():
    assert validate_slug("a//b") is not None


def test_validate_slug_dot_segment():
    assert validate_slug("a/./b") is not None
    assert validate_slug(".") is not None


def test_validate_slug_dotdot_segment():
    assert validate_slug("a/../b") is not None
    assert validate_slug("..") is not None


def test_validate_slug_illegal_char():
    assert validate_slug("a b") is not None
    assert validate_slug("a$b") is not None


def test_flatten_slug():
    assert flatten_slug("a/b/c") == "a+b+c"
    assert flatten_slug("plain") == "plain"


# --- T2: 数据模型 ---

from datetime import datetime  # noqa: E402

from aixcode.worktree.models import Worktree, WorktreeSession  # noqa: E402


def test_worktree_fields():
    wt = Worktree(name="demo", path="/p", branch="worktree-demo",
                  based_on="HEAD", head_commit="abc")
    assert wt.name == "demo"
    assert wt.path == "/p"
    assert wt.branch == "worktree-demo"
    assert wt.based_on == "HEAD"
    assert wt.head_commit == "abc"
    assert isinstance(wt.created, datetime)


def test_worktree_session_defaults():
    s = WorktreeSession(
        original_cwd="/o", worktree_path="/w", worktree_name="demo",
        original_branch="master", original_head_commit="def",
    )
    assert s.session_id == ""
    assert s.hook_based is False


# --- 测试用 git 仓库 helper ---

import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def _make_git_repo(tmp_path):
    """建一个带初始提交的临时 git 仓库，返回 repo 路径。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _add_worktree(repo, name):
    """在 repo 下加一个 worktree，返回 (path, head_commit)。"""
    wt = repo / ".wt" / name
    wt.parent.mkdir(exist_ok=True)
    _git(["worktree", "add", "-q", "-B", f"worktree-{name}", str(wt), "HEAD"], repo)
    head = _git(["rev-parse", "HEAD"], wt).stdout.strip()
    return wt, head


# --- T3: 变更检测 fail-closed ---

from aixcode.worktree.changes import (  # noqa: E402
    Changes,
    CleanupResult,
    count_worktree_changes,
    has_unpushed_commits,
    has_worktree_changes,
)


def test_changes_clean(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, head = _add_worktree(repo, "c1")
    ch = count_worktree_changes(str(wt), head)
    assert ch == Changes(uncommitted=0, new_commits=0)


def test_changes_uncommitted(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, head = _add_worktree(repo, "c2")
    (wt / "new.txt").write_text("x\n", encoding="utf-8")
    ch = count_worktree_changes(str(wt), head)
    assert ch.uncommitted > 0


def test_changes_new_commits(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, head = _add_worktree(repo, "c3")
    (wt / "f.txt").write_text("y\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-q", "-m", "more"], wt)
    ch = count_worktree_changes(str(wt), head)
    assert ch.new_commits > 0


def test_changes_fail_closed_bad_path():
    ch = count_worktree_changes("/nonexistent/path/xyz", "deadbeef")
    assert ch.uncommitted == 1
    assert ch.new_commits == 1


def test_has_worktree_changes(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, head = _add_worktree(repo, "c4")
    assert has_worktree_changes(str(wt), head) is False
    (wt / "z.txt").write_text("z\n", encoding="utf-8")
    assert has_worktree_changes(str(wt), head) is True


def test_has_unpushed_commits_no_remote(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, _ = _add_worktree(repo, "c5")
    assert has_unpushed_commits(str(wt)) is True


def test_cleanup_result_defaults():
    r = CleanupResult(kept=False)
    assert r.path is None and r.branch is None


# --- T4: integration notice ---

import re  # noqa: E402

from aixcode.worktree.integration import (  # noqa: E402
    WORKTREE_NOTICE_TEMPLATE,
    build_worktree_notice,
    generate_worktree_name,
)


def test_notice_template_markers():
    assert "[WORKTREE CONTEXT]" in WORKTREE_NOTICE_TEMPLATE
    assert "[/WORKTREE CONTEXT]" in WORKTREE_NOTICE_TEMPLATE
    assert "{wt_path}" in WORKTREE_NOTICE_TEMPLATE
    assert "{parent_cwd}" in WORKTREE_NOTICE_TEMPLATE


def test_generate_worktree_name():
    name = generate_worktree_name()
    assert re.match(r"^agent-[0-9a-f]{8}$", name)


def test_build_worktree_notice():
    notice = build_worktree_notice("/parent/cwd", "/wt/path")
    assert "/parent/cwd" in notice
    assert "/wt/path" in notice
    assert "isolated Git Worktree" in notice
    assert "re-read files before editing" in notice
    assert "translate them to your local worktree path" in notice


# --- T5: 会话持久化 ---

from aixcode.worktree.session import (  # noqa: E402
    SESSION_FILENAME,
    load_worktree_session,
    save_worktree_session,
)


def _sample_session():
    return WorktreeSession(
        original_cwd="/o", worktree_path="/w", worktree_name="demo",
        original_branch="master", original_head_commit="abc",
        session_id="s1", hook_based=True,
    )


def test_session_filename():
    assert SESSION_FILENAME == "worktree_session.json"


def test_session_roundtrip(tmp_path):
    save_worktree_session(str(tmp_path), _sample_session())
    loaded = load_worktree_session(str(tmp_path))
    assert loaded == _sample_session()


def test_session_save_none_clears(tmp_path):
    save_worktree_session(str(tmp_path), _sample_session())
    save_worktree_session(str(tmp_path), None)
    assert load_worktree_session(str(tmp_path)) is None


def test_session_missing_file(tmp_path):
    assert load_worktree_session(str(tmp_path / "nope")) is None


def test_session_bad_json(tmp_path):
    (tmp_path / SESSION_FILENAME).write_text("{not json", encoding="utf-8")
    assert load_worktree_session(str(tmp_path)) is None


def test_session_missing_worktree_path(tmp_path):
    import json
    (tmp_path / SESSION_FILENAME).write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert load_worktree_session(str(tmp_path)) is None


def test_session_tolerates_missing_new_fields(tmp_path):
    import json
    data = {
        "original_cwd": "/o", "worktree_path": "/w", "worktree_name": "demo",
        "original_branch": "master", "original_head_commit": "abc",
    }
    (tmp_path / SESSION_FILENAME).write_text(json.dumps(data), encoding="utf-8")
    loaded = load_worktree_session(str(tmp_path))
    assert loaded is not None
    assert loaded.session_id == ""
    assert loaded.hook_based is False


# --- T6: 创建后设置四项 ---

from aixcode.worktree.setup import (  # noqa: E402
    LOCAL_CONFIG_FILES,
    _copy_ignored_files,
    _create_symlinks,
    perform_post_creation_setup,
)


def test_local_config_files():
    assert LOCAL_CONFIG_FILES == ["settings.local.json", ".env"]


def test_setup_copies_local_config(tmp_path):
    repo = _make_git_repo(tmp_path)
    (repo / "settings.local.json").write_text('{"k":1}', encoding="utf-8")
    wt, _ = _add_worktree(repo, "s1")
    perform_post_creation_setup(str(repo), str(wt), [])
    assert (wt / "settings.local.json").exists()


def test_setup_missing_config_ok(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, _ = _add_worktree(repo, "s2")
    # 不应抛
    perform_post_creation_setup(str(repo), str(wt), [])


def test_copy_ignored_files(tmp_path):
    repo = _make_git_repo(tmp_path)
    (repo / ".gitignore").write_text("*.local\n", encoding="utf-8")
    (repo / "secret.local").write_text("s\n", encoding="utf-8")
    (repo / ".worktreeinclude").write_text("*.local\n# comment\n\n", encoding="utf-8")
    wt, _ = _add_worktree(repo, "s3")
    _copy_ignored_files(str(repo), str(wt))
    assert (wt / "secret.local").exists()


def test_create_symlinks_no_throw(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    # 源不存在 + Windows 软链接权限问题都不应抛
    _create_symlinks([str(tmp_path / "nonexistent")], str(wt))


# --- T7: WorktreeManager 主类 + 快速恢复 ---

from aixcode.worktree.manager import WorktreeError, WorktreeManager  # noqa: E402


def test_manager_default_worktree_dir(tmp_path):
    m = WorktreeManager(repo_root=str(tmp_path))
    assert m.worktree_dir == str(Path(tmp_path) / ".aixcode" / "worktrees")
    assert m.current_session is None
    assert m.active == {}


def test_read_head_sha_real_worktree(tmp_path):
    repo = _make_git_repo(tmp_path)
    wt, head = _add_worktree(repo, "h1")
    sha = WorktreeManager.read_worktree_head_sha(str(wt))
    assert sha == head
    assert len(sha) == 40


def test_read_head_sha_bad_path(tmp_path):
    assert WorktreeManager.read_worktree_head_sha(str(tmp_path / "nope")) is None


def test_manager_cache_callback(tmp_path):
    calls = []
    cache = {"a": 1}
    m = WorktreeManager(repo_root=str(tmp_path), file_cache=cache)
    m.add_cache_clear_callback(lambda: calls.append(1))
    m._clear_all_caches()
    assert calls == [1]
    assert cache == {}  # file_cache 被清空


def test_manager_run_git(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    result = m._run_git(["rev-parse", "HEAD"])
    assert result.returncode == 0
    assert len(result.stdout.strip()) == 40


def test_worktree_error_is_exception():
    assert issubclass(WorktreeError, Exception)


# --- T8: create/enter/exit/auto_cleanup/restore ---

from aixcode.worktree.changes import describe_changes  # noqa: E402


def test_describe_changes_singular_plural():
    assert describe_changes(Changes(1, 0)) == "1 uncommitted file"
    assert describe_changes(Changes(2, 0)) == "2 uncommitted files"
    assert describe_changes(Changes(0, 1)) == "1 commit"
    assert describe_changes(Changes(0, 3)) == "3 commits"
    assert "and" in describe_changes(Changes(1, 1)) or "," in describe_changes(Changes(1, 1))


def test_manager_create(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    assert wt.name == "demo"
    assert wt.branch == "worktree-demo"
    assert Path(wt.path).is_dir()
    assert "demo" in m.active
    assert len(wt.head_commit) == 40


def test_manager_create_nested_flatten(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("team/x"))
    assert wt.branch == "worktree-team+x"
    assert Path(wt.path).name == "team+x"


def test_manager_create_invalid_slug(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    with pytest.raises(WorktreeError):
        asyncio.run(m.create("bad name"))


def test_manager_create_fast_restore(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt1 = asyncio.run(m.create("demo"))
    # 模拟"已存在"：清掉 active 让重名检查通过，但目录还在 → 走快速恢复
    m.active.clear()
    wt2 = asyncio.run(m.create("demo"))
    assert wt2.path == wt1.path
    assert wt2.head_commit == wt1.head_commit


def test_manager_enter_writes_session(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(m.create("demo"))
    cleared = []
    m.add_cache_clear_callback(lambda: cleared.append(1))
    session = asyncio.run(m.enter("demo"))
    assert session.worktree_name == "demo"
    assert m.current_session is session
    assert cleared == [1]
    assert load_worktree_session(m._aixcode_dir) is not None


def test_manager_exit_keep(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    asyncio.run(m.enter("demo"))
    asyncio.run(m.exit("demo", "keep"))
    assert Path(wt.path).is_dir()  # 保留
    assert m.current_session is None
    assert load_worktree_session(m._aixcode_dir) is None


def test_manager_exit_remove_clean(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    asyncio.run(m.enter("demo"))
    asyncio.run(m.exit("demo", "remove"))
    assert not Path(wt.path).exists()
    assert "demo" not in m.active


def test_manager_exit_remove_dirty_rejected(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    (Path(wt.path) / "dirty.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(WorktreeError):
        asyncio.run(m.exit("demo", "remove"))
    assert Path(wt.path).is_dir()  # 未删


def test_manager_exit_remove_discard(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    (Path(wt.path) / "dirty.txt").write_text("x\n", encoding="utf-8")
    asyncio.run(m.exit("demo", "remove", discard_changes=True))
    assert not Path(wt.path).exists()


def test_manager_auto_cleanup_clean(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    result = asyncio.run(m.auto_cleanup("demo", wt.head_commit))
    assert result.kept is False
    assert not Path(wt.path).exists()


def test_manager_auto_cleanup_dirty(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("demo"))
    (Path(wt.path) / "dirty.txt").write_text("x\n", encoding="utf-8")
    result = asyncio.run(m.auto_cleanup("demo", wt.head_commit))
    assert result.kept is True
    assert result.path == wt.path
    assert result.branch == wt.branch
    assert Path(wt.path).is_dir()


def test_manager_restore_hit(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(m.create("demo"))
    asyncio.run(m.enter("demo"))
    # 新建一个 manager 模拟重启
    m2 = WorktreeManager(repo_root=str(repo))
    restored = m2.restore_session()
    assert restored is not None
    assert restored.worktree_name == "demo"
    assert "demo" in m2.active
    assert m2.current_session is restored


def test_manager_restore_miss_clears(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    # 手写一个指向不存在 worktree 的 session
    save_worktree_session(m._aixcode_dir, WorktreeSession(
        original_cwd="/o", worktree_path=str(tmp_path / "gone"),
        worktree_name="gone", original_branch="master", original_head_commit="x",
    ))
    assert m.restore_session() is None
    assert load_worktree_session(m._aixcode_dir) is None  # 脏文件被清


def test_manager_list_and_current(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(m.create("demo"))
    assert len(m.list_worktrees()) == 1
    assert m.get_current_session() is None


# --- T9: 后台过期清理 ---

import os  # noqa: E402
import time  # noqa: E402

from aixcode.worktree.cleanup import (  # noqa: E402
    EPHEMERAL_PATTERNS,
    _is_ephemeral,
    cleanup_stale_worktrees,
    start_stale_cleanup_task,
)


def _push_to_new_remote(repo, tmp_path):
    """给 repo 加一个 bare remote 并 push，让 HEAD commit 算"已推送"。"""
    remote = tmp_path / "remote.git"
    _git(["init", "--bare", "-q", str(remote)], tmp_path)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "HEAD:refs/heads/master"], repo)


def _expire(path):
    old = time.time() - 100 * 3600
    os.utime(path, (old, old))


def test_is_ephemeral_matches():
    assert _is_ephemeral("agent-aabbccdd")
    assert _is_ephemeral("wf_aabbccdd-abc-1")
    assert _is_ephemeral("wf-3")
    assert _is_ephemeral("bridge-abc_def")
    assert _is_ephemeral("job-myslug-aabbccdd")


def test_is_ephemeral_rejects_user_names():
    assert not _is_ephemeral("my-feature")
    assert not _is_ephemeral("demo")


def test_ephemeral_patterns_count():
    assert len(EPHEMERAL_PATTERNS) == 5


def test_cleanup_removes_clean_expired(tmp_path):
    repo = _make_git_repo(tmp_path)
    _push_to_new_remote(repo, tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("agent-aabbccdd"))
    _expire(wt.path)
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 1
    assert not Path(wt.path).exists()


def test_cleanup_skips_non_ephemeral(tmp_path):
    repo = _make_git_repo(tmp_path)
    _push_to_new_remote(repo, tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("my-feature"))
    _expire(wt.path)
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 0
    assert Path(wt.path).is_dir()


def test_cleanup_skips_recent(tmp_path):
    repo = _make_git_repo(tmp_path)
    _push_to_new_remote(repo, tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("agent-aabbccdd"))
    # 不设过期 mtime → 未过期 → 跳过
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 0
    assert Path(wt.path).is_dir()


def test_cleanup_skips_current_session(tmp_path):
    repo = _make_git_repo(tmp_path)
    _push_to_new_remote(repo, tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("agent-aabbccdd"))
    asyncio.run(m.enter("agent-aabbccdd"))
    _expire(wt.path)
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 0  # 当前 session 占用，保留
    assert Path(wt.path).is_dir()


def test_cleanup_skips_unpushed(tmp_path):
    repo = _make_git_repo(tmp_path)
    # 不加 remote → has_unpushed_commits True → L3 fail-closed 保留
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("agent-aabbccdd"))
    _expire(wt.path)
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 0
    assert Path(wt.path).is_dir()


def test_cleanup_skips_dirty(tmp_path):
    repo = _make_git_repo(tmp_path)
    _push_to_new_remote(repo, tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    wt = asyncio.run(m.create("agent-aabbccdd"))
    (Path(wt.path) / "dirty.txt").write_text("x\n", encoding="utf-8")
    _expire(wt.path)
    n = asyncio.run(cleanup_stale_worktrees(m, cutoff_hours=24))
    assert n == 0
    assert Path(wt.path).is_dir()


def test_start_stale_cleanup_task_runs_and_cancels(tmp_path):
    repo = _make_git_repo(tmp_path)

    async def scenario():
        m = WorktreeManager(repo_root=str(repo))
        task = asyncio.create_task(start_stale_cleanup_task(m, 0.01, 24))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())  # 不应抛


# --- T10: 包级导出 ---

def test_package_exports():
    import aixcode.worktree as wt
    for name in [
        "Changes", "CleanupResult", "count_worktree_changes", "has_worktree_changes",
        "cleanup_stale_worktrees", "start_stale_cleanup_task",
        "WorktreeError", "WorktreeManager", "Worktree", "WorktreeSession",
        "load_worktree_session", "save_worktree_session",
        "flatten_slug", "validate_slug",
    ]:
        assert hasattr(wt, name), name
    assert len(wt.__all__) == 14
    assert wt.__all__ == sorted(wt.__all__)


# --- T11: EnterWorktreeTool ---

from aixcode.tools.enter_worktree import EnterWorktreeParams, EnterWorktreeTool  # noqa: E402


def test_enter_tool_attrs():
    assert EnterWorktreeTool.name == "EnterWorktree"
    assert EnterWorktreeTool.category == "command"
    assert EnterWorktreeTool.is_concurrency_safe is False
    assert EnterWorktreeTool.should_defer is False


def test_enter_tool_params_optional_name():
    p = EnterWorktreeParams()
    assert p.name is None


def test_enter_tool_creates(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    tool = EnterWorktreeTool(m)
    res = asyncio.run(tool.execute(EnterWorktreeParams(name="demo")))
    assert not res.is_error
    assert "worktree-demo" in res.output
    assert m.get_current_session() is not None


def test_enter_tool_already_in_session(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    tool = EnterWorktreeTool(m)
    asyncio.run(tool.execute(EnterWorktreeParams(name="demo")))
    res = asyncio.run(tool.execute(EnterWorktreeParams(name="demo2")))
    assert res.is_error
    assert "Already in a worktree session" in res.output


def test_enter_tool_invalid_name(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    tool = EnterWorktreeTool(m)
    res = asyncio.run(tool.execute(EnterWorktreeParams(name="bad name")))
    assert res.is_error


def test_enter_tool_default_name(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    tool = EnterWorktreeTool(m)
    res = asyncio.run(tool.execute(EnterWorktreeParams()))
    assert not res.is_error
    assert "wt-" in res.output


# --- T12: ExitWorktreeTool ---

from aixcode.tools.exit_worktree import ExitWorktreeParams, ExitWorktreeTool  # noqa: E402


def test_exit_tool_attrs():
    assert ExitWorktreeTool.name == "ExitWorktree"
    assert ExitWorktreeTool.category == "command"
    assert ExitWorktreeTool.should_defer is False


def test_exit_tool_no_session(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    tool = ExitWorktreeTool(m)
    res = asyncio.run(tool.execute(ExitWorktreeParams(action="remove")))
    assert res.is_error
    assert "No-op" in res.output


def test_exit_tool_invalid_action(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    EnterWorktreeTool(m)
    asyncio.run(EnterWorktreeTool(m).execute(EnterWorktreeParams(name="demo")))
    tool = ExitWorktreeTool(m)
    res = asyncio.run(tool.execute(ExitWorktreeParams(action="bogus")))
    assert res.is_error


def test_exit_tool_keep(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(EnterWorktreeTool(m).execute(EnterWorktreeParams(name="demo")))
    wt = m.active["demo"]
    res = asyncio.run(ExitWorktreeTool(m).execute(ExitWorktreeParams(action="keep")))
    assert not res.is_error
    assert Path(wt.path).is_dir()
    assert m.get_current_session() is None


def test_exit_tool_remove_dirty_blocked_singular(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(EnterWorktreeTool(m).execute(EnterWorktreeParams(name="demo")))
    wt = m.active["demo"]
    (Path(wt.path) / "one.txt").write_text("x\n", encoding="utf-8")
    res = asyncio.run(ExitWorktreeTool(m).execute(ExitWorktreeParams(action="remove")))
    assert res.is_error
    assert "1 uncommitted file" in res.output
    assert Path(wt.path).is_dir()


def test_exit_tool_remove_dirty_blocked_plural(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(EnterWorktreeTool(m).execute(EnterWorktreeParams(name="demo")))
    wt = m.active["demo"]
    (Path(wt.path) / "a.txt").write_text("x\n", encoding="utf-8")
    (Path(wt.path) / "b.txt").write_text("y\n", encoding="utf-8")
    res = asyncio.run(ExitWorktreeTool(m).execute(ExitWorktreeParams(action="remove")))
    assert res.is_error
    assert "2 uncommitted files" in res.output


def test_exit_tool_remove_discard(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(EnterWorktreeTool(m).execute(EnterWorktreeParams(name="demo")))
    wt = m.active["demo"]
    (Path(wt.path) / "a.txt").write_text("x\n", encoding="utf-8")
    res = asyncio.run(
        ExitWorktreeTool(m).execute(
            ExitWorktreeParams(action="remove", discard_changes=True)
        )
    )
    assert not res.is_error
    assert not Path(wt.path).exists()


# --- T13: /worktree 命令 ---

from aixcode.commands.handlers.worktree import create_worktree_command  # noqa: E402
from aixcode.commands.registry import CommandContext, CommandType  # noqa: E402


class _WtUI:
    def __init__(self):
        self.messages = []

    def add_system_message(self, text):
        self.messages.append(text)

    async def send_user_message(self, text):
        pass

    def set_plan_mode(self, on):
        pass

    def get_token_count(self):
        return 0

    def refresh_status(self):
        pass


class _WtAgent:
    work_dir = "."


def _wt_ctx(args):
    ui = _WtUI()
    ctx = CommandContext(
        args=args, agent=_WtAgent(), conversation=None, session=None,
        session_manager=None, memory_manager=None, ui=ui, config={},
    )
    return ctx, ui


def test_worktree_command_meta(tmp_path):
    m = WorktreeManager(repo_root=str(tmp_path))
    cmd = create_worktree_command(m)
    assert cmd.name == "worktree"
    assert "wt" in cmd.aliases
    assert cmd.type == CommandType.LOCAL


def test_worktree_command_unknown_sub(tmp_path):
    m = WorktreeManager(repo_root=str(tmp_path))
    cmd = create_worktree_command(m)
    ctx, ui = _wt_ctx("bogus")
    asyncio.run(cmd.handler(ctx))
    assert any("未知子命令" in msg for msg in ui.messages)


def test_worktree_command_create(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    cmd = create_worktree_command(m)
    ctx, ui = _wt_ctx("create demo")
    asyncio.run(cmd.handler(ctx))
    assert "demo" in m.active
    assert ctx.agent.work_dir == m.active["demo"].path


def test_worktree_command_list(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    asyncio.run(m.create("demo"))
    cmd = create_worktree_command(m)
    ctx, ui = _wt_ctx("list")
    asyncio.run(cmd.handler(ctx))
    assert any("demo" in msg for msg in ui.messages)


def test_worktree_command_status(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    cmd = create_worktree_command(m)
    asyncio.run(cmd.handler(_wt_ctx("create demo")[0]))
    ctx, ui = _wt_ctx("status")
    asyncio.run(cmd.handler(ctx))
    assert any("demo" in msg for msg in ui.messages)


def test_worktree_command_exit_remove_discard(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    cmd = create_worktree_command(m)
    asyncio.run(cmd.handler(_wt_ctx("create demo")[0]))
    wt_path = m.active["demo"].path
    ctx, ui = _wt_ctx("exit --remove --discard")
    asyncio.run(cmd.handler(ctx))
    assert not Path(wt_path).exists()


# --- T14: AgentTool worktree 隔离接入 ---

import aixcode.tools.agent_tool as agent_tool_mod  # noqa: E402
from aixcode.agents.parser import AgentDef, parse_agent_file  # noqa: E402
from aixcode.agents.task_manager import TaskManager  # noqa: E402
from aixcode.agents.trace import TraceManager  # noqa: E402
from aixcode.config import ProviderConfig  # noqa: E402
from aixcode.tools import create_default_registry  # noqa: E402
from aixcode.tools.agent_tool import AgentTool, AgentToolParams  # noqa: E402


def _provider():
    return ProviderConfig(protocol="openai", model="deepseek-chat",
                          base_url="https://x", api_key="sk")


class _WtParent:
    def __init__(self, work_dir):
        self.registry = create_default_registry()
        self.client = object()
        self.hook_engine = None
        self.work_dir = work_dir
        self.context_window = 1000
        self.permission_checker = None
        self.active_conversation = None


class _WtLoader:
    def __init__(self, agents):
        self._agents = agents

    def get_catalog(self):
        return [(n, "use") for n in self._agents]

    def get(self, name):
        return self._agents.get(name)


class _StubSub:
    total_input_tokens = 5
    total_output_tokens = 2


def test_parser_reads_isolation(tmp_path):
    f = tmp_path / "w.md"
    f.write_text("---\nname: w\ndescription: d\nisolation: worktree\n---\nbody",
                 encoding="utf-8")
    d = parse_agent_file(str(f))
    assert d.isolation == "worktree"


def test_agentdef_isolation_default():
    assert AgentDef("a", "w", "s").isolation is None


def test_agenttoolparams_isolation_default():
    p = AgentToolParams(prompt="p", description="d")
    assert p.isolation is None


def test_execute_with_worktree_no_manager(tmp_path):
    loader = _WtLoader({"w": AgentDef("w", "u", "s", isolation="worktree")})
    tool = AgentTool(loader, TaskManager(), TraceManager(),
                     parent_agent=_WtParent(str(tmp_path)),
                     provider_config=_provider(), worktree_manager=None)

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="w")
        )

    res = asyncio.run(scenario())
    assert res.is_error


def test_execute_with_worktree_clean_cleanup(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    loader = _WtLoader({"w": AgentDef("w", "u", "s", isolation="worktree")})
    tool = AgentTool(loader, TaskManager(), TraceManager(),
                     parent_agent=_WtParent(str(repo)),
                     provider_config=_provider(), worktree_manager=m)
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "WT RESULT"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="w")
        )

    res = asyncio.run(scenario())
    assert not res.is_error
    assert "WT RESULT" in res.output
    assert "[Worktree preserved" not in res.output  # 干净已自动清理
    # worktree 目录已删
    assert not list(Path(m.worktree_dir).glob("agent-*"))


def test_execute_with_worktree_dirty_preserved(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    loader = _WtLoader({"w": AgentDef("w", "u", "s", isolation="worktree")})
    tool = AgentTool(loader, TaskManager(), TraceManager(),
                     parent_agent=_WtParent(str(repo)),
                     provider_config=_provider(), worktree_manager=m)

    created = {}

    def fake_build(definition, registry, client, work_dir):
        created["work_dir"] = work_dir
        return _StubSub()
    monkeypatch.setattr(tool, "_build_sub_agent", fake_build)

    async def fake_rtc(sub, conv):
        # 模拟子 Agent 在 worktree 里留下未提交改动
        (Path(created["work_dir"]) / "changed.txt").write_text("x\n", encoding="utf-8")
        return "DID WORK"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="w")
        )

    res = asyncio.run(scenario())
    assert "DID WORK" in res.output
    assert "[Worktree preserved at" in res.output
    assert "branch worktree-agent-" in res.output


def test_execute_isolation_via_params(tmp_path, monkeypatch):
    # 定义未声明 isolation，但调用时通过 params.isolation 指定
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    loader = _WtLoader({"w": AgentDef("w", "u", "s")})
    tool = AgentTool(loader, TaskManager(), TraceManager(),
                     parent_agent=_WtParent(str(repo)),
                     provider_config=_provider(), worktree_manager=m)
    monkeypatch.setattr(tool, "_build_sub_agent", lambda *a, **k: _StubSub())

    async def fake_rtc(sub, conv):
        return "VIA PARAMS"
    monkeypatch.setattr(agent_tool_mod, "run_to_completion", fake_rtc)

    async def scenario():
        return await tool.execute(
            AgentToolParams(prompt="go", description="d", subagent_type="w",
                            isolation="worktree")
        )

    res = asyncio.run(scenario())
    assert "VIA PARAMS" in res.output


# --- T15: app.py 装配 ---

from aixcode.app import AixCodeApp  # noqa: E402
from aixcode.conversation import ConversationManager  # noqa: E402


def _app_agent():
    from aixcode.context import RecoveryState
    from aixcode.permissions import PermissionMode

    class _A:
        def __init__(self):
            self.permission_mode = PermissionMode.DEFAULT
            self.memory_manager = None
            self.recovery_state = RecoveryState()
            self.instructions_content = ""
            self.work_dir = "."

            class _R:
                def list_tools(self):
                    return []

            self.registry = _R()

        def set_permission_mode(self, m):
            self.permission_mode = m

    return _A()


def test_app_registers_worktree_command(tmp_path):
    m = WorktreeManager(repo_root=str(tmp_path))
    app = AixCodeApp(_app_agent(), ConversationManager(), worktree_manager=m)
    assert app.command_registry.find("worktree") is not None
    assert app.worktree_manager is m
    assert len(m._cache_clear_callbacks) == 1


def test_app_without_worktree_manager():
    app = AixCodeApp(_app_agent(), ConversationManager())
    assert app.command_registry.find("worktree") is None
    assert app.worktree_manager is None


def test_app_cache_callback_resets_recovery(tmp_path):
    m = WorktreeManager(repo_root=str(tmp_path))
    agent = _app_agent()
    old = agent.recovery_state
    AixCodeApp(agent, ConversationManager(), worktree_manager=m)
    m._clear_all_caches()
    assert agent.recovery_state is not old


def test_manager_work_dir_callback(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    seen = []
    m.add_work_dir_callback(lambda p: seen.append(p))
    wt = asyncio.run(m.create("demo"))
    asyncio.run(m.enter("demo"))
    assert seen[-1] == wt.path
    asyncio.run(m.exit("demo", "keep"))
    assert seen[-1] == os.getcwd()  # 切回 original_cwd


def test_app_worktree_switches_agent_work_dir(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))
    agent = _app_agent()
    AixCodeApp(agent, ConversationManager(), worktree_manager=m)
    wt = asyncio.run(m.create("demo"))
    asyncio.run(m.enter("demo"))
    assert agent.work_dir == wt.path
    asyncio.run(m.exit("demo", "keep"))
    assert agent.work_dir == os.getcwd()


def test_app_starts_and_stops_cleanup_task(tmp_path):
    repo = _make_git_repo(tmp_path)
    m = WorktreeManager(repo_root=str(repo))

    async def scenario():
        app = AixCodeApp(_app_agent(), ConversationManager(), worktree_manager=m)
        app._start_worktree_cleanup()
        assert app._stale_cleanup_task is not None
        app._stop_worktree_cleanup()
        await asyncio.sleep(0)
        assert app._stale_cleanup_task.cancelled() or app._stale_cleanup_task.done()

    asyncio.run(scenario())
