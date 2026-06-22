# ch15: AgentTeam 系统 Spec（AixCode / Python 版）

> 本文件自包含。新对话冷启动时，先读「§0 全局背景」明确**全局目标**，再看「§0 末 + §2」明确 ch15 **当前目标**，然后按 [tasks.md](tasks.md) 顺序、配 [checklist.md](checklist.md) 验收开发。
> 本章把 **AgentTeam（长期协作团队）** 接进 AixCode：把子 Agent 拓扑从 ch13 的**星型**（子 Agent 只能与主 Agent 通信、彼此不可见）升级为**网状**（多个队员并行干活、直接互发消息、共享任务列表与邮箱），主 Agent 可选切换 **Coordinator Mode** 专职调度。底层提供 `AgentTeam`/`TeammateInfo`/`TeamManager`/`Mailbox`/`SharedTaskStore`/`AgentNameRegistry` 一整套数据结构与服务，对 LLM 暴露 `TeamCreate`/`TeamDelete`/`SendMessage` + 共享任务 `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` 七个工具，并让 `Agent` 工具带 `team_name` 把队员 spawn 进团队（复用 ch14 worktree 做空间隔离 + 受限工具池）。

## 0. 全局背景（每章都要先理解）

**项目**：AixCode —— 一个用 **Python** 写的终端 AI 编程助手（对标 Claude Code），后端用 **Deepseek**（OpenAI 兼容 chat/completions 协议，`config.yaml` 四字段 `protocol/model/base_url/api_key`；验收用 `model: deepseek-chat`）。逐章构建，每章交付 `spec.md / tasks.md / checklist.md` 三件套（覆盖项目根目录）。

**运行环境**：Windows + PowerShell（主力；Bash 工具也可用）；本项目自 ch14 起已是 **git 仓库**（当前在 `ch15-agentteam` 分支，ch14 已合并回 `master`；`.aixcode/` 与 `config.yaml` 已 gitignore）；Python 3.10+（实跑 3.14）；UTF-8 输出已在入口 `sys.stdout.reconfigure` 处理。**注意本机无 tmux / iTerm2**，团队队员本机一律走 **in-process** 后端（config.yaml 设 `teammate_mode: "in-process"`）。

**工作方式**：可测单元一律 **TDD**（先写失败测试→看红→最小实现→转绿，沿用仓库约定：纯 pytest 函数 + `asyncio.run`，不引入 pytest-asyncio、不用测试类）；每章末尾必有「接入主流程」+「端到端验证」；改动外科手术式、最小化。验证 `python -m compileall aixcode tests` + `python -m pytest -q`（不假设 ruff/mypy/pyright）。

**已完成章节（现有代码结构，包名 `aixcode/`）**：
- ch01 对话通道：`config.py`(`ProviderConfig`+`load_config`/`load_mcp_servers`/`load_raw_hooks`)、`client.py`(`LLMClient` ABC + `OpenAIClient` 异步流式 `stream`；`create_client(ProviderConfig)`)、`conversation.py`(`Message{role,content,tool_calls,tool_call_id}` 扁平结构 + `ConversationManager{history,env_injected,ltm_injected,last_input_tokens}`)、`app.py`、`__main__.py`。
- ch03 工具系统：`tools/` 包（`Tool` ABC：类属性 `name/description/params_model/category(read|write|command)/should_defer/is_system_tool/is_concurrency_safe` + async `execute`；`ToolResult(output,is_error)`；`ToolRegistry`：`register/get/list_tools/is_enabled/get_all_schemas/get_deferred_tool_names`；6 核心工具 ReadFile/WriteFile/EditFile/Bash/Glob/Grep + ToolSearch/AskUser；`create_default_registry`）。
- ch04 Agent Loop：`agent.py`——`Agent.run(conversation)` 多轮 ReAct 异步生成器（`while True` 主循环，产 `AgentEvent`：`StreamText/ThinkingText/ToolUseEvent/ToolResultEvent/TurnComplete/UsageEvent/LoopComplete(text)/ErrorEvent/...`）；`Agent.__init__(client, registry, protocol, work_dir, max_iterations, permission_checker, context_window, memory_manager, hook_engine)`；`partition_tool_calls` 批量执行；`active_conversation`（ch13 加，供 fork 读）；`_run_tool` 用 contextvar push/pop work_dir（ch14 加）。
- ch05 Prompt：`prompts.py`（`build_system_prompt(custom_instructions="", deferred_tools=None)`；环境/Plan 提醒走对话通道）。ch06 权限：`permissions/` 包（`PermissionMode` 五档 / `DangerousCommandDetector` / `PathSandbox(project_root)` / `RuleEngine` / `PermissionChecker`）。ch07 MCP：`mcp/` 包（`mcp_` 前缀）。ch08 上下文：`context/` 包。ch09 记忆：`memory/` 包。
- ch10 Slash Command：`commands/` 包（`CommandRegistry`/`Command`/`CommandContext`/`CommandType`/`UIController`；`handlers/` 含内置命令；`handlers/mode.py` 的 `parse_mode_name`）。
- ch11 Skill：`skills/` 包（`SkillLoader`/`SkillExecutor`/`filter_tool_registry`）+ `tools/load_skill.py`。
- ch12 Hook：`hooks/` 包（`LifecycleEvent` 15 事件 / `HookEngine` / `load_hooks`）；`Agent` 有 `hook_engine` + loop 触发点。
- ch13 SubAgent：`agents/` 包（`parser.py`:`AgentDef`+`parse_agent_file`；`loader.py`:`AgentLoader` 三级搜索+热重载；`tool_filter.py`:`resolve_agent_tools` 四层过滤+MCP 直通、`ALL_AGENT_DISALLOWED_TOOLS`/`CUSTOM_AGENT_DISALLOWED_TOOLS`/`ASYNC_AGENT_ALLOWED_TOOLS`；`fork.py`:`build_forked_messages`/`ForkError`；`trace.py`:`TraceManager`/`TraceNode`；`task_manager.py`:`TaskManager`/`BackgroundTask`；`notification.py`；`builtins/`:general-purpose/plan/explore）+ `tools/agent_tool.py`(`AgentTool` 三路径 sync/background/fork + 模型路由 + 独立 `PermissionChecker`；**注意 `run_to_completion(sub_agent, conversation)` 是该文件的模块级函数，不是 `Agent` 的方法**)。`AgentTool.__init__(agent_loader, task_manager, trace_manager, parent_agent, provider_config, enable_fork=False, worktree_manager=None)`，`AgentToolParams` 字段 `prompt/description/subagent_type/model/run_in_background/isolation`。585 passed。
- **ch14 Worktree：`worktree/` 包（`slug`/`models`/`changes`/`integration`/`session`/`setup`/`manager`/`cleanup` + `__init__`）；`WorktreeManager`(`create`/`enter`/`exit`/`auto_cleanup`/`restore_session`/`read_worktree_head_sha`/`add_cache_clear_callback`/`add_work_dir_callback`/`_notify_work_dir`，git 子进程 `encoding="utf-8"`+`GIT_TERMINAL_PROMPT=0`+`timeout`)；两 LLM 工具 `EnterWorktreeTool`/`ExitWorktreeTool`；`/worktree` 命令；`AgentTool._execute_with_worktree`（`isolation=="worktree"` 自动隔离子 Agent，建独立 worktree + `PathSandbox` + 跑完 `auto_cleanup`）；`AgentDef.isolation` + `AgentToolParams.isolation` 双入口。**ch14 关键修复：工具按 work_dir 解析相对路径**——新增 `tools/workdir.py`（`ContextVar` + `current_work_dir`/`push_work_dir`/`pop_work_dir`/`resolve_path`），`Agent._run_tool` 执行工具前 push 本 Agent 的 `work_dir`、执行后 pop；6 个文件工具改用 `resolve_path`/`current_work_dir`；app 经 `add_work_dir_callback` 在切 worktree 时同步 `agent.work_dir` 与 `PathSandbox`。装配在 `__main__.py`（建 `WorktreeManager` → `restore_session` → 注册工具 → 传 app + AgentTool）。694 passed。**

**ch15 当前目标**：① 落地 `aixcode/teams/` 包（`models`/`mailbox`/`backend_detect`/`shared_task`/`registry`/`spawn_inprocess`/`spawn_tmux`/`spawn_iterm2`/`transcript`/`manager`/`coordinator` + `__init__`）；② 七个 LLM 工具——`tools/send_message.py`、`tools/team_create.py`、`tools/team_delete.py` 三件套 + `tools/task_create.py`/`task_get.py`/`task_list.py`/`task_update.py` 四个共享任务工具；③ 扩展 `agents/tool_filter.py`（`COORDINATOR_MODE_ALLOWED_TOOLS`/`TEAMMATE_COORDINATION_TOOLS`/`IN_PROCESS_TEAMMATE_ALLOWED_TOOLS`/`apply_coordinator_filter`/`build_teammate_tools`）；④ `Agent` 加 `agent_id`/`team_name`/`coordinator_mode`/`_team_manager` 字段 + `_consume_mailbox` 钩入 `run` 主循环开头；⑤ `AgentTool` 加 `team_name`/`name` 入参 + `_execute_as_teammate` 分支；⑥ `prompts.build_system_prompt` 加 `coordinator_mode` 参数；⑦ `config.py` 加 `load_team_settings`（`teammate_mode`/`enable_coordinator_mode`）；⑧ `__main__.py` 装配 `TeamManager` + 注册七工具 + 写回 `agent._team_manager`/`agent.agent_id`。

**与 MewCode 参考的关键差异（AixCode 适配，已与用户确认）**：
- **路径/命名/环境变量**：`mewcode/`→`aixcode/`、`~/.mewcode/teams/`→`~/.aixcode/teams/`；环境变量 `MEWCODE_TEAM_NAME`/`MEWCODE_TEAMMATE_NAME`/`MEWCODE_MAILBOX_DIR`/`MEWCODE_COORDINATOR_MODE`→`AIXCODE_*`。
- **后端范围（本机走 in-process）**：`detect_backend` 完整优先级链照搬（`teammate_mode=="in-process" or not is_interactive` → `TMUX` env → iTerm2+it2 → tmux → 否则抛 `BackendDetectionError` **不静默回退**）。`spawn_tmux`/`spawn_iterm2`/`build_cli_command` 移植为代码 + **mock 单测**（patch `subprocess`/`shutil.which`），验证拼接与三级 fallback 逻辑；**真实 pane 启动与 `python -m aixcode -p` 单次执行模式 CLI flag 解析属 Out of Scope**（本机无 Unix 环境验收）。Windows 上必须在 config.yaml 设 `teammate_mode: "in-process"`，否则 `detect_backend` 按设计抛错。
- **Agent 无 `agent_id`**：新增 `self.agent_id`（默认 `uuid4().hex[:12]`）；mailbox 寻址、name registry、teammate 标识都用它。Lead 用自身 `agent_id`，队员由 `_execute_as_teammate` 显式赋值。
- **无 `Agent.run_to_completion` 方法**：MewCode 的 `spawn_inprocess_teammate` 调 `agent.run_to_completion`；AixCode 复用 `tools/agent_tool.py` 的**模块级** `run_to_completion(agent, conversation)`，`spawn_inprocess_teammate(agent, prompt, name, conversation=None)` 内构造 `ConversationManager`（或用传入的 conversation）再调它；为避免 `teams.spawn_inprocess` ↔ `tools.agent_tool` 循环导入，在函数内**懒导入** `run_to_completion`。
- **`_consume_mailbox` 单一钩点**：MewCode 钩在 `run_to_completion` 主循环；AixCode 的主循环就是 `Agent.run` 的 `while True`，在循环体**最开头**（`iteration += 1` 之后、`auto_compact`/`build_system_prompt`/`client.stream` 之前）`await self._consume_mailbox(conversation)`。此单点同时覆盖 Lead（由 app 驱动 `agent.run`）与 in-process 队员（由模块 `run_to_completion` 驱动 `sub_agent.run`）。
- **扁平 Message 结构 → transcript 简化**：AixCode `ConversationManager.history` 是 `list[Message{role,content,tool_calls,tool_call_id}]`（非 MewCode 的 ToolUseBlock/ToolResultBlock）。`save_transcript` 直接把每条 Message 转 dict（`role/content/tool_calls/tool_call_id`）落 JSON；`load_transcript` 反序列化为 `Message` 列表回填 `history`，并置 `env_injected = ltm_injected = True` 防重复注入。
- **工具白名单按 AixCode 实际工具集裁剪**（无 Cron / 无 SyntheticOutput）：
  - `COORDINATOR_MODE_ALLOWED_TOOLS` = `{Agent, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, TeamCreate, TeamDelete, ReadFile, Glob, Grep, Bash}` 共 12 项（写工具 `WriteFile`/`EditFile` 排除）。
  - `TEAMMATE_COORDINATION_TOOLS` = `{SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate}` 共 5 项。
  - `IN_PROCESS_TEAMMATE_ALLOWED_TOOLS` = `ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS`（去掉 MewCode 的 `{CronCreate,CronDelete,CronList}`，AixCode 无 Cron）。
- **共享任务工具需自建**：AixCode 无 TaskCreate/Get/List/Update 工具（ch13 的 `task_manager` 是后台子 Agent 任务，与此无关），本章基于 `SharedTaskStore` 新建 4 个工具。
- **砍 SyntheticOutput**：MewCode 协调模式有 `SyntheticOutputTool`，AixCode 不实现（Out of Scope），coordinator 用普通正文输出综合结论。
- **idle 通知经 asyncio done_callback**：AixCode in-process 队员用 `asyncio.create_task` 独立运行（不走 ch13 的 `TaskManager`），故 `_execute_as_teammate` 在队员 task 上 `add_done_callback` 调 `team_manager.on_teammate_completed(agent_id)` 触发 idle 标记 + 写 Lead 邮箱；pane 队员的 idle 自动检测属 Out of Scope（队员可自行 `SendMessage` 告知）。
- **装配在 `__main__.py`**：MewCode 在 `app.py.__init__` 建 `TeamManager`；AixCode 沿用 ch13/ch14 约定在 `__main__.py` 建 `TeamManager(worktree_manager, trace_manager)`、传 `AgentTool(team_manager=...)`、注册七工具、`agent._team_manager = team_manager`，并把 `teammate_mode`/`enable_coordinator_mode` 经 `load_team_settings` 透传。
- **config 扩展方式**：AixCode 无 `AppConfig`。沿用 `load_mcp_servers`/`load_raw_hooks` 的独立 loader 约定，新增 `load_team_settings(path) -> tuple[str, bool]` 读 `teammate_mode`（默认 `""`，校验 ∈ `{"", "in-process"}`）与 `enable_coordinator_mode`（默认 `False`）。
- **测试约定**：纯 pytest 函数 + `asyncio.run`；用 `monkeypatch.setattr("aixcode.teams.models.Path.home", ...)` 把 home 重定向到 `tmp_path` 防污染主目录；`AgentNameRegistry.reset()` 用 autouse fixture 在每个用例前清单例。验证 `compileall` + `pytest`；三件套放仓库根；开发期不主动 git commit（除非用户要求）。

## 1. 背景

SubAgent（ch13）解决了一次性子任务的上下文隔离，但拓扑是**星型**：所有子 Agent 只能和主 Agent 通信，子 Agent 之间彼此看不见。当任务规模上来——四个模块同时重构、多角度并行调查 bug、一个 Agent 需要把发现告诉另一个——星型拓扑下主 Agent 成了信息中转瓶颈，子任务被迫串行。本章把「长期协作团队」做成 AixCode 的一等概念：多个 Agent 组成 Team，并行干活、直接互发消息、共享任务列表和邮箱，主 Agent 可选切换为 Coordinator Mode 专职调度。空间隔离复用 ch14 的 worktree（每个队员一个独立 working tree）。

## 2. 目标

提供 `AgentTeam`/`TeammateInfo`/`TeamManager`/`Mailbox`/`SharedTaskStore`/`AgentNameRegistry` 一整套数据结构与服务，暴露 `TeamCreate`/`TeamDelete`/`SendMessage` + `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` 七个工具，让 LLM 在对话里：1) 调 `TeamCreate` 建团队（按环境自动选后端，本机走 in-process，在 `~/.aixcode/teams/<slug>/` 落 `config.json` + `tasks.json` + `mailbox/`）；2) 调 `Agent` 工具带 `team_name` 把队员 spawn 进团队（复用 ch14 独立 worktree + 受限工具池）；3) 队员之间通过 `SendMessage` 走 `Mailbox` 互发消息、按 name 或 agent_id 寻址、支持 `to="*"` 广播；4) 每个 Agent 每轮迭代开头 `_consume_mailbox` 把收件箱消息转 user message 注入对话；5) 启用 `enable_coordinator_mode` 后 Lead 通过 `apply_coordinator_filter` 把工具集收窄到 12 项白名单。pane 后端（tmux/iTerm2）的拼命令/spawn 代码移植并 mock 测试，但真实启动本机不验收。

## 3. 功能需求

- F1: `BackendType` 枚举三档 `TMUX="tmux"` / `ITERM2="iterm2"` / `IN_PROCESS="in-process"`；`detect_backend(teammate_mode, is_interactive)` 优先级 `teammate_mode == "in-process" or not is_interactive` → `TMUX` env 非空 → `TERM_PROGRAM == "iTerm.app"` 且 `shutil.which("it2")` → `shutil.which("tmux")`；都不命中抛 `BackendDetectionError`（含 `brew install tmux` / iTerm2+it2 安装指引 + 提示设 `teammate_mode: "in-process"`），**不静默回退**。
- F2: `AgentTeam` dataclass 持有 `name / lead_agent_id / members: list[TeammateInfo] / config_path / description`，含 `to_dict`/`from_dict`/`save`/`load`；`get_member(name)` 同时按 `name` 或 `agent_id` 查找；`add_member`/`remove_member`（直接从列表移除不留墓碑）；`set_member_active(name, is_active)` 翻活跃标志；`active_members()` 返回活跃成员；`all_idle()` 返回是否全员 `is_active is False`。
- F3: `TeammateInfo` dataclass 字段 `name / agent_id / agent_type / model / worktree_path / backend_type / is_active`，`is_active: bool | None = None` 三值语义：`None` 或 `True` 表示活跃，`False` 表示空闲。
- F4: `TeamManager(worktree_manager=None, trace_manager=None)` 提供 `detect_backend` / `create_team` / `get_team` / `get_task_store` / `get_mailbox` / `register_member` / `set_member_idle` / `register_inprocess_handle` / `register_pane_id` / `get_pane_id` / `delete_team` / `get_team_for_teammate` / `on_teammate_completed` 共 13 个公开方法；内部维护 `_teams` / `_task_stores` / `_mailboxes` / `_inprocess_handles` / `_pane_ids` / `_teammate_team_map` / `_detected_backend` 七个字典/缓存；`_detected_backend` 第一次检测后缓存复用。
- F5: `Mailbox(base_dir)` 基于 `<base_dir>/<agent_id>/<timestamp>_<id>.json` 单文件单消息模型：`write(agent_id, msg)` 落盘；`read(agent_id)` 只读不删（按 `sorted(d.iterdir())` 时间序）；`consume(agent_id)` 读完逐个 `f.unlink()` 保证 FIFO；`broadcast(agent_ids, msg, exclude=None)` 按列表逐个 write 排除 exclude；`cleanup(agent_id)` / `cleanup_all()` 清目录。
- F6: `MailboxMessage` dataclass 字段 `id / from_agent / to_agent / content / summary / message_type / timestamp / metadata`；`message_type` 三档 `text / shutdown_request / shutdown_response` 由 `SendMessageTool.VALID_MESSAGE_TYPES` 守门；`text` 类型必须带非空 `summary`（5-10 词）否则报错。
- F7: `create_message(from_agent, to_agent, content, summary="", message_type="text", metadata=None)` 统一构造器，自动填 `id=uuid4().hex[:12]` 和 `timestamp=time.time()`。
- F8: `SharedTaskStore(path)` 基于单文件 `tasks.json`，结构 `{"next_id": int, "tasks": [...]}`；`create / get / list_tasks / update / init_empty` 五方法；`SharedTask` dataclass 字段 `id / title / description / status / assignee / blocks / blocked_by / created_by`，`status` 四档 `pending / in_progress / completed / blocked`；`list_tasks(status=None, assignee=None)` 双过滤；`update` 部分字段更新且 `blocks`/`blocked_by` 列表去重追加；`init_empty` 清空 + `next_id=1` + save。
- F9: `AgentNameRegistry` 进程内单例（线程安全 double-checked locking，`_lock = threading.Lock()`）；类方法 `instance()` / `reset()`；实例方法 `register(name, agent_id)` / `resolve(name_or_id)`（先按 name 查再按 id 反查）/ `unregister(name)` / `list_all()`；内部 `_names: dict[str, str]` 存 name→agent_id。
- F10: `TeamManager.create_team(name, lead_agent_id, description="", teammate_mode="", is_interactive=True)` 链 `detect_backend`（缓存到 `_detected_backend`）→ `unique_team_name`（同名加 `-2/-3/...`）→ `resolve_team_dir` 在 `~/.aixcode/teams/<slug>/` `mkdir` → `AgentTeam(...).save`（config.json）+ `SharedTaskStore.init_empty`（tasks.json）+ 建 `mailbox/` → 缓存 `_teams`/`_task_stores`/`_mailboxes`，返回 `AgentTeam`。
- F11: `TeamManager.delete_team(team_name)` 先校验全员 idle（`is_active is not False` 即视为 active，存在则抛 `TeamError("Cannot delete team: active members: ...")`）；通过后遍历每个 member：`AgentNameRegistry` unregister 名字、in-process handle `cancel`、`_kill_pane`、`worktree_manager` 删该队员 worktree、`trace_manager` remove；最后 `mailbox.cleanup_all` + 删团队目录 + 弹出三个缓存字典。
- F12: `spawn_inprocess_teammate(agent, prompt, name, conversation=None)`：懒导入 `tools.agent_tool.run_to_completion`，无 conversation 时用 `prompt` 构造 `ConversationManager`，`asyncio.create_task(run_to_completion(agent, conv), name=f"teammate-{name}")` 起协程；返 `InProcessTeammateHandle{agent, task, name}`，含 `done` 判完成、`result` 安全取结果（未完成/异常返 None）、`cancel()` 取消未完成 task。
- F13: `spawn_tmux_teammate`（pane 后端，移植 + mock 测试）三级 fallback：先 `split-window -h -t <team>` → 失败则 `new-window` + `split-window` → 再失败则 `new-session -d` + `list-panes` 取首个；用 `build_cli_command` 拼 `AIXCODE_TEAM_NAME=X AIXCODE_TEAMMATE_NAME=Y AIXCODE_MAILBOX_DIR=Z python -m aixcode -p --work-dir <wt> [--agent-type X] [--model X] '<prompt>'`，prompt 内单引号转义为 `'\''`；`send-keys -t <pane> <cmd> Enter` 启动；`kill_pane(pane_id)` / `send_keys_to_pane(pane_id, keys)` best-effort 静默失败。
- F14: `spawn_iterm2_teammate`（pane 后端，移植 + mock 测试）复用 `build_cli_command`，经 `it2 split-pane --command "/bin/zsh -c '<cmd>'"` 创建新 pane，返回 `ITermPaneInfo{session_id}`，失败抛 `ITermSpawnError`（不静默吞）。
- F15: `save_transcript(team_name, agent_id, conv)` / `load_transcript(team_name, agent_id)`：把 `conv.history` 的 `Message` 列表序列化为 JSON（每条 `role/content/tool_calls/tool_call_id`）落 `~/.aixcode/teams/<team>/transcripts/<agent_id>.json`；加载反序列化为 `Message` 列表回填新建 `ConversationManager` 的 `history` 并置 `env_injected = ltm_injected = True`。
- F16: `Agent._consume_mailbox(conversation)`：仅当 `self.team_name and self._team_manager` 非空时取 `team_manager.get_mailbox(team_name).consume(self.agent_id)`；每条消息前缀 `[Message from <from_agent>] `（text 类型）或 `[<message_type> from <from_agent>] ` 后 `conversation.add_user_message`；异常吞掉记 `logger.debug`。在 `Agent.run` 的 `while True` 循环体最开头调用（每轮迭代前）。
- F17: `TeamCreateTool(team_manager, parent_agent, teammate_mode="", is_interactive=True, enable_coordinator_mode=False)` 暴露 `team_name` 必填 + `description` 可选；先 `detect_backend` 不通过返 IsError；通过后 `create_team(team_name, lead_agent_id=parent_agent.agent_id, ...)`，把 `parent_agent.team_name = team.name`（使 Lead 能消费自己邮箱）；若 `is_coordinator_mode(enable_coordinator_mode)` 为真则 `parent_agent.coordinator_mode = True`、`parent_agent._full_registry = parent_agent.registry`、`parent_agent.registry = apply_coordinator_filter(registry)`，输出附 "Coordinator Mode activated"。
- F18: `TeamDeleteTool(team_manager, parent_agent)` 暴露 `team_name` 必填；调 `delete_team` 捕获 `TeamError` 返 IsError；若 `parent_agent.coordinator_mode` 为真则恢复 `parent_agent.registry = parent_agent._full_registry`、清零 flag、清 `parent_agent.team_name`，输出附 "Coordinator Mode deactivated"。
- F19: `SendMessageTool(team_manager, parent_agent)` 暴露 `to / message / summary / message_type / metadata`；先校验 `message_type in VALID_MESSAGE_TYPES`，再校验 `text` 类型必须有 `summary`；`to == "*"` 走 `mailbox.broadcast(member_ids ∪ {lead_agent_id} \ {self.agent_id})`，否则用 `AgentNameRegistry.instance().resolve(to)` 解析目标 id（解析失败返 IsError `Cannot resolve recipient '...'`）；写完对 pane 后端 `_wake_pane(target_id)`（in-process 不需要，靠每轮 `_consume_mailbox`）。
- F20: `AgentTool._execute_as_teammate(p)` 处理 `p.team_name` 非空分支（`execute` 入口优先于 fork/sync/background 分发）：校验 `team_manager`/`worktree_manager` 已装配、`get_team(team_name)` 不存在返 IsError；base_name（`p.name`）同名冲突自动加 `-2/-3/...`；可选解析 `subagent_type`，无 type + `enable_fork` 走 `build_forked_messages` 否则用空白 builtin `AgentDef`；`worktree_manager.create(f"team-{team_name}/{teammate_name}", "HEAD")` 建独立 wt；`detect_backend` 决定后端；`build_teammate_tools(registry, backend)` 构造队员工具池；建 sub-agent 后设 `agent_id`/`team_name`/`_team_manager` 并注入队员说明（addendum）；`AgentNameRegistry.instance().register(teammate_name, agent_id)`；构造 `TeammateInfo` 后 `team_manager.register_member`；按 backend 分发 `spawn_inprocess_teammate`（in-process，并 `task.add_done_callback` 触发 `on_teammate_completed`）或 pane spawn；立即返回 spawn 确认文本（不等队员跑完）。
- F21: 共享任务工具四件——`TaskCreate(title, description="", assignee="", blocks=None, blocked_by=None)`、`TaskGet(task_id)`、`TaskList(status="", assignee="")`、`TaskUpdate(task_id, status="", assignee="", title="", description="", add_blocks=None, add_blocked_by=None)`——均经 `parent_agent` 的 `team_name` 找到 `team_manager.get_task_store(team_name)` 操作；无活跃团队时返 IsError；`created_by` 填 `parent_agent.agent_id`。

## 4. 非功能需求

- N1: `Mailbox` 单文件单消息模型避免跨进程并发写覆盖：文件名 `<timestamp>_<id>.json` 全局唯一，写入无需文件锁；`consume` 按时间排序保证 FIFO；`unlink` 单文件操作不会丢消息。
- N2: `detect_backend` 检测失败不静默回退到 in-process——直接抛 `BackendDetectionError` 让用户显式选择（装 tmux/iTerm2+it2，或 config.yaml 设 `teammate_mode: "in-process"`）。pane 后端提供的进程隔离是团队模式核心保障，静默降级会让用户失去隔离还不自知。
- N3: `AgentNameRegistry` 是进程内单例，故跨进程 pane 队员必须在子进程内自己重注册 name→agent_id（不能依赖 Lead 进程注册表）；`resolve` 同时支持按 name 和按 agent_id 反查（Lead 端用名字、子进程端用 agent_id 都命中）。
- N4: `TeamManager._detected_backend` 一旦检测过即缓存，整个 manager 生命周期不变；同进程内多次 `create_team` 不重新探测环境，保证一致性。
- N5: `_consume_mailbox` 必须放在每轮迭代**开头**（调 LLM 之前），不能放结束——放结束会出现"工具完成→idle→下轮才看到新消息"的一轮延迟；放开头保证 LLM 看到的历史已含队员最新消息。
- N6: `TeamCreateTool` 启用 Coordinator Mode 时必须把原 `registry` 备份到 `parent_agent._full_registry`，`TeamDeleteTool` 恢复时从这里读回——不能重新构造，因 registry 可能已注入运行时动态工具（MCP / Skill）。
- N7: pane 队员场景 `SendMessageTool._wake_pane` 必须 `send-keys` 触发对方读新消息（pane 进程在 `python -m aixcode -p` 单次执行模式会阻塞），否则消息只入 mailbox 对方不感知；in-process 队员不需要 wake（每轮 `_consume_mailbox` 自动跑）。【pane 真实路径本机不验收】
- N8: `build_cli_command` 把 `prompt` 内单引号转义为 `'\''`（关闭→插入字面单引号→重开），否则 prompt 出现单引号破坏 shell 解析；前缀环境变量用空格分隔不加引号，假设值是合法标识符。
- N9: `delete_team` 必须先校验全员 `is_active is False`，活跃成员存在时拒绝删除——避免运行中的 in-process 协程或 pane 进程突然失去 mailbox 悬挂。Active 检查用 `is_active is not False`（`None` 和 `True` 都算 active）。
- N10: 测试运行 `Mailbox`/`AgentTeam.save`/`create_team` 必须 `monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)` 重定向 home，否则跑完会在用户主目录残留 `~/.aixcode/teams/` 污染。
- N11: `AgentNameRegistry.reset()` 在 pytest autouse fixture 中每用例前调用——单例跨用例共享会让 register 状态泄漏。
- N12: in-process 队员的 idle 通知经 `asyncio.Task.add_done_callback`：队员 task 完成（正常或异常）时回调 `team_manager.on_teammate_completed(agent_id)` → `set_member_idle`（翻 `is_active=False` + 写 `Teammate '<name>' is now idle.` 到 Lead 邮箱）。done_callback 内异常吞掉不传播。
- N13: `_execute_as_teammate` 必须**立即返回** spawn 确认（不 await 队员跑完），让 Lead 继续与用户/其他队员交互；队员完成经 mailbox idle 通知异步告知 Lead。

## 5. 设计概要

- 包结构 `aixcode/teams/`：
  - `models.py`：`BackendType`、`TeammateInfo`、`_sanitize_name`、`AgentTeam`、`resolve_team_dir`（`~/.aixcode/teams/<slug>/`，用 `Path.home()`）、`unique_team_name`。
  - `mailbox.py`：`MailboxMessage`、`Mailbox`、`create_message`。
  - `backend_detect.py`：`BackendDetectionError`、`_in_tmux_session`/`_in_iterm2`/`_it2_available`/`_tmux_installed`、`detect_backend`。
  - `shared_task.py`：`SharedTask`、`SharedTaskStore`。
  - `registry.py`：`AgentNameRegistry`（线程安全单例）。
  - `spawn_inprocess.py`：`InProcessTeammateHandle`、`spawn_inprocess_teammate`（懒导入 `run_to_completion`）。
  - `spawn_tmux.py`：`TmuxPaneInfo`、`TmuxSpawnError`、`_run_tmux`、`build_cli_command`、`spawn_tmux_teammate`、`send_keys_to_pane`、`kill_pane`。
  - `spawn_iterm2.py`：`ITermPaneInfo`、`ITermSpawnError`、`_run_it2`、`spawn_iterm2_teammate`。
  - `transcript.py`：`_serialize_message`/`_deserialize_message`、`save_transcript`、`load_transcript`。
  - `manager.py`：`TeamError`、`TeamManager`。
  - `coordinator.py`：`is_coordinator_mode`（双开关：flag false 直接 false；true 时读 `AIXCODE_COORDINATOR_MODE` ∈ `{1,true,yes}`）、`get_coordinator_system_prompt`（含 Research/Synthesis/Implementation/Verification 四阶段引导 + `based on your findings` anti-pattern；提示词层引导，工具层不强制）。
  - `__init__.py`：导出对外符号。
- 工具：`tools/send_message.py`(`SendMessageParams`/`VALID_MESSAGE_TYPES`/`SendMessageTool`)、`tools/team_create.py`(`TeamCreateParams`/`TeamCreateTool`)、`tools/team_delete.py`(`TeamDeleteParams`/`TeamDeleteTool`)、`tools/task_create.py`/`task_get.py`/`task_list.py`/`task_update.py`（共享任务四件，均持 `team_manager`+`parent_agent`）。
- 改动：`agents/tool_filter.py`(加 `COORDINATOR_MODE_ALLOWED_TOOLS`/`TEAMMATE_COORDINATION_TOOLS`/`IN_PROCESS_TEAMMATE_ALLOWED_TOOLS`/`apply_coordinator_filter`/`build_teammate_tools`)、`agent.py`(`__init__` 加 `agent_id`/`team_name`/`coordinator_mode`/`_team_manager` 四字段 + `_consume_mailbox` + run 主循环钩入 + `build_system_prompt(coordinator_mode=...)`)、`tools/agent_tool.py`(`AgentToolParams` 加 `team_name`/`name`；`__init__` 加 `team_manager`；`execute` 入口分支；`_execute_as_teammate`)、`prompts.py`(`build_system_prompt` 加 `coordinator_mode` 参数)、`config.py`(`load_team_settings`)、`__main__.py`(装配 `TeamManager` + 注册七工具 + 写回 `agent._team_manager`/`agent.agent_id` + 透传 `teammate_mode`/`enable_coordinator_mode`)。
- 主流程（按生命周期）：
  1. 创建：用户 → Lead → LLM 调 `TeamCreate(team_name="X")` → `detect_backend`（本机 in-process）→ `create_team` 落盘 → 可选切 Coordinator Mode（备份 `_full_registry` + `apply_coordinator_filter`）。
  2. Spawn 队员：Lead 调 `Agent(team_name="X", name="alice", prompt=...)` → `AgentTool.execute` 见 `team_name` 走 `_execute_as_teammate` → 校验团队、解析 type/fork、`worktree_manager.create("team-X/alice")` 建 wt、`build_teammate_tools` 构造工具池、设队员 `agent_id`/`team_name`/`_team_manager`、`register_member` + name registry register → in-process `spawn_inprocess_teammate` + done_callback。
  3. 通信：队员调 `SendMessage(to="bob", message=..., summary=...)` → `resolve("bob")` → target_id → `mailbox.write` →（pane 需 `_wake_pane`）→ 对方下一轮 `_consume_mailbox` 拿到。
  4. 各 Agent 每轮：`Agent.run` 循环开头 `_consume_mailbox` 把自己邮箱消息转 user message 注入对话。
  5. idle 通知：in-process 队员 task done_callback → `on_teammate_completed(agent_id)` → `set_member_idle`（`is_active=False` + 写 idle 消息到 Lead 邮箱）→ Lead 下一轮 `_consume_mailbox` 收到。
  6. Coordinator Mode：`apply_coordinator_filter(registry)` 筛到 12 项白名单；`TeamDelete` 恢复 `_full_registry`。
  7. 关闭：`TeamDelete(team_name="X")` → `delete_team` → 校验全员 idle → 遍历 member 清 name registry / cancel handle / kill pane / 删 worktree / trace remove → cleanup mailbox + 删目录 + 弹三缓存。
- 调用链（模块层级）：`__main__.py` 建 `TeamManager(worktree_manager, trace_manager)` → 传 `AgentTool(team_manager=...)` → 注册 `TeamCreate/TeamDelete/SendMessage/TaskCreate/TaskGet/TaskList/TaskUpdate` → `agent._team_manager = team_manager`、`agent.agent_id` 已在构造时生成；LLM 调工具 → registry → `team_manager` 服务；`AgentTool._execute_as_teammate` 调 worktree/build_teammate_tools/spawn/register。
- 与其他模块交互：依赖 `agent`（Agent 实例 / 模块 `run_to_completion` / 系统提示）、`conversation`（`ConversationManager`/`Message`）、`agents/tool_filter`（`apply_coordinator_filter`/`build_teammate_tools`/白名单）、`worktree`（每队员独立 worktree）、`tools.base`（`Tool`/`ToolResult`/`ToolRegistry`）；底层只 `asyncio`+`subprocess`(tmux/it2)+标准库(`uuid`/`time`/`json`/`pathlib`/`threading`/`shutil`/`os`)+`pydantic`(工具 schema)。被 `__main__.py`（装配）、`tools/agent_tool.py`（`_execute_as_teammate`）、`prompts.py`（`build_system_prompt(coordinator_mode=...)`）调用。

## 6. Out of Scope

- 真实 pane 后端启动（tmux/iTerm2 实际拉起子进程）与 `python -m aixcode -p --work-dir --agent-type --model` 单次执行 CLI flag 解析——本机无 Unix 环境验收，仅移植代码 + mock 单测；待有 Unix 环境补 `__main__` 的 argparse 入口。
- `SyntheticOutputTool` 与协调模式"强制四阶段工作流"——`get_coordinator_system_prompt` 仅提示词层引导，工具层不强制顺序，coordinator 用普通正文综合。
- `planModeRequired` 字段与审批工作流——`TeammateInfo` 只保留基础元信息。
- `shutdown_response` 完整双向握手协议——只保留 `message_type` 三档枚举，握手语义由 LLM 在文本层约定。
- 共享任务依赖图拓扑排序自动调度——`SharedTask.blocks/blocked_by` 字段已存但 store 仅 CRUD，依赖推断由 Lead LLM 从任务列表文本读出。
- 队员"从磁盘恢复对话续写"resume——transcript 落盘仅供事后回看，要复用需重新 spawn。
- `AIXCODE_COORDINATOR_MODE` 自动激活——必须 `enable_coordinator_mode=True` 配合 env 双开关同时打开才生效。
- mailbox 跨节点分布式同步——只在单机内运作。
- pane 队员的 idle 自动检测与崩溃自动重启——pane 队员需自行 `SendMessage` 告知 idle，崩溃需手动 `TeamDelete` 重建。

## 7. 完成定义

见 [checklist.md](checklist.md)，所有条目勾上即完成（§4 端到端的真实 TUI 项与 pane 后端真实启动留 Out of Scope / 用户手动验收）。
