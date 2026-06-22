# ch14: Worktree 系统 Tasks（AixCode / Python 版）

> 顺序执行。可测单元一律 **TDD**（先写失败测试→看红→最小实现→转绿），测试统一进 `tests/test_worktree.py`，沿用仓库约定（纯 pytest 函数 + `asyncio.run`，不用测试类、不引 pytest-asyncio）。
> 每完成一个任务跑 `python -m compileall aixcode tests` + `python -m pytest tests/test_worktree.py -q`；接入主流程的任务（T15）做完立刻补端到端验证（T16）。
> 全局背景与已完成章节、AixCode 适配差异见 [spec.md](spec.md) §0。前置：ch01–ch13 已交付（全量 585 passed），项目已 git init（master + 初始提交）。验收后端 `model: deepseek-chat`。

## T1: slug 校验 + 命名映射
- 影响文件: `aixcode/worktree/__init__.py`（新建空壳，T10 补导出）、`aixcode/worktree/slug.py`、`tests/test_worktree.py`（新建）
- 依赖任务: 无
- 完成标准（TDD）: `MAX_SLUG_LENGTH=64`；`validate_slug(slug)` 校验空名/长度 ≤64/按 `/` 切段/每段匹配 `^[a-zA-Z0-9._-]+$`/显式拒绝空段和 `.`·`..` 段，失败返带原因字符串、合法返 `None`；`flatten_slug(s)=s.replace("/","+")`。
- 测试: 合法单段/嵌套；超长；空名；空段(`a//b`)；`.`/`..` 段；非法字符；flatten 替换。

## T2: 数据模型 models
- 影响文件: `aixcode/worktree/models.py`、`tests/test_worktree.py`
- 依赖任务: 无
- 完成标准（TDD）: `@dataclass Worktree` 6 字段 `name/path/branch/based_on/head_commit/created`，`created` 默认 `field(default_factory=datetime.now)`；`@dataclass WorktreeSession` 7 字段 `original_cwd/worktree_path/worktree_name/original_branch/original_head_commit/session_id=""/hook_based=False`。
- 测试: Worktree 默认 created 是 datetime；WorktreeSession 后两字段默认值。

## T3: 变更检测 changes（fail-closed）
- 影响文件: `aixcode/worktree/changes.py`、`tests/test_worktree.py`
- 依赖任务: 无
- 完成标准（TDD）: `GIT_ENV={"GIT_TERMINAL_PROMPT":"0","GIT_ASKPASS":""}`；`_run_git(args, cwd)` 强制 `env={**os.environ,**GIT_ENV}`+`stdin=DEVNULL`+`timeout=30`+`capture_output`+`text`；`@dataclass Changes(uncommitted, new_commits)`；`count_worktree_changes(path, head_commit)` 跑 `git status --porcelain`(非空行计数) + `git rev-list --count <head>..HEAD`，任一 `SubprocessError/OSError/ValueError` 把对应字段置 1（fail-closed）；`has_worktree_changes(path, head_commit)` 任一计数>0 返 True；`@dataclass CleanupResult(kept, path=None, branch=None)`；`has_unpushed_commits(path)` 跑 `git rev-list --max-count=1 HEAD --not --remotes`，输出非空返 True、git 失败返 True。
- 测试（用真实临时 git 仓库 + worktree）: 干净 worktree count=(0,0)；改文件后 uncommitted>0；提交后 new_commits>0；坏路径 fail-closed 置 1；has_worktree_changes 真假；has_unpushed_commits 无 remote 返 True。

## T4: worktree notice integration
- 影响文件: `aixcode/worktree/integration.py`、`tests/test_worktree.py`
- 依赖任务: 无
- 完成标准（TDD）: `WORKTREE_NOTICE_TEMPLATE` 多行串含 `[WORKTREE CONTEXT]`/`[/WORKTREE CONTEXT]` 标记、`{wt_path}`/`{parent_cwd}` 占位、关键句 "running in an isolated Git Worktree"、"translate them to your local worktree path"、"re-read files before editing"；`generate_worktree_name()` 返 `f"agent-{secrets.token_hex(4)}"`（agent- + 8 hex）；`build_worktree_notice(parent_cwd, wt_path)` 用 `.format` 注入两占位。
- 测试: generate 前缀 agent- 且尾 8 hex；build 含两路径与关键句；模板含标记。

## T5: 会话持久化 session
- 影响文件: `aixcode/worktree/session.py`、`tests/test_worktree.py`
- 依赖任务: T2
- 完成标准（TDD）: `SESSION_FILENAME="worktree_session.json"`；`_session_path(aixcode_dir)`；`save_worktree_session(aixcode_dir, session)`：`mkdir(parents=True,exist_ok=True)` → `session is None` 写 `"{}"` → 否则 dump 7 字段；`load_worktree_session(aixcode_dir)`：文件不存在返 `None`，`JSONDecodeError/KeyError` warning 后返 `None`，空 dict 或缺 `worktree_path` 返 `None`，否则构造 `WorktreeSession`，`session_id`/`hook_based` 用 `data.get` 容忍缺失。
- 测试: save 后 load 往返一致；save(None) 写空清空；文件缺失返 None；坏 JSON 返 None；缺 worktree_path 返 None；缺新字段仍能 load。

## T6: 创建后设置四项 setup
- 影响文件: `aixcode/worktree/setup.py`、`tests/test_worktree.py`
- 依赖任务: 无
- 完成标准（TDD）: `LOCAL_CONFIG_FILES=["settings.local.json",".env"]`；`perform_post_creation_setup(repo_root, worktree_path, symlink_directories)` 依序调 A/B/C/D；A `_copy_local_configs` 用 `shutil.copy2`，`OSError` 仅 warning；B `_setup_git_hooks` 优先 `<repo>/.husky` 回退 `<repo>/.git/hooks`，找到目录跑 `git config core.hooksPath <dir>`；C `_create_symlinks(directories, worktree_path)` 跳已存在/源不存在，`OSError` warning；D `_copy_ignored_files` 读 `.worktreeinclude`（跳空行和 `#`）→ `git ls-files --others --ignored --exclude-standard --directory` → `fnmatch.fnmatch` 筛 → 单文件失败 `continue`。
- 测试: 复制存在的 settings.local.json、缺失静默跳过；symlink 创建（用 tmp 目录，Windows 软链接失败也不应抛）；`.worktreeinclude` 命中复制；坏项不中断。

## T7: WorktreeManager 主类 + 快速恢复
- 影响文件: `aixcode/worktree/manager.py`、`tests/test_worktree.py`
- 依赖任务: T1, T3
- 完成标准（TDD）: `GIT_ENV` 同 T3；`class WorktreeError(Exception)`；`WorktreeManager.__init__(repo_root, file_cache=None, symlink_directories=None, worktree_dir=None)` 持有 `repo_root/file_cache/symlink_directories/worktree_dir(默认 <repo>/.aixcode/worktrees)/_aixcode_dir(<repo>/.aixcode)/_lock=asyncio.Lock()/active:dict/current_session=None`；`add_cache_clear_callback(cb)`/`_clear_all_caches`（清 file_cache(若 dict 调 clear) + 跑回调）；`_run_git(args, cwd=None)` 强制 `env`+`cwd=cwd or repo_root`+`stdin=DEVNULL`+`timeout=60`；`read_worktree_head_sha(path)` 静态方法完整链路（`.git pointer→gitdir→commondir→HEAD→loose ref/packed-refs`）失败返 `None`且无 git 子进程；`_get_current_branch()`/`_get_head_commit()`。
- 测试: 构造默认 worktree_dir；`read_worktree_head_sha` 对真实 worktree 返 40 位 sha、对坏路径返 None；cache 回调被调用；`_run_git` env 含 GIT_TERMINAL_PROMPT。

## T8: create + enter + exit + auto_cleanup + restore
- 影响文件: `aixcode/worktree/manager.py`、`tests/test_worktree.py`
- 依赖任务: T2, T5, T6, T7
- 完成标准（TDD）: `create(slug, base_branch="HEAD")` 在 `async with _lock`：`validate_slug` → `active` 重名 → 快速恢复（`read_worktree_head_sha` 命中直接构造 `Worktree`、**不** setup）→ 未命中 `os.makedirs` → `git worktree add -B worktree-<flat> <path> <base>` → `perform_post_creation_setup` → 写 `active` 返 `Worktree`；`enter(slug)`：`_clear_all_caches` → `os.getcwd`+`_get_current_branch`+`_get_head_commit` → 写 `current_session`+`save_worktree_session`；`exit(name, action, discard_changes=False)`：`action=="remove" and not discard` 时 `count_worktree_changes`>0 抛 `WorktreeError`含具体计数 → 清缓存+清 `current_session`+`save_worktree_session(None)` → `action=="remove"` 调 `_remove_worktree`；`_remove_worktree(name)`：`git worktree remove --force <path>` → `await asyncio.sleep(0.1)` → `git branch -D worktree-<flat>` → `active.pop`；`auto_cleanup(name, head_commit)`：脏返 `CleanupResult(kept=True,path,branch)`、干净 `_remove_worktree` 返 `CleanupResult(kept=False)`；`list_worktrees()`/`get_current_session()`；`restore_session()`：读持久化 → `read_worktree_head_sha` 验证 → 命中写回 `active`+`current_session` 返 session、未命中 `save_worktree_session(None)` 返 None。
- 测试（真实临时 git 仓库）: create 新建目录+分支+返回 Worktree；create 已存在走快速恢复不重 setup；enter 写 session 文件+清缓存；exit keep 保留目录；exit remove 干净删除；exit remove 脏抛 WorktreeError；auto_cleanup 干净删/脏留；restore 命中/未命中清脏。

## T9: 后台过期清理 cleanup
- 影响文件: `aixcode/worktree/cleanup.py`、`tests/test_worktree.py`
- 依赖任务: T3, T8
- 完成标准（TDD）: `EPHEMERAL_PATTERNS` 5 条正则（`^agent-[0-9a-f]{8}$`/`^wf_[0-9a-f]{8}-[0-9a-f]{3}-\d+$`/`^wf-\d+$`/`^bridge-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$`/`^job-[a-zA-Z0-9._-]{1,55}-[0-9a-f]{8}$`）；`_is_ephemeral(name)` 任一 match 返 True；`cleanup_stale_worktrees(manager, cutoff_hours)` 扫 `worktree_dir`，三层过滤 L1 命名→L2 时态(`current_session.worktree_name==name` 跳 + `mtime>cutoff` 跳)→L3 git fail-closed(`read_worktree_head_sha is None` 或 `has_worktree_changes` 或 `has_unpushed_commits` 任一 True 跳)，通过的 `git worktree remove --force`+`sleep(0.1)`+`git branch -D`，返清理数；`start_stale_cleanup_task(manager, interval, cutoff_hours)` 死循环 `await asyncio.sleep(interval)`→清理→异常 warning 不抛。
- 测试: `_is_ephemeral` 命中 agent-/wf_/wf-/bridge-/job-、不命中用户名；cleanup 跳当前 session、跳未过期、跳有变更/未推送、删干净过期 ephemeral；返回数正确。

## T10: 包级 __init__ 导出
- 影响文件: `aixcode/worktree/__init__.py`、`tests/test_worktree.py`
- 依赖任务: T1, T2, T3, T5, T8, T9
- 完成标准（TDD）: 导出 14 符号——`changes`:`Changes/CleanupResult/count_worktree_changes/has_worktree_changes`；`cleanup`:`cleanup_stale_worktrees/start_stale_cleanup_task`；`manager`:`WorktreeError/WorktreeManager`；`models`:`Worktree/WorktreeSession`；`session`:`load_worktree_session/save_worktree_session`；`slug`:`flatten_slug/validate_slug`；`__all__` 列 14 名按字母序。
- 测试: `from aixcode.worktree import WorktreeManager, validate_slug, flatten_slug, ...` 全可导入；`__all__` 长度 14。

## T11: EnterWorktreeTool
- 影响文件: `aixcode/tools/enter_worktree.py`、`tests/test_worktree.py`
- 依赖任务: T1, T8
- 完成标准（TDD）: `EnterWorktreeParams(BaseModel)` 仅 `name: str | None = None`（含描述）；`EnterWorktreeTool(Tool)`：`name="EnterWorktree"`/`category="command"`/`is_concurrency_safe=False`/`should_defer=False`/`params_model=EnterWorktreeParams`；`__init__(worktree_manager)`；`execute`：`get_current_session() is not None` 返 `ToolResult("Already in a worktree session", is_error=True)` → `slug = params.name or f"wt-{secrets.token_hex(4)}"` → `validate_slug` 失败返错 → `manager.create(slug)`+`manager.enter(slug)` → 返回 `ToolResult(f"Created worktree at {path} on branch {branch}. ...")`。
- 测试（真实临时 git）: 已有 session 拒绝；非法名报错；正常创建返回含 path+branch；默认名 wt- 前缀。

## T12: ExitWorktreeTool
- 影响文件: `aixcode/tools/exit_worktree.py`、`tests/test_worktree.py`
- 依赖任务: T3, T8
- 完成标准（TDD）: `ExitWorktreeParams(BaseModel)`：`action: str`（必填）+ `discard_changes: bool | None = None`；`ExitWorktreeTool(Tool)`：`name="ExitWorktree"`/`category="command"`/`is_concurrency_safe=False`/`should_defer=False`；`execute`：`get_current_session() is None` 返 "No-op: there is no active EnterWorktree session to exit. ..."（`is_error=True`）→ `action not in ("keep","remove")` 返非法 → `action=="remove" and not discard` 时 `count_worktree_changes` 拼具体数（单复数 file/files、commit/commits 正确）拒绝 → `manager.exit(name, action, discard)` → keep 返 "Your work is preserved at ..."、remove 返 "Exited and removed worktree at ..."。
- 测试: 无 session no-op；非法 action；remove 有变更被拒含正确单复数；remove discard 强删；keep 保留。

## T13: /worktree 本地命令
- 影响文件: `aixcode/commands/handlers/worktree.py`、`tests/test_worktree.py`（或 `tests/test_commands.py`）
- 依赖任务: T8
- 完成标准（TDD）: `create_worktree_command(manager)` 返 `Command(name="worktree", aliases=["wt"], type=CommandType.LOCAL)`；解析子命令 `create/list/enter/exit/status`，未知报 "未知子命令: ..."；`_handle_create` 调 `manager.create+manager.enter` 并同步 `ctx.agent.work_dir`；`_handle_exit` 解析 `--remove`/`--discard` 映射 `action/discard_changes`；`_handle_list` 列 `manager.list_worktrees` 标当前；`_handle_status` 输出当前 session 路径与原始分支。
- 测试（fake manager）: create/list/status/exit 主路径；未知子命令提示；list 标当前。

## T14: AgentTool worktree 隔离接入
- 影响文件: `aixcode/agents/parser.py`（`AgentDef` 加 `isolation`）、`aixcode/tools/agent_tool.py`、`tests/test_worktree.py`/`tests/test_subagent.py`
- 依赖任务: T4, T8, T11
- 完成标准（TDD）: `AgentDef` 加 `isolation: str | None = None`，parser 从 frontmatter `isolation` 映射；`AgentToolParams` 加 `isolation: str | None = None`；`AgentTool.__init__` 加可选 `worktree_manager=None`；`execute` 取 `isolation = params.isolation or definition.isolation`，`== "worktree"` 走 `_execute_with_worktree(params, definition)`；`_execute_with_worktree`：`worktree_manager is None` 报错 → `generate_worktree_name` 出 `agent-<8hex>` → `manager.create(wt_name,"HEAD")` → `notice = build_worktree_notice(parent_cwd, wt.path)` → `task = notice + "\n\n" + prompt` → 子 Agent `work_dir=wt.path`+独立 `PathSandbox(wt.path)` → `run_to_completion` → `manager.auto_cleanup(wt_name, wt.head_commit)` → `kept` 时结果末尾拼 `[Worktree preserved at <path>, branch <branch>]`。
- 测试: parser 读 isolation；AgentToolParams isolation 默认 None；`_execute_with_worktree` worktree_manager None 报错；isolation 分流（monkeypatch manager + stub run_to_completion）；kept 时附保留说明；干净时 auto_cleanup 删。

## T15: 接入 app.py + __main__.py
- 影响文件: `aixcode/__main__.py`、`aixcode/app.py`、`tests/test_app.py`/`tests/test_worktree.py`
- 依赖任务: T8, T9, T11, T12, T13, T14
- 完成标准:
  - `__main__.py`：建 `worktree_manager = WorktreeManager(repo_root=cwd, file_cache=None, symlink_directories=[])`；`restore_session()` 非 None 时 `agent.work_dir = restored.worktree_path`；建 `AgentTool(..., worktree_manager=worktree_manager)`；`registry.register(EnterWorktreeTool(worktree_manager))` + `registry.register(ExitWorktreeTool(worktree_manager))`；把 `worktree_manager` 传入 `AixCodeApp`。
  - `app.py`：`AixCodeApp.__init__` 加 `worktree_manager=None`；注册 `create_worktree_command(worktree_manager)`（manager 非空时）；`add_cache_clear_callback` 注册清 `agent.recovery_state`/重载 instructions 的回调；`run()` 启动 `self._stale_cleanup_task = asyncio.create_task(start_stale_cleanup_task(manager, interval, cutoff_hours))`（manager 非空时）；teardown 取消该 task。
- 测试: 构造 `AixCodeApp(..., worktree_manager=fake)` 注册 `/worktree` 命令；不传时向后兼容（既有路径绿）；registry 含 EnterWorktree/ExitWorktree。

## T16: 端到端验证
- 影响文件: 无（仅运行验证）
- 依赖任务: T1-T15
- 完成标准:
  - `python -m compileall aixcode tests` 通过；`python -m pytest -q` 全绿（ch01–13 既有 585 + ch14 新增）。
  - 离线 smoke：`from aixcode.worktree import WorktreeManager, validate_slug` 可导入；真实临时 git 仓库里 `manager.create("demo")`→目录+分支建成、`enter`→session 文件写入、`exit("demo","remove",discard_changes=True)`→删除；`cleanup_stale_worktrees` 对有未推送 commit 的 ephemeral 目录保守不删；`_is_ephemeral("agent-<8hex>")` True。
  - 真实手动（本机 `python -m aixcode`，PowerShell，见 checklist §4）。

## 进度
- [x] T1 slug 校验 + 命名映射
- [x] T2 数据模型 models
- [x] T3 变更检测 changes（fail-closed）
- [x] T4 worktree notice integration
- [x] T5 会话持久化 session
- [x] T6 创建后设置四项 setup
- [x] T7 WorktreeManager 主类 + 快速恢复
- [x] T8 create/enter/exit/auto_cleanup/restore
- [x] T9 后台过期清理 cleanup
- [x] T10 包级 __init__ 导出
- [x] T11 EnterWorktreeTool
- [x] T12 ExitWorktreeTool
- [x] T13 /worktree 本地命令
- [x] T14 AgentTool worktree 隔离接入
- [x] T15 接入 app + __main__
- [x] T16 端到端验证（compileall 通过；pytest 681 passed；离线 smoke 全通）
