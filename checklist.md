# ch14: Worktree 系统 Checklist（AixCode / Python 版）

> 所有条目必须可勾选、可观测。验收方式写在每项后面的括号里。操作目录 `d:\Agent\AixCode`，命令用 Bash 工具的 `grep`/`python`/`git` 即可。
> 全局背景见 [spec.md](spec.md) §0。

## 1. 实现完整性

### 1.1 slug + 模型 + 变更检测

- [x] `MAX_SLUG_LENGTH=64` + `validate_slug`（空名/长度/空段/`.`·`..`/非法字符五类）+ `flatten_slug`（`/`→`+`）（`grep -n "MAX_SLUG_LENGTH\|def validate_slug\|def flatten_slug" aixcode/worktree/slug.py` + 单测）
- [x] `@dataclass Worktree`（6 字段 `name/path/branch/based_on/head_commit/created`，created 默认 datetime）+ `@dataclass WorktreeSession`（7 字段，`session_id`/`hook_based` 有默认）（`grep -n "class Worktree\|class WorktreeSession" aixcode/worktree/models.py`）
- [x] `Changes` + `CleanupResult` + `count_worktree_changes`（git 异常 fail-closed 置 1）+ `has_worktree_changes` + `has_unpushed_commits`（git 失败返 True）（`grep -n "class Changes\|class CleanupResult\|def count_worktree_changes\|def has_worktree_changes\|def has_unpushed_commits" aixcode/worktree/changes.py` + 单测）
- [x] `changes._run_git` 强制 `GIT_ENV`(`GIT_TERMINAL_PROMPT=0`/`GIT_ASKPASS=""`) + `stdin=DEVNULL` + `timeout=30`（`grep -n "GIT_ENV\|GIT_TERMINAL_PROMPT\|DEVNULL\|timeout=30" aixcode/worktree/changes.py`）

### 1.2 integration + session + setup

- [x] `WORKTREE_NOTICE_TEMPLATE` 含 `[WORKTREE CONTEXT]` 标记 + `{parent_cwd}`/`{wt_path}` 占位 + "re-read files before editing" 关键句（`grep -n "WORKTREE CONTEXT\|re-read files\|{wt_path}\|{parent_cwd}" aixcode/worktree/integration.py`）
- [x] `generate_worktree_name`（`agent-`+`secrets.token_hex(4)`）+ `build_worktree_notice`（`grep -n "def generate_worktree_name\|def build_worktree_notice\|token_hex" aixcode/worktree/integration.py` + 单测）
- [x] `SESSION_FILENAME="worktree_session.json"` + `save_worktree_session`（None 写 `"{}"`）+ `load_worktree_session`（容忍缺失/坏 JSON/空 dict/缺字段全返 None）（`grep -n "SESSION_FILENAME\|def save_worktree_session\|def load_worktree_session" aixcode/worktree/session.py` + 单测）
- [x] `LOCAL_CONFIG_FILES=["settings.local.json",".env"]` + `perform_post_creation_setup` 依序 A/B/C/D + `_copy_ignored_files` 单文件失败 continue（`grep -n "LOCAL_CONFIG_FILES\|def perform_post_creation_setup\|def _copy_local_configs\|def _setup_git_hooks\|def _create_symlinks\|def _copy_ignored_files" aixcode/worktree/setup.py` + 单测）

### 1.3 WorktreeManager

- [x] `WorktreeError` + `WorktreeManager.__init__`（`_lock=asyncio.Lock()`/`active`/`current_session`/`worktree_dir` 默认 `.aixcode/worktrees`）（`grep -n "class WorktreeError\|class WorktreeManager\|asyncio.Lock\|worktrees" aixcode/worktree/manager.py`）
- [x] `read_worktree_head_sha` 静态方法完整链路（`.git→gitdir→commondir→HEAD→loose/packed-refs`）失败返 None 且无 git 子进程（`grep -n "def read_worktree_head_sha\|commondir\|packed-refs" aixcode/worktree/manager.py` + 单测）
- [x] `manager._run_git` 强制 `GIT_ENV` + `cwd=cwd or repo_root` + `stdin=DEVNULL` + `timeout=60`（`grep -n "def _run_git\|timeout=60\|DEVNULL" aixcode/worktree/manager.py`）
- [x] `create`（快速恢复二选一 + 大写 `-B`）+ `enter`（清缓存+写 session）+ `exit`（remove 未 discard 跑变更保护）（`grep -n "def create\|def enter\|def exit\|worktree add -B\|_clear_all_caches" aixcode/worktree/manager.py` + 单测）
- [x] `_remove_worktree` 含 `await asyncio.sleep(0.1)` 等 lockfile + `auto_cleanup`（脏 kept=True/干净 kept=False）+ `restore_session`（读不到 HEAD 时反向清脏）（`grep -n "def _remove_worktree\|asyncio.sleep(0.1)\|def auto_cleanup\|def restore_session" aixcode/worktree/manager.py` + 单测）
- [x] `add_cache_clear_callback` + `_clear_all_caches`（`grep -n "def add_cache_clear_callback\|def _clear_all_caches" aixcode/worktree/manager.py`）

### 1.4 cleanup

- [x] `EPHEMERAL_PATTERNS` 5 条正则（`^agent-[0-9a-f]{8}$` 等）+ `_is_ephemeral`（`grep -n "EPHEMERAL_PATTERNS\|def _is_ephemeral" aixcode/worktree/cleanup.py` + 单测）
- [x] `cleanup_stale_worktrees` 三层过滤顺序固定（L1 命名→L2 时态→L3 git fail-closed）+ `start_stale_cleanup_task` 死循环异常 warning 不抛（`grep -n "def cleanup_stale_worktrees\|def start_stale_cleanup_task\|has_unpushed_commits\|has_worktree_changes" aixcode/worktree/cleanup.py` + 单测）

### 1.5 工具与命令

- [x] `EnterWorktreeTool`（`name="EnterWorktree"`/`should_defer=False`/`is_concurrency_safe=False`；已有 session 拒绝；默认名 `wt-`）（`grep -n "class EnterWorktreeTool\|EnterWorktree\|Already in a worktree" aixcode/tools/enter_worktree.py` + 单测）
- [x] `ExitWorktreeTool`（`action` 必填；无 session no-op；remove 变更保护单复数正确）（`grep -n "class ExitWorktreeTool\|No-op\|uncommitted\|commit" aixcode/tools/exit_worktree.py` + 单测）
- [x] `create_worktree_command`（`name="worktree"`/`aliases=["wt"]`/子命令 create/list/enter/exit/status）（`grep -n "def create_worktree_command\|def _handle_create\|def _handle_list\|def _handle_exit\|def _handle_status" aixcode/commands/handlers/worktree.py` + 单测）

### 1.6 isolation 接入

- [x] `AgentDef` 加 `isolation` 字段 + parser 映射（`grep -n "isolation" aixcode/agents/parser.py` + 单测）
- [x] `AgentToolParams` 加 `isolation` + `AgentTool.__init__` 接 `worktree_manager` + `_execute_with_worktree`（`grep -n "isolation\|worktree_manager\|def _execute_with_worktree\|build_worktree_notice\|generate_worktree_name\|auto_cleanup" aixcode/tools/agent_tool.py` + 单测）

## 2. 接入完整性（杜绝死代码）

- [x] `grep -rn "WorktreeManager(" aixcode --include="*.py"` 命中 `aixcode/__main__.py` 非测试装配点
- [x] `grep -n "EnterWorktreeTool\|ExitWorktreeTool\|registry.register" aixcode/__main__.py` 两工具均注册
- [x] `grep -n "restore_session" aixcode/__main__.py` 启动恢复调用且命中时设 `agent.work_dir`
- [x] `grep -n "worktree_manager" aixcode/tools/agent_tool.py` AgentTool 接收并使用
- [x] `grep -n "create_worktree_command\|start_stale_cleanup_task\|add_cache_clear_callback\|worktree_manager" aixcode/app.py` 命令注册 + 后台清理 task + 缓存回调
- [x] `grep -n "auto_cleanup\|build_worktree_notice\|generate_worktree_name" aixcode/tools/agent_tool.py` 子 Agent 隔离全链路有真实调用

## 3. 编译与测试

- [x] `python -m compileall aixcode tests` 通过
- [x] `python -m pytest tests/test_worktree.py -q` 全部通过，覆盖：slug / models / changes（fail-closed）/ integration / session（往返+容错）/ setup / manager（create/enter/exit/auto_cleanup/restore + read_worktree_head_sha）/ cleanup（三层过滤）/ 两工具 / /worktree 命令 / AgentTool isolation
- [x] `python -m pytest -q` 全绿（ch01–13 既有 585 + ch14 新增）
- [x] `python -c "from aixcode.worktree import WorktreeManager, validate_slug, flatten_slug; print('ok')"` 无 import 错误
- [x] `python -c "from aixcode.tools.enter_worktree import EnterWorktreeTool; from aixcode.tools.exit_worktree import ExitWorktreeTool; print(EnterWorktreeTool.name, ExitWorktreeTool.name)"` 输出 `EnterWorktree ExitWorktree`

## 4. 离线 smoke + 端到端验证（手动操作 TUI，PowerShell）— 本章待用户手动验收

> 离线 smoke 可自动；带「手动」的真实 TUI 项留用户。启动：`python -m aixcode`

- [x] 离线 smoke：真实临时 git 仓库里 `WorktreeManager.create("demo")` → `.aixcode/worktrees/demo/` + 分支 `worktree-demo` 建成；`enter` 写 `.aixcode/worktree_session.json`；`exit("demo","remove",discard_changes=True)` 删除目录与分支
- [x] 离线 smoke：`_is_ephemeral("agent-"+8hex)` True、用户名 False；`cleanup_stale_worktrees` 对有未推送 commit 的过期 ephemeral 目录保守不删（L3 fail-closed）
- [ ] **手动 路径 A（工具直接驱动）**：让主 Agent「用 EnterWorktree 创建名叫 demo 的工作树」→ 返回 `Created worktree at .../demo on branch worktree-demo`；在 worktree 里 WriteFile + `git commit` → `ExitWorktree({action:"remove"})` 被变更保护拒绝且含具体 `1 commit`/`N commits` → `ExitWorktree({action:"remove", discard_changes:true})` 强删成功
- [ ] **手动 路径 B（子 Agent 自动隔离）**：主目录 WriteFile `witness.txt="original content from main agent"` → 调 `Agent({subagent_type:"<声明 isolation worktree 的类型>", prompt:"把 witness.txt 改成 ..."})` → 主目录 `witness.txt` 不变；`.aixcode/worktrees/agent-*/witness.txt` 是改后版本；有 commit 时结果末尾出现 `[Worktree preserved at ..., branch worktree-agent-...]`
- [ ] **手动 持久化恢复**：TUI 里 `EnterWorktree({name:"crashtest"})` → `Ctrl+C` 杀进程 → `.aixcode/worktree_session.json` 仍在含 crashtest → 重启 `python -m aixcode` → `restore_session` 写回，`agent.work_dir` 已切到 worktree
- [ ] **手动 /worktree 命令**：`/worktree create demo` 创建并进入 → `/worktree status` 显示当前 session → `/worktree list` 列出含 demo → `/worktree exit --remove --discard` 强删

## 5. 文档

- [x] `spec.md` / `tasks.md` / `checklist.md` 三件套齐全于项目根目录（`ls spec.md tasks.md checklist.md`）
- [x] `tasks.md` 16 个任务全部勾上
- [x] `checklist.md` 全部条目勾上（§4 带「手动」的真实 TUI 项除外，留给用户）
