# ch14: Worktree 系统 Spec（AixCode / Python 版）

> 本文件自包含。新对话冷启动时，先读「§0 全局背景」明确**全局目标**，再看「§0 末 + §2」明确 ch14 **当前目标**，然后按 [tasks.md](tasks.md) 顺序、配 [checklist.md](checklist.md) 验收开发。
> 本章把 **Git Worktree** 接进 AixCode：让主 Agent 和每个子 Agent 拥有**空间维度隔离**的独立 working tree（同一时刻多份 working tree、各自分支、共享一个 `.git`），解决多 Agent 并发改同一文件互相覆盖的问题。做成两层 API——会话级（LLM 用 `EnterWorktree`/`ExitWorktree` 工具自主进出）与 Agent 级（子 Agent 经 `isolation: "worktree"` 自动获得独立 worktree），底层共用一个 `WorktreeManager`，叠加 fail-closed 变更保护与孤儿 worktree 后台过期清理。

## 0. 全局背景（每章都要先理解）

**项目**：AixCode —— 一个用 **Python** 写的终端 AI 编程助手（对标 Claude Code），后端用 **Deepseek**（OpenAI 兼容 chat/completions 协议，`config.yaml` 四字段 `protocol/model/base_url/api_key`；验收用 `model: deepseek-chat`）。逐章构建，每章交付 `spec.md / tasks.md / checklist.md` 三件套（覆盖项目根目录）。

**运行环境**：Windows + PowerShell（主力；Bash 工具也可用）；**ch14 起本项目已是 git 仓库**（master 分支，已有初始提交；`.aixcode/` 与 `config.yaml` 已 gitignore）；Python 3.10+（实跑 3.14）；UTF-8 输出已在入口 `sys.stdout.reconfigure` 处理。

**工作方式**：可测单元一律 **TDD**（先写失败测试→看红→最小实现→转绿，沿用仓库约定：纯 pytest 函数 + `asyncio.run`，不引入 pytest-asyncio、不用测试类）；每章末尾必有「接入主流程」+「端到端验证」；改动外科手术式、最小化。验证 `python -m compileall` + `python -m pytest`（不假设 ruff/mypy）。

**已完成章节（现有代码结构，包名 `aixcode/`）**：
- ch01 对话通道：`config.py`(`ProviderConfig`+`load_config`/`load_mcp_servers`/`load_raw_hooks`)、`client.py`(`LLMClient` ABC + `OpenAIClient` 异步流式 `stream`；`create_client(ProviderConfig)`)、`conversation.py`(`Message` 扁平结构 + `ConversationManager`)、`app.py`、`__main__.py`。
- ch03 工具系统：`tools/` 包（`Tool` ABC：类属性 `name/description/params_model/category(read|write|command)/should_defer/is_system_tool/is_concurrency_safe` + async `execute`；`ToolResult(output,is_error)`；`ToolRegistry`：`register/get/list_tools`；6 核心工具 + `ToolSearch/AskUser`；`create_default_registry`）。
- ch04 Agent Loop：`agent.py`——`Agent.run(conversation)` 多轮 ReAct，产 `AgentEvent` 异步流（`StreamText/.../LoopComplete(text)/...`）；`Agent.__init__(client, registry, protocol, work_dir, max_iterations, permission_checker, context_window, memory_manager, hook_engine)`；`partition_tool_calls` 批量执行；`active_conversation`（ch13 加，供 fork 读）。
- ch05 Prompt：`prompts.py`。ch06 权限：`permissions/` 包（`PermissionMode` 五档 / `DangerousCommandDetector` / `PathSandbox(project_root)` / `RuleEngine` / `PermissionChecker`）。ch07 MCP：`mcp/` 包（`mcp_` 前缀）。ch08 上下文：`context/` 包。ch09 记忆：`memory/` 包。
- ch10 Slash Command：`commands/` 包（`CommandRegistry`/`Command`/`CommandContext`/`CommandType(LOCAL|LOCAL_UI|PROMPT)`/`UIController`；`handlers/` 含 13 内置 + `ALL_COMMANDS`/`register_all_commands`；`handlers/mode.py` 的 `parse_mode_name`）。app 实现 `UIController`、`_dispatch_command`、`_build_command_context`（config 闭包）。
- ch11 Skill：`skills/` 包（`SkillLoader` 三级搜索 / `SkillExecutor` inline·fork / `filter_tool_registry`）+ `tools/load_skill.py`。
- ch12 Hook：`hooks/` 包（`LifecycleEvent` 15 事件 / `HookEngine` / `load_hooks`）；`Agent` 有 `hook_engine` + loop 触发点；app 起止派发 startup/shutdown。
- **ch13 SubAgent：`agents/` 包（`parser.py`:`AgentDef`+`parse_agent_file`/校验；`loader.py`:`AgentLoader` 三级搜索+热重载；`tool_filter.py`:`resolve_agent_tools` 四层过滤+MCP 直通；`fork.py`:`build_forked_messages`/`ForkError`；`trace.py`:`TraceManager`/`TraceNode`；`task_manager.py`:`TaskManager`/`BackgroundTask` 后台状态机；`notification.py`:`format_task_notification`/`inject_task_notifications`；`builtins/`:general-purpose/plan/explore）+ `tools/agent_tool.py`(`AgentTool` 三路径 sync/background/fork + 模型路由 + 独立 `PermissionChecker` + 复用父 `hook_engine`)；`commands/handlers/`:`tasks.py`/`trace.py`；app 主循环 `_inject_completed_tasks`(poll+inject) + 中断 `adopt_running`（shield）。`AgentTool.__init__(agent_loader, task_manager, trace_manager, parent_agent, provider_config, enable_fork)`，`AgentToolParams` 字段 `prompt/description/subagent_type/model/run_in_background`。ch13 落地完成，全量 585 passed。**注：ch13 适配时刻意砍掉了 worktree 与 teams（"本项目非 git"）；本章 ch14 在 git init 后补回 worktree。**

**ch14 当前目标**：① 落地 `aixcode/worktree/` 包（slug / models / changes / integration / session / setup / manager / cleanup + `__init__` 导出）；② 两个 LLM 工具 `tools/enter_worktree.py`(`EnterWorktreeTool`) + `tools/exit_worktree.py`(`ExitWorktreeTool`)；③ `commands/handlers/worktree.py` 的 `/worktree` 本地命令；④ `AgentTool` 接 `worktree_manager`，按 `isolation == "worktree"` 走 `_execute_with_worktree` 自动隔离子 Agent；⑤ `AgentDef`/parser 加 `isolation` 字段，`AgentToolParams` 加 `isolation` 入参（声明 + 调用时均可）；⑥ app/__main__ 装配 `WorktreeManager` + `restore_session` + 注册工具/命令 + 后台过期清理 task + 退出清理。

**与 MewCode 参考的关键差异（AixCode 适配，已与用户确认）**：
- **路径**：`mewcode/`→`aixcode/`、`.mewcode/`→`.aixcode/`；worktree 目录 `<repo>/.aixcode/worktrees`、会话文件 `<repo>/.aixcode/worktree_session.json`。
- **不做 teams**：AixCode 无 `teams` 模块（ch13 已砍，MewCode ch14 自身也把 teammate 清理推到 ch15）。`_execute_with_worktree` 仅 worktree，不接 `TeamManager`/`team_name`。
- **should_defer 语义不同**：AixCode 里 `should_defer=True` 表示"披露延迟（ToolSearch 才出）"，非 MewCode 的"批次末延迟执行"。两工具 `should_defer=False` 始终可见；靠 `category="command"` + `is_concurrency_safe=False` 保证串行执行（天然不与其他工具并发）。
- **isolation 双入口**：`AgentDef.isolation`（定义声明）与 `AgentToolParams.isolation`（调用时指定）都支持，`execute` 取 `params.isolation or definition.isolation`。
- **EPHEMERAL agent 正则修正**：MewCode `^agent-a[0-9a-f]{7}$` 仅当首位 hex 为 `a` 才匹配（latent bug）；AixCode 产出 `agent-<8hex>` 任意 hex，故用 `^agent-[0-9a-f]{8}$`，其余 4 条正则照搬。
- **缓存清理**：AixCode 无 `FileCache` 类。`WorktreeManager` 保留通用 `add_cache_clear_callback`/`_clear_all_caches`；`file_cache` 构造参数可选（dict-like 或 None）；app 注册回调清 Agent 的 `recovery_state` 并重载 `instructions_content`。
- **工具按 work_dir 解析相对路径（ch14 修复）**：原本所有文件工具（ReadFile/WriteFile/EditFile/Glob/Grep/Bash）的相对路径基准是**进程 cwd**，不读 `agent.work_dir`，导致 worktree 隔离时"沙箱检查基准 ≠ 实际写入基准"、子 Agent 相对路径会静默写到主仓库、隔离失效。修复：新增 `tools/workdir.py`（`ContextVar` + `current_work_dir`/`push_work_dir`/`pop_work_dir`/`resolve_path`），`Agent._run_tool` 执行工具前 push 本 Agent 的 `work_dir`、执行后 pop（并发批次各自独立 context、嵌套子 Agent 配对恢复）；文件工具改用 `resolve_path`（绝对路径不变、相对路径基于注入的 work_dir，无注入回退进程 cwd 保持向后兼容），Bash 用 `cwd=current_work_dir()`。会话级 `WorktreeManager` 加 `add_work_dir_callback`/`_notify_work_dir`，enter 切进 worktree、exit 切回原目录时由 app 回调同步 `agent.work_dir` 与 `PathSandbox`。
- **git 子进程编码（ch14 修复）**：所有 worktree 内 `subprocess.run` 显式 `encoding="utf-8", errors="replace"`，避免 Windows 默认 locale（gbk）解码 git 输出崩溃。
- **git 子进程超时**：统一 `timeout=60`（`_run_git`）/ 变更检测层 `timeout=30`；均关终端提示（`GIT_TERMINAL_PROMPT=0`/`GIT_ASKPASS=""`/`stdin=DEVNULL`），失败返 `CompletedProcess` 不抛。
- 测试纯 pytest 函数 + `asyncio.run`；验证 `compileall` + `pytest`；三件套放仓库根；开发期不主动 git commit（除非用户要求）。

## 1. 背景

SubAgent（ch13）隔离了消息、权限、工具结果缓存，但所有子 Agent 仍共享同一个工作目录——两个子 Agent 并发改同一文件会互相覆盖。Git 分支不解决这个问题：分支是时间维度的快照，同一时刻整个仓库只有一份 working tree，切分支会动所有文件 mtime 触发全量重编。多 Agent 并行要的是**空间维度隔离**：同时存在多份独立 working tree，各对应不同分支、共享同一个 `.git`。Git Worktree 提供的就是这个能力。本章把它接进 AixCode，让主 Agent 和每个子 Agent 都能拥有独立文件视图。

## 2. 目标

把 worktree 做成两层 API：会话级让 LLM 通过 `EnterWorktree`/`ExitWorktree` 工具自主进出 worktree；Agent 级让 SubAgent 通过 `isolation: "worktree"` 声明（或调用时指定）自动获得独立 worktree。底层共用一个 `WorktreeManager` 提供创建/快速恢复路径和"创建后设置"管线（本地配置复制 / git hooks 配置 / 大目录软链接 / `.worktreeinclude` 文件复制）。叠加 fail-closed 变更检测（无变更才允许清掉、有变更默认保留）和孤儿 worktree 后台过期清理 task，保证既不丢用户工作、又不让磁盘堆积。

## 3. 功能需求

- F1: slug 安全校验 `validate_slug(slug)`：限定字符集每段 `^[a-zA-Z0-9._-]+$`、总长 ≤ `MAX_SLUG_LENGTH=64`、按 `/` 切段、显式拒绝空名/空段/`.`/`..` 段，校验失败返回带原因字符串，合法返回 `None`；任何 git 命令或路径拼接前先跑。
- F2: 命名映射 `flatten_slug(s) = s.replace("/", "+")`，避免嵌套 slug 导致目录/分支 D/F conflict；分支名由调用方拼 `f"worktree-{flat_slug}"`（统一前缀便于从 `git branch` 识别 AixCode 创建的）。
- F3: 快速恢复 `WorktreeManager.read_worktree_head_sha(path)`（静态方法）：worktree 目录已存在时纯文件系统读 `.git` 指针 → `gitdir` → `commondir` → `HEAD` → loose ref / packed-refs，跳过 git 子进程；任一步失败返 `None`，调用方回退完整创建路径。
- F4: git 子进程安全壳：所有 git 调用 `env={**os.environ, GIT_TERMINAL_PROMPT:"0", GIT_ASKPASS:""}` + `stdin=subprocess.DEVNULL`，绝不挂起等输入；`manager._run_git` 统一 `timeout=60`、`changes._run_git` `timeout=30`，失败返 `CompletedProcess` 不抛。
- F5: 创建/恢复主入口 `WorktreeManager.create(slug, base_branch="HEAD")`：`async with _lock` → `validate_slug` → `active` 字典重名检查 → 命中已存在目录走快速恢复（不重跑创建后设置）→ 未命中 `os.makedirs(worktree_dir, exist_ok=True)` → `git worktree add -B worktree-<flat> <path> <base_branch>`（大写 `-B` 容忍上次未清的孤儿分支）→ `perform_post_creation_setup`。
- F6: 创建后设置四项 `perform_post_creation_setup(repo_root, worktree_path, symlink_directories)` 依序：A `_copy_local_configs` 复制 `LOCAL_CONFIG_FILES=["settings.local.json",".env"]`（不存在静默跳过）；B `_setup_git_hooks` 优先 `<repo>/.husky` 回退 `<repo>/.git/hooks`，找到目录在 worktree 跑 `git config core.hooksPath`；C `_create_symlinks` 逐个 `os.symlink`，错误日志吞掉不抛；D `_copy_ignored_files` 读 `<repo>/.worktreeinclude`（跳空行和 `#`）→ `git ls-files --others --ignored --exclude-standard --directory` → `fnmatch` 筛选 → 命中 `shutil.copy2`，单文件失败 `continue` 不中断。A 必做，B/C/D best-effort。
- F7: 会话级 API：`create`（见 F5）、`enter(slug)`（`_clear_all_caches` → 记 `original_cwd`/`original_branch`/`original_head_commit` → 写 `current_session` + `save_worktree_session`）、`exit(name, action, discard_changes=False)`（`action="remove" and not discard_changes` 时跑变更保护抛 `WorktreeError` 含具体计数 → 清缓存 + 清单例 + `save_worktree_session(None)` → `action="remove"` 调 `_remove_worktree`）。
- F8: 会话持久化：`save_worktree_session(aixcode_dir, session)` 把 `WorktreeSession` 7 字段 dump 到 `<aixcode_dir>/worktree_session.json`，`session is None` 时写 `"{}"`（清空）；`load_worktree_session(aixcode_dir)` 容忍文件缺失、JSON 损坏、空 dict、缺 `worktree_path` 全部返 `None` + warning，`session_id`/`hook_based` 用 `.get` 容忍旧版缺字段。
- F9: 启动恢复 `WorktreeManager.restore_session()`：读持久化 → `read_worktree_head_sha` 验证 worktree 路径仍在 → 命中把 `Worktree` 写回 `active` + `current_session` 并返回 `WorktreeSession`；HEAD SHA 读不到则反向 `save_worktree_session(None)` 清脏文件并返 `None`。
- F10: 自动清理 `WorktreeManager.auto_cleanup(name, head_commit)`：`has_worktree_changes` 看脏不脏，干净直接 `_remove_worktree` 返 `CleanupResult(kept=False)`，脏返 `CleanupResult(kept=True, path, branch)`；供 SubAgent 完成后调用。
- F11: SubAgent 集成 `AgentTool._execute_with_worktree`：`worktree_manager is None` 报错 → `generate_worktree_name()` 生成 `agent-<8hex>` slug → `worktree_manager.create(wt_name, "HEAD")` → `build_worktree_notice(parent_cwd, wt.path)` 拼到 prompt 前 → 子 Agent `work_dir=wt.path` + 独立 `PathSandbox(wt.path)` 锁权限边界 → `run_to_completion`。
- F12: 子 Agent 完成后决策：`auto_cleanup(wt_name, wt.head_commit)` 干净 → 自动清理，脏 → 保留并在结果末尾附 `[Worktree preserved at <path>, branch <branch>]` 给主 Agent review。
- F13: 变更保护 `ExitWorktreeTool`：`action="remove"` 且 `discard_changes` 非 True 时调 `count_worktree_changes`，`uncommitted > 0 or new_commits > 0` 拒绝并把具体数（file/files、commit/commits 单复数正确）回吐给 LLM。
- F14: 变更检测 fail-closed：`count_worktree_changes` 的 `_run_git` 抛 `SubprocessError/OSError/ValueError` 时对应计数置 1（按"有变更"处理）；`has_unpushed_commits` git 失败返 `True`；绝不在 git 失败时清掉用户工作。
- F15: LLM Tool 暴露：`EnterWorktreeTool`（input 仅可选 `name`，已有 session 时拒绝 "Already in a worktree session"）和 `ExitWorktreeTool`（input `action` 必填、`discard_changes` 可选，无 session 时返回 "No-op: ..."）；两工具 `category="command"`、`is_concurrency_safe=False`、`should_defer=False`（始终可见）。
- F16: 临时 worktree 命名模式 `EPHEMERAL_PATTERNS`（5 条正则集中维护）：`^agent-[0-9a-f]{8}$`（AixCode 修正）/ `^wf_[0-9a-f]{8}-[0-9a-f]{3}-\d+$` / `^wf-\d+$` / `^bridge-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$` / `^job-[a-zA-Z0-9._-]{1,55}-[0-9a-f]{8}$`；区分自动产物与用户手动命名。
- F17: 后台过期清理 `cleanup_stale_worktrees(manager, cutoff_hours)` 三层过滤：L1 命名（`_is_ephemeral` False 跳）→ L2 时态（`current_session.worktree_name==name` 跳 + `mtime > cutoff` 跳）→ L3 git 状态 fail-closed（`read_worktree_head_sha is None` 或 `has_worktree_changes` 或 `has_unpushed_commits` 任一 True 都跳）；通过的删 worktree + 删分支。`start_stale_cleanup_task(manager, interval, cutoff_hours)` 死循环 `await asyncio.sleep(interval)` → 清理 → 异常 warning 不抛。

## 4. 非功能需求

- N1: `WorktreeManager` 用 `asyncio.Lock` 保护 `create`，并发创建同名互斥；`active` 字典和 `current_session` 同一锁覆盖。
- N2: 任何 worktree 删除（会话 exit / Agent auto_cleanup / 后台清理）都要保证当前 cwd 不在 worktree 内（`_run_git` 的 `cwd` 缺省走 `repo_root`），否则 `git worktree remove` 失败。
- N3: `git worktree remove` 和 `git branch -D` 之间必须 `await asyncio.sleep(0.1)` 等 git lockfile 释放，否则 branch 删除偶发失败。
- N4: `restore_session` 在 HEAD SHA 读不到时必须主动 `save_worktree_session(None)` 清脏文件，否则下次启动反复尝试恢复同一损坏 session。
- N5: 三层过滤执行顺序固定：先廉价命名 → 再时态 → 最后贵的 git 检查；任一层判定保留立即 `continue`。
- N6: 创建后设置的软链接和 `.worktreeinclude` 复制是 best-effort——单文件失败只 `log.warning` 不抛。
- N7: 变更保护错误信息必须含具体数字（N file/files + M commit/commits）和正确单复数，让 LLM 据此判断是否强删；不能只回 "has changes"。
- N8: worktree 子系统不假设统一日志层，创建/退出/清理信息通过工具结果文本传达（同时是给 LLM 的运行时反馈）；日志只用 `logging.getLogger(__name__)`。

## 5. 设计概要

- 包结构 `aixcode/worktree/`：`slug.py`(`MAX_SLUG_LENGTH`/`validate_slug`/`flatten_slug`)、`models.py`(`Worktree`/`WorktreeSession`)、`changes.py`(`GIT_ENV`/`_run_git`/`Changes`/`count_worktree_changes`/`has_worktree_changes`/`CleanupResult`/`has_unpushed_commits`)、`integration.py`(`WORKTREE_NOTICE_TEMPLATE`/`generate_worktree_name`/`build_worktree_notice`)、`session.py`(`SESSION_FILENAME`/`save_worktree_session`/`load_worktree_session`)、`setup.py`(`LOCAL_CONFIG_FILES`/`perform_post_creation_setup`/四私有项)、`manager.py`(`GIT_ENV`/`WorktreeError`/`WorktreeManager`)、`cleanup.py`(`EPHEMERAL_PATTERNS`/`_is_ephemeral`/`cleanup_stale_worktrees`/`start_stale_cleanup_task`)、`__init__.py`(导出 14 符号)。
- 工具与命令：`tools/enter_worktree.py`(`EnterWorktreeParams`/`EnterWorktreeTool`)、`tools/exit_worktree.py`(`ExitWorktreeParams`/`ExitWorktreeTool`)、`commands/handlers/worktree.py`(`create_worktree_command` + create/list/enter/exit/status 子命令)。
- 改动：`agents/parser.py`(`AgentDef` 加 `isolation` 字段 + parser 映射)、`tools/agent_tool.py`(`AgentToolParams` 加 `isolation`；`__init__` 接 `worktree_manager=None`；`execute` 分流 `_execute_with_worktree`)、`app.py`(`WorktreeManager` 装配 + `restore_session` + 注册工具/命令 + 后台清理 task + 退出清理 + cache 回调)、`__main__.py`(建 manager、传 app 与 AgentTool)。
- 主流程：
  1. 会话级 Enter：`EnterWorktreeTool.execute` → guard 已有 session → `validate_slug` → `manager.create(slug)`（快速恢复或 add+setup）→ `manager.enter(slug)` → 返回带路径和分支的文本。
  2. 会话级 Exit：`ExitWorktreeTool.execute` → guard 无 session → `action="remove"` 且未 `discard_changes` 跑 `count_worktree_changes` → `manager.exit(name, action, discard)`（remove 时 `_remove_worktree`：`git worktree remove --force` → sleep 0.1 → `git branch -D`）。
  3. Agent 级隔离：`AgentTool.execute` 见 `isolation == "worktree"` → `_execute_with_worktree` → `generate_worktree_name` → `manager.create(wt_name,"HEAD")` → `build_worktree_notice` 拼 prompt 前缀 → 子 Agent `work_dir`+`PathSandbox` → 跑完 `auto_cleanup`。
  4. 后台过期清理：app 启动 `asyncio.create_task(start_stale_cleanup_task(...))` → 死循环 sleep → `cleanup_stale_worktrees` 三层过滤 → 通过的删。
  5. 启动恢复：app 建 manager 后 `restore_session()`，命中则 `agent.work_dir = restored.worktree_path`。
- 调用链：`__main__`/`app` → `WorktreeManager(repo_root, file_cache?, symlink_directories)` → `restore_session` → 注册 `EnterWorktreeTool`/`ExitWorktreeTool`/`create_worktree_command` → `asyncio.create_task(start_stale_cleanup_task)`；LLM Enter/Exit → 工具 registry → `manager` 会话级 API；`AgentTool` 见 isolation → `manager.create` + `build_worktree_notice` → 子 Agent → `auto_cleanup`。
- 与其他模块交互：依赖 `tools`(注册两工具)、`agents`(parser isolation 字段)、`commands`(/worktree)、`permissions`(子 Agent 独立 `PathSandbox`)；底层只 `asyncio`+`subprocess`(git)+标准库(`re`/`json`/`pathlib`/`secrets`/`fnmatch`/`shutil`)+`pydantic`(工具 schema)。不依赖 `memory`/`prompts`/`teams`。

## 6. Out of Scope

- teams 团队成员（teammate）路径与 `TeamManager`：AixCode 无 teams 模块，本章不接（与 ch13 一致，MewCode ch14 自身也把 teammate 清理推到 ch15）。
- 非 git VCS 适配（hg/jj/sapling），所有 worktree 操作 hardcode git 子命令。
- sparse checkout / partial clone 优化；`--worktree`/tmux CLI 启动快速路径；PR fetch / pull request 头引用解析；prepare-commit-msg hook 注入 commit attribution；FindCanonicalGitRoot 穿透 commondir 的独立工具（仅以 `repo_root` 注入为主）。
- 不引入第三方 gitignore 库（`fnmatch` 简化匹配够用）。

## 7. 完成定义

见 [checklist.md](checklist.md)，所有条目勾上即完成（§4 端到端的真实 TUI 项留用户手动验收）。
