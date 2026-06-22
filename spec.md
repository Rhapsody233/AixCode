# ch13: SubAgent 系统 Spec（AixCode / Python 版）

> 本文件自包含。新对话冷启动时，先读「§0 全局背景」明确**全局目标**，再看「§0 末 + §2」明确 ch13 **当前目标**，然后按 [tasks.md](tasks.md) 顺序、配 [checklist.md](checklist.md) 验收开发。
> 本章把「开一个上下文隔离的子 Agent 去做一件事」做成主 Agent 可直接调用的 **`Agent` 工具**：按 `subagent_type` 启专家子 Agent（系统提示/模型/工具白名单按 Markdown 定义），或不带类型时 **fork 当前对话**跑临时子 Agent；支持**前台同步 / 后台异步 / fork(强制后台)** 三路径，后台完成经 `<task-notification>` 异步注入主对话。

## 0. 全局背景（每章都要先理解）

**项目**：AixCode —— 一个用 **Python** 写的终端 AI 编程助手（对标 Claude Code），后端用 **Deepseek**（OpenAI 兼容 chat/completions 协议，`config.yaml` 四字段 `protocol/model/base_url/api_key`；验收用 `model: deepseek-chat`）。逐章构建，每章交付 `spec.md / tasks.md / checklist.md` 三件套（覆盖项目根目录）。

**运行环境**：Windows + PowerShell（主力；Bash 工具也可用）；**当前不是 git 仓库**；Python 3.10+（实跑 3.14）；UTF-8 输出已在入口 `sys.stdout.reconfigure` 处理。

**工作方式**：可测单元一律 **TDD**（先写失败测试→看红→最小实现→转绿，沿用仓库约定：纯 pytest 函数 + `asyncio.run`，不引入 pytest-asyncio、不用测试类）；每章末尾必有「接入主流程」+「端到端验证」；改动外科手术式、最小化。

**已完成章节（现有代码结构，包名 `aixcode/`）**：
- ch01 对话通道：`config.py`(`ProviderConfig` + `load_config`；`load_mcp_servers`；`load_raw_hooks` 读 `config.yaml`)、`client.py`(`LLMClient` ABC + `OpenAIClient` 异步流式 `stream`，产 `TextDelta/ThinkingDelta/ToolCallComplete/StreamEnd`；`create_client(ProviderConfig)`)、`conversation.py`(`Message`：扁平结构 `role/content/tool_calls/tool_call_id`；`ConversationManager`：`add_user_message/add_assistant_message/add_tool_result/add_system_reminder/inject_environment/replace_history/last_input_tokens/serialize/history`)、`app.py`、`__main__.py`。
- ch03 工具系统：`tools/`包（`Tool` ABC：类属性 `name/description/params_model/category(read|write|command)/should_defer/is_system_tool/is_concurrency_safe` + async `execute`；`ToolResult(output, is_error)`；`ToolRegistry`：`register/get/list_tools`；6 核心工具 `ReadFile/WriteFile/EditFile/Bash/Glob/Grep` + `ToolSearch/AskUser`；`create_default_registry`）。
- ch04 Agent Loop：`agent.py`——`Agent.run(conversation)` 多轮 ReAct，产 `AgentEvent` 异步流（`StreamText/ThinkingText/ToolUseEvent/ToolResultEvent/UsageEvent/LoopComplete(text)/TurnComplete/ErrorEvent/PermissionRequest/CompactNotification/HookEvent`）；`Agent.__init__(client, registry, protocol, work_dir, max_iterations, permission_checker, context_window, memory_manager, hook_engine)`；工具批量执行 `partition_tool_calls`，权限/钩子拒绝走 `denied: dict[tool_id, ToolResult]`。
- ch05 Prompt：`prompts.py`(`build_system_prompt / build_environment_context(work_dir, skill_catalog) / build_plan_mode_reminder / build_active_skills_reminder`)。
- ch06 权限：`permissions/`包（`PermissionMode` 枚举五档 `STRICT/DEFAULT/ACCEPT_EDITS/BYPASS/PLAN` / `DangerousCommandDetector` / `PathSandbox(project_root)` / 三层 `RuleEngine` / `PermissionChecker(detector, sandbox, rule_engine, mode)`）。
- ch07 MCP：`mcp/`包；MCP 工具名以 `mcp_` 前缀。
- ch08 上下文管理：`context/`包（auto_compact 等）。
- ch09 记忆：`memory/`包（`MemoryManager` / `SessionManager`）。
- ch10 Slash Command：`commands/`包（`CommandRegistry`：`register_sync/find/list_commands/unregister`；`Command`/`CommandContext`/`CommandType(LOCAL|LOCAL_UI|PROMPT)`/`UIController`；`parse_command`/`complete`；`SlashCommandCompleter`；`handlers/`：help/clear/status/compact/plan/do/mode/session/memory/review/skill 共 11 内置 + `ALL_COMMANDS`/`register_all_commands`；`handlers/mode.py` 的 `parse_mode_name(name)->PermissionMode|None`）。app 实现 `UIController`、`_dispatch_command`、`_build_command_context`（config 闭包：registry/version/set_session/clear_chat/skill_loader/skill_executor）。
- ch11 Skill：`skills/`包（`SkillLoader` 三级搜索 / `SkillExecutor` inline·fork / 目录型工具 / `filter_tool_registry`）+ `tools/load_skill.py`(`LoadSkill`)；Agent 有 `active_skills`/`_skill_catalog`/`activate_skill`/`set_skill_catalog`。
- ch12 Hook：`hooks/`包（`LifecycleEvent` 15 事件 / `Action`/`Hook`/`HookContext`/`Condition`/`ConditionGroup`/`parse_condition` / `HookEngine`：`run_hooks`/`run_pre_tool_hooks`/`get_prompt_messages`/`drain_notifications` / `load_hooks` 校验 / 4 执行器）；`Agent` 有 `hook_engine` 字段 + 8 个 loop 触发点 + `HookEvent`；app 起止派发 startup/shutdown，`__main__` 装配 `HookEngine`。**注：ch12 落地完成，仅 checklist §4 的 2 项真实 TUI 验收待用户手动（见本章 checklist §6「上一章遗留手动验收」）。**

**ch13 当前目标**：① 落地 `aixcode/agents/` 包（parser / loader / tool_filter / fork / trace / task_manager / notification）+ `aixcode/tools/agent_tool.py`(`AgentTool`)；② `AgentTool` 注册进主 registry 被 LLM 当普通工具调用，按 `subagent_type` 启**定义式专家子 Agent**（Markdown 定义），或不带类型时 **fork 当前对话**；③ 三执行路径 **sync(前台阻塞) / background(asyncio task 立即返回 Task ID) / fork(强制后台)**；④ `TaskManager` 跟踪后台子 Agent 生命周期，完成经 `<task-notification>` 注入主对话；⑤ **四层工具过滤**防递归失控；⑥ `TraceManager` 父子调用树追踪 + `/trace`；⑦ `/tasks` 管理后台任务；⑧ 接入 app/__main__ 装配 + 主循环 poll + 中断挂后台。

**与 MewCode 参考的关键差异（AixCode 适配，已与用户确认）**：
- **砍掉 worktree 隔离与 team 团队成员**两条可选路径（本项目非 git；teams 留后续）；`AgentTool` 去掉 `isolation`/`team_name`/`name` 参数，对应 F8/F9/T11/T12 不做。
- **模型路由保留两档**：`model ∈ {inherit, deepseek-chat, deepseek-pro}`（`deepseek-chat`=Deepseek V4、`deepseek-pro`=V4pro）；运行时模型覆盖 = 复制父 `ProviderConfig` 换 `model` 字段 → `create_client`；不引入 haiku/sonnet/opus 别名表。
- **保留 TraceManager + `/trace`**。
- **fork 适配 AixCode 扁平 `Message`**：`copy.deepcopy(history)`；对带 `tool_calls` 但缺对应 `tool` 结果消息的 assistant 消息，补 `role="tool"` 的 `"interrupted"` 占位结果；嵌套 fork 通过扫描 history 内容含 `FORK_BOILERPLATE_TAG` 拒绝。
- **`run_to_completion` 复用 ch11 fork 执行器写法**：内部驱动 `sub_agent.run(conversation)` 异步流，累计 `StreamText`、到 `LoopComplete` 取最终文本返回。
- **基础设施共享、运行态隔离**：子 Agent 复用父 `hook_engine`、`provider_config`、文件系统；独立 `ConversationManager`、独立 `PermissionChecker`（`PathSandbox` 按子 `work_dir` 重建）、独立 token 计数与 `_loop_count`。
- **agent catalog 走工具描述**：可用子 Agent 类型清单在 `AgentTool.__init__` 时由 loader 写进工具 `description`（而非 MewCode 的 `set_agent_catalog` 注入系统提示），少改 agent.py。
- 装配分两处（`__main__` 建 registry/managers/Agent，`app` 持 task_manager 在 REPL 主循环 poll + 中断挂后台 + 注册 `/tasks`·`/trace`）；权限模式取值复用 ch10 `parse_mode_name` 语义（`strict/default/accept/bypass`）。
- 测试纯 pytest 函数 + `asyncio.run`；验证 `compileall` + `pytest`（不假设 ruff）；三件套放仓库根；无 git commit 项。

## 1. 背景

主 Agent 做大任务时会塞满上下文：研究、规划、写代码、跑测试堆在一个对话里，单窗口很快耗尽。把「开一个上下文隔离的新 Agent 去做一件事」做成主 Agent 可调用的工具，让主 Agent 学会分发工作、避免上下文污染，并通过专门角色（Plan / Explore）和后台异步执行扩展并发。

## 2. 目标

提供 `Agent` 工具：主 Agent 在对话里写一次工具调用即可：1) 按 `subagent_type` 启动定义式专家子 Agent（系统提示/模型/工具白名单按 Markdown 定义）；2) 不带 `subagent_type` 且 `enable_fork=True` 时 fork 当前对话上下文跑临时子 Agent（强制后台）；3) `run_in_background=True` 或定义 `background: true` 时后台执行立即返回 Task ID。后台任务完成经 `<task-notification>` 反馈主 Agent。`TraceManager` 记录父子调用树，`/tasks`·`/trace` 供用户查看。

## 3. 功能需求

### 3.1 定义与加载（agents/parser.py、agents/loader.py）

- F1: `@dataclass AgentDef` 字段：`agent_type / when_to_use / system_prompt / tools / disallowed_tools / model / max_turns / permission_mode / background / file_path / source`（11 字段；默认 `model="inherit" / max_turns=50 / permission_mode="default" / background=False / tools=[] / disallowed_tools=[]`）。
- F2: `parse_frontmatter(raw) -> (meta, body)` 处理 `---\n<yaml>\n---\n<body>`；`parse_agent_file(path, source) -> AgentDef`：`name`→agent_type、`description`→when_to_use、body→system_prompt、`tools`/`disallowedTools`/`model`/`maxTurns`/`permissionMode`/`background` 映射。校验：缺 `name`/`description` 抛 `AgentParseError`；`model ∉ VALID_MODELS={"inherit","deepseek-chat","deepseek-pro",""}` 抛；`permissionMode ∉ VALID_PERMISSION_MODES={"","strict","default","accept","bypass"}` 抛；`maxTurns` 非正抛；YAML 失败抛。
- F3: `AgentLoader(work_dir, enable_verification=False)`：`PROJECT_AGENTS_DIR=".aixcode/agents"`、`USER_AGENTS_DIR="~/.aixcode/agents"`；`load_all()` 顺序 项目(`source="project"`)→用户(`source="user"`)→内置(`importlib.resources.files("aixcode.agents.builtins")`，`source="builtin"`)，首次出现 name 占位、同名跳过（项目覆盖内置）；坏文件 try/except + `log.warning` 跳过；`get(name)` 命中重读源文件热重载、失败回退缓存；`list_agents()`；`enable_verification=False` 时不加载 `verification` 内置；`get_catalog() -> list[(name, when_to_use)]`。
- F4: 三档内置（`aixcode/agents/builtins/*.md`）：
  - `general-purpose`：通用全能，`model: inherit`，无额外限制。
  - `plan`：只读规划，`disallowedTools: [Agent, EditFile, WriteFile]`、`maxTurns: 15`、`permissionMode: strict`、`model: deepseek-pro`。
  - `explore`：代码探索，`tools: [ReadFile, Grep, Glob]`、`maxTurns: 30`、`model: deepseek-chat`。
  - （可选）`verification`：找最后 20% bug，`enable_verification` flag 守，默认不出现在列表。

### 3.2 四层工具过滤（agents/tool_filter.py）

- F5: 常量：`ALL_AGENT_DISALLOWED_TOOLS = frozenset({"Agent", "AskUser"})`（防递归 + 禁交互式提问）；`CUSTOM_AGENT_DISALLOWED_TOOLS = frozenset({"LoadSkill"})`（非 builtin 来源额外禁）；`ASYNC_AGENT_ALLOWED_TOOLS = frozenset({"ReadFile","WriteFile","EditFile","Bash","Glob","Grep","ToolSearch","LoadSkill"})`（后台白名单）。
- F6: `resolve_agent_tools(registry, definition, is_background) -> ToolRegistry`（返回新 `ToolRegistry`，复用 ch11 `filter_tool_registry` 同款重建思路）：
  1. MCP 工具（`mcp_` 前缀）一律直通、不受任何层约束；
  2. 全局禁 `ALL_AGENT_DISALLOWED_TOOLS`；
  3. `definition.source != "builtin"` 时再禁 `CUSTOM_AGENT_DISALLOWED_TOOLS`；
  4. `is_background=True` 时只保留 `ASYNC_AGENT_ALLOWED_TOOLS`（+ MCP）；
  5. 定义级：`definition.tools` 非空则只保留白名单（+ MCP）；再去掉 `definition.disallowed_tools`。

### 3.3 Fork（agents/fork.py）

- F7: `FORK_BOILERPLATE_TAG = "<fork_boilerplate>"`；`FORK_BOILERPLATE`（含该 tag + 强硬指令：不能再 fork / 不要主动对话 / 不要请求确认 / 直接用工具干活 / 最终报告控字数且结构化）；`ForkError(Exception)`；`build_forked_messages(conversation, task) -> ConversationManager`：① 扫 `conversation.history` 任意 `msg.content` 含 `FORK_BOILERPLATE_TAG` → `raise ForkError("Cannot fork from a forked agent.")`；② `copy.deepcopy(history)` 复制到新 `ConversationManager`（byte-exact，保 prompt cache）；③ 对带 `tool_calls` 但无对应 `tool` 结果的 assistant 消息，补 `add_tool_result(tool_call_id, "interrupted")` 占位；④ `add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")`。

### 3.4 追踪与后台（agents/trace.py、agents/task_manager.py、agents/notification.py）

- F8: `@dataclass TraceNode`(`agent_id / parent_id / trace_id / agent_type / status / input_tokens / output_tokens / start_time / end_time`)；`TraceManager`：`create(agent_type, parent_id=None, trace_id=None) -> TraceNode`（`agent_id`=uuid hex 12 位；无 `trace_id` 自动生成）/ `update(agent_id, **kw)` / `complete(agent_id, status)`（写 `end_time`）/ `get_tree(trace_id) -> list[TraceNode]` / `get_total_tokens(trace_id) -> (in, out)`；操作不存在 ID 时 no-op。
- F9: `@dataclass BackgroundTask`(`task_id / agent_type / status / result / error / input_tokens / output_tokens / start_time / end_time`，状态 `running/completed/failed/cancelled`)；`TaskManager`：`_tasks: dict`、`_async_tasks: dict[str, asyncio.Task]`、`_notify_queue: asyncio.Queue`；`launch(coro_factory, agent_type) -> str`（建 `asyncio.create_task(self._run_background(...))` 立即返回 task_id，完成把 task_id 入队）/ `_run_background` 捕获异常置 `failed`/`cancelled` / `adopt_running(task_id, agent_type, partial)` 把正在跑的实例挂为后台 / `get/list_tasks/cancel(task_id)`（仅 `running` 有效，`asyncio.Task.cancel()`）/ `poll_completed() -> list[BackgroundTask]`（`get_nowait` 抽空队列）。
- F10: `MAX_NOTIFICATION_RESULT_LENGTH = 5000`；`format_task_notification(task) -> str`：`<task-notification>` 标签包裹，含 `Task ID / Agent / Status / Elapsed / Tokens / Result`；result 超 5000 字符截断为 `...\n... (truncated)`；`inject_task_notifications(conversation, completed) -> None`：每个 task 包成 user message 追加到 conversation。

### 3.5 AgentTool（tools/agent_tool.py）

- F11: `AgentToolParams(BaseModel)`：`prompt: str`、`description: str`（必填）；`subagent_type: str = ""`、`model: str = ""`、`run_in_background: bool = False`（可选）。
- F12: `AgentTool(Tool)`：`name="Agent"`、`category="command"`、`is_concurrency_safe=False`、`is_system_tool=False`；`__init__(agent_loader, task_manager, trace_manager, parent_agent, provider_config, enable_fork=False)`；`description` 在 `__init__` 由 `agent_loader.get_catalog()` 动态拼出（列可用 `subagent_type` + 用途 + fork 说明）。
- F13: `AgentTool.execute(params)` 三路径分发：
  - `subagent_type` 给但 `loader.get` 返 None → 错误结果列出可用类型；
  - `subagent_type == ""`：fork 路径（`enable_fork=False` 时报错）；`build_forked_messages` → 强制后台 → `task_manager.launch`；
  - 否则定义式：`is_background = run_in_background or definition.background`；`resolve_agent_tools` 过滤工具 → `_build_sub_agent`（独立 PermissionChecker、模型路由、复用父 hook_engine）→ background 走 `task_manager.launch` 返回 `Task ID: ...`；sync 走 `await run_to_completion(task)` 返回最终文本；
  - 每次 spawn 经 `trace_manager.create(...)` 建节点，完成/失败 `complete(...)`；前台异常标 `failed` 并返回错误结果。
- F14: 模型路由 `_select_model(params, definition)`（`params.model` > `definition.model`(≠inherit) > None=继承父 client）+ `_create_client_for_model(model)`（复制 `provider_config` 换 `model` → `create_client`；失败回退父 client）；`run_to_completion(sub_agent, task) -> str` 驱动 `sub_agent.run` 收 `LoopComplete` 文本。
- F15: 权限：`PERMISSION_MODE_MAP` 复用 ch10 `parse_mode_name` 把 `strict/default/accept/bypass` 映射成 `PermissionMode`；子 Agent 用**独立** `PermissionChecker`（`PathSandbox(project_root=sub_work_dir)`，与父共享 detector/rule_engine 类型但实例独立），`permission_mode` 覆盖不污染父。

### 3.6 命令与接入（commands/handlers、app.py、__main__.py）

- F16: `/tasks list | view <id> | cancel <id>`（`commands/handlers/tasks.py`，`TASKS_COMMAND` 加入 `ALL_COMMANDS`）：list 列后台任务（id/类型/状态/token/用时）；view 出单任务详情含 result；cancel 调 `task_manager.cancel`。
- F17: `/trace [trace_id]`（`commands/handlers/trace.py`，`TRACE_COMMAND` 加入 `ALL_COMMANDS`）：无参列最近 trace；带 id 出调用树（父子缩进 + token 汇总）。
- F18: `__main__.py` 装配：建 `AgentLoader(cwd).load_all()` / `TaskManager()` / `TraceManager()`；建 `AgentTool(loader, task_manager, trace_manager, parent_agent=agent, provider_config=config, enable_fork=True)` 并 `registry.register`（在建 Agent 后注入 parent_agent，或用 setter 注入，避免先后依赖）；把 `task_manager`/`trace_manager` 传入 `AixCodeApp`。
- F19: `app.py` 接入：`AixCodeApp.__init__` 持 `task_manager`/`trace_manager`；`CommandContext.config` 塞 `"task_manager"`/`"trace_manager"`；REPL 主循环每轮 `_run_turn` 前 `completed = task_manager.poll_completed()`，非空则 `inject_task_notifications(conversation, completed)` 注入下一轮；中断路径（`_run_turn` 的 CancelledError）调 `task_manager.adopt_running(...)` 把当前正在跑的子任务挂后台而非杀掉。

## 4. 非功能需求

- N1: 子 Agent 不能再调 `Agent` 工具（防无限递归 / 上下文爆炸）——任意层级经 `ALL_AGENT_DISALLOWED_TOOLS` 屏蔽。
- N2: 后台 Agent 经 `asyncio.Task.cancel()` 受控；取消后状态 `cancelled`。
- N3: `TaskManager` 在 asyncio 单线程模型下顺序安全；`_tasks`/`_async_tasks`/`_notify_queue` 在事件循环内访问。
- N4: fork 必须先扫父对话 `FORK_BOILERPLATE_TAG` 字面量，命中即 `raise ForkError`。
- N5: sync 路径 `await` 子 Agent 跑到底不丢消息；异常把 `trace_node` 标 `failed` 再向上反馈为错误结果（不崩主流程）。
- N6: fork 子 Agent 复用父池工具与对话内容（含 thinking），请求前缀尽量字节级一致以命中 prompt cache。
- N7: 子 Agent 的 `PermissionChecker` 必须独立实例，`permission_mode` 覆盖不污染父权限状态。
- N8: 接入无死代码：`AgentTool`/`task_manager.poll_completed`/`adopt_running`/`/tasks`/`/trace` 都有真实调用方；子 Agent 复用父 `hook_engine` 而非新建。
- N9: 基础设施共享、运行态隔离：子 Agent 独立 `ConversationManager`/token 计数/`_loop_count`，共享 client provider 配置与 hook 引擎与文件系统。

## 5. 设计概要

- 包结构 `aixcode/agents/`：`parser.py`(AgentDef / parse_frontmatter / parse_agent_file / 校验常量 / AgentParseError)、`loader.py`(AgentLoader + 三级路径 + 热重载 + verification flag)、`tool_filter.py`(四张 frozenset + resolve_agent_tools)、`fork.py`(FORK_BOILERPLATE(_TAG) / ForkError / build_forked_messages)、`trace.py`(TraceNode / TraceManager)、`task_manager.py`(BackgroundTask / TaskManager)、`notification.py`(format_task_notification / inject_task_notifications)、`builtins/`(general-purpose / plan / explore [/ verification])。
- `aixcode/tools/agent_tool.py`：AgentToolParams / AgentTool / PERMISSION_MODE_MAP / run_to_completion / _build_sub_agent / _select_model / _create_client_for_model。
- `aixcode/commands/handlers/`：`tasks.py`(TASKS_COMMAND) + `trace.py`(TRACE_COMMAND) + `__init__.py` 加入 ALL_COMMANDS。
- 改动：`app.py`(task_manager/trace_manager 字段 + 主循环 poll + 中断 adopt + config 闭包)、`__main__.py`(装配)。
- 主流程：
  1. 启动（`__main__`）：建 registry（含核心工具/ToolSearch/AskUser/LoadSkill）→ 建 Agent（含 hook_engine/memory）→ 建 `AgentLoader.load_all()`/`TaskManager`/`TraceManager` → 建 `AgentTool(..., parent_agent=agent, enable_fork=True)` 并注册进 registry → 传 task_manager/trace_manager 给 `AixCodeApp`。
  2. 同步 spawn：主 Agent LLM 输出 `Agent` 工具调用 → `execute` → 解析 `subagent_type` → `resolve_agent_tools` → 独立 `PermissionChecker` + 模型路由 → `_build_sub_agent` → `await run_to_completion(prompt)` → 返回文本（同时 trace 记录）。
  3. 后台 spawn：同上但 `is_background` → `task_manager.launch` 立即返回 `Task ID`；完成把 id 入 `_notify_queue`。
  4. fork：扫 `FORK_BOILERPLATE_TAG` 拒绝嵌套 → `build_forked_messages` → 工具四层过滤 → 强制后台 → 通知。
  5. 主循环：每轮 `_run_turn` 前 `poll_completed` + `inject_task_notifications` 把 `<task-notification>` 灌进对话；中断时 `adopt_running` 挂后台。
- 调用链：`__main__` → AgentLoader/TaskManager/TraceManager → AgentTool（注册）；`AgentTool.execute` → resolve_agent_tools / build_forked_messages / _build_sub_agent / task_manager.launch / trace_manager.create；`app._repl_loop` → poll_completed + inject_task_notifications / adopt_running。
- 与其他模块交互：依赖 `agent`(建子 Agent)、`conversation`(forked 对话)、`tools`(注册+过滤)、`client`(model 路由 create_client)、`permissions`(独立 Checker)、`hooks`(复用父引擎)；被 `app`/`__main__` 调用。

## 6. Out of Scope

- worktree 隔离 / `WorktreeManager`（本项目非 git，砍掉）。
- team 团队成员 / `TeamManager` / pane backend（留后续章节）。
- `isolation` / `team_name` / `name` 入参（随上面两块一并去掉）。
- haiku/sonnet/opus 别名表（Deepseek 单家，仅 `inherit`/`deepseek-chat`/`deepseek-pro`）。
- 子 Agent 输出落盘 / 持久化后台恢复 / 120s 自动超时切后台。
- `AgentDef` 不消费 `skills`/`hooks`/`mcpServers`/`memory` 等字段（运行时不落地，留后续）。
- `PermissionMode.PLAN` 的复杂裁剪与 bubble。

## 7. 完成定义

见 [checklist.md](checklist.md)，所有条目勾上即完成。
