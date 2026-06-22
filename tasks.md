# ch13: SubAgent 系统 Tasks（AixCode / Python 版）

> 顺序执行。可测单元一律 **TDD**（先写失败测试→看红→最小实现→转绿），测试统一进 `tests/test_subagent.py`，沿用仓库约定（纯 pytest 函数 + `asyncio.run`，不用测试类、不引 pytest-asyncio）。
> 每完成一个任务跑 `python -m compileall aixcode tests` + `python -m pytest tests/test_subagent.py -q`；接入主流程的任务（T12）做完立刻补端到端验证（T13）再继续。
> 全局背景与已完成章节、AixCode 适配差异见 [spec.md](spec.md) §0。前置：ch01–ch12 已交付（全量 502 passed）。验收后端 `model: deepseek-chat`。

## T1: AgentDef dataclass + 三档内置 Markdown

- 影响文件: `aixcode/agents/__init__.py`（新建）、`aixcode/agents/parser.py`（AgentDef 部分）、`aixcode/agents/builtins/{general-purpose,plan,explore}.md`、`aixcode/agents/builtins/__init__.py`（空）、`pyproject.toml`（package-data）、`tests/test_subagent.py`（新建）
- 依赖任务: 无
- 完成标准（TDD）:
  - `@dataclass AgentDef` 11 字段：`agent_type / when_to_use / system_prompt / tools / disallowed_tools / model / max_turns / permission_mode / background / file_path / source`；默认 `model="inherit" / max_turns=50 / permission_mode="default" / background=False / tools=[] / disallowed_tools=[]`。
  - `general-purpose.md`：`model: inherit`，无额外限制。
  - `plan.md`：`disallowedTools: [Agent, EditFile, WriteFile]`、`maxTurns: 15`、`permissionMode: strict`、`model: deepseek-pro`。
  - `explore.md`：`tools: [ReadFile, Grep, Glob]`、`maxTurns: 30`、`model: deepseek-chat`。
  - `pyproject.toml` 把 `aixcode.agents.builtins` 的 `*.md` 纳入 package-data（已用 `packages.find=["aixcode*"]`，补 `[tool.setuptools.package-data]` 一行）。
- 测试: AgentDef 默认值；三档 .md 能被后续 loader 读到（T3 验证内容）。

## T2: parse_frontmatter + parse_agent_file + 校验

- 影响文件: `aixcode/agents/parser.py`、`tests/test_subagent.py`
- 依赖任务: T1
- 完成标准（TDD）:
  - 常量 `VALID_MODELS={"inherit","deepseek-chat","deepseek-pro",""}`、`VALID_PERMISSION_MODES={"","strict","default","accept","bypass"}`；异常 `AgentParseError`。
  - `parse_frontmatter(raw) -> (meta, body)` 处理 `---\n<yaml>\n---\n<body>`；缺起始/未闭合/非 dict 抛 `AgentParseError`。
  - `parse_agent_file(path, source="builtin") -> AgentDef`：`name`→agent_type、`description`→when_to_use、body→system_prompt、`tools`/`disallowedTools`/`model`/`maxTurns`/`permissionMode`/`background` 映射；缺 `name`/`description` 抛；`model`/`permissionMode` 取值非白名单抛；`maxTurns` 非正抛；读盘失败抛。
- 测试: valid / 缺 name / 缺 description / 非法 model / 非法 permissionMode / 非正 maxTurns / 坏 yaml / 文件不存在；frontmatter 边界。

## T3: AgentLoader 三级搜索 + 热重载 + verification flag

- 影响文件: `aixcode/agents/loader.py`、`tests/test_subagent.py`
- 依赖任务: T2
- 完成标准（TDD）:
  - `PROJECT_AGENTS_DIR=".aixcode/agents"`、`USER_AGENTS_DIR="~/.aixcode/agents"`；`AgentLoader(work_dir, enable_verification=False)` 计算 `_project_dir`/`_user_dir`。
  - `load_all()` 顺序 项目→用户→内置（`importlib.resources.files("aixcode.agents.builtins")`），首次出现 name 占位、同名跳过；`_scan_directory(path, source)` 读 `*.md`；坏文件 try/except + `log.warning` 跳过。
  - `get(name)` 重读源文件热重载、失败回退缓存；`list_agents()`；`get_catalog() -> list[(agent_type, when_to_use)]`；`get_source_label`。
  - `enable_verification=False` 时不加载 `verification` 内置（若提供该内置）。
- 测试: 内置三档全在 / 项目覆盖内置 / get / get_unknown / 热重载成功+失败回退 / 坏文件跳过 / source_label / verification 默认不在·开启后在（如做 verification 内置）。

## T4: 四层工具过滤 resolve_agent_tools

- 影响文件: `aixcode/agents/tool_filter.py`、`tests/test_subagent.py`
- 依赖任务: 无（与 T1-T3 并行）
- 完成标准（TDD）:
  - `ALL_AGENT_DISALLOWED_TOOLS=frozenset({"Agent","AskUser"})`、`CUSTOM_AGENT_DISALLOWED_TOOLS=frozenset({"LoadSkill"})`、`ASYNC_AGENT_ALLOWED_TOOLS=frozenset({"ReadFile","WriteFile","EditFile","Bash","Glob","Grep","ToolSearch","LoadSkill"})`。
  - `resolve_agent_tools(registry, definition, is_background) -> ToolRegistry`（返回新实例）：MCP（`mcp_` 前缀）直通；去 `ALL_AGENT_DISALLOWED_TOOLS`；`source!="builtin"` 去 `CUSTOM_AGENT_DISALLOWED_TOOLS`；`is_background` 只留 `ASYNC_AGENT_ALLOWED_TOOLS`(+MCP)；`definition.tools` 非空只留白名单(+MCP)；再去 `definition.disallowed_tools`。
- 测试: 全局禁（Agent/AskUser 不在）/ 定义级 disallowed / 定义级 tools 白名单 / background 白名单 / 白+黑组合 / custom 额外禁 LoadSkill / builtin 不受 custom 限制 / MCP 直通。

## T5: Fork（build_forked_messages + ForkError）

- 影响文件: `aixcode/agents/fork.py`、`tests/test_subagent.py`
- 依赖任务: 无
- 完成标准（TDD）:
  - `FORK_BOILERPLATE_TAG="<fork_boilerplate>"`；`FORK_BOILERPLATE`（含该 tag + 强硬指令）；`ForkError`。
  - `build_forked_messages(conversation, task) -> ConversationManager`：扫 history 任意 `content` 含 TAG → `raise ForkError("Cannot fork from a forked agent.")`；`copy.deepcopy(history)` 复制；带 `tool_calls` 但缺对应 `tool` 结果的 assistant 消息补 `add_tool_result(id, "interrupted")`；末尾 `add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")`。
- 测试: 基本 fork / 保留历史 / 补 interrupted 占位 / 嵌套 fork 拒绝 / deepcopy 不改父对话。

## T6: TraceManager 调用树

- 影响文件: `aixcode/agents/trace.py`、`tests/test_subagent.py`
- 依赖任务: 无
- 完成标准（TDD）:
  - `@dataclass TraceNode`(`agent_id/parent_id/trace_id/agent_type/status/input_tokens/output_tokens/start_time/end_time`)。
  - `TraceManager`：`create(agent_type, parent_id=None, trace_id=None)`（agent_id=uuid hex 12 位；无 trace_id 自动生成）/ `update(agent_id, **kw)` / `complete(agent_id, status)`（写 end_time）/ `get_tree(trace_id)` / `get_total_tokens(trace_id)`；不存在 ID no-op。
- 测试: create 生成 id / update 改字段 / complete 写 end_time / get_tree 同 trace / get_total_tokens 汇总 / 不存在 ID no-op。

## T7: TaskManager + BackgroundTask 状态机

- 影响文件: `aixcode/agents/task_manager.py`、`tests/test_subagent.py`
- 依赖任务: 无
- 完成标准（TDD）:
  - `@dataclass BackgroundTask`(`task_id/agent_type/status/result/error/input_tokens/output_tokens/start_time/end_time`)。
  - `TaskManager`：`_tasks`/`_async_tasks`/`_notify_queue: asyncio.Queue`；`launch(coro_factory, agent_type) -> str`（`asyncio.create_task(self._run_background(...))` 立即返回 task_id；完成把 task_id 入队、写 result/tokens）；`_run_background` 捕获异常置 `failed`，`CancelledError` 置 `cancelled`；`adopt_running(coro, agent_type, ...) -> str`；`get/list_tasks/cancel/poll_completed`（`get_nowait` 抽空）。
- 测试: launch 完成→completed + result / poll_completed 抽空 / cancel running→cancelled / 失败→failed + error / list_tasks。

## T8: format_task_notification + inject_task_notifications

- 影响文件: `aixcode/agents/notification.py`、`tests/test_subagent.py`
- 依赖任务: T7
- 完成标准（TDD）:
  - `MAX_NOTIFICATION_RESULT_LENGTH=5000`；`format_task_notification(task) -> str`：`<task-notification>` 包裹，含 `Task ID/Agent/Status/Elapsed/Tokens/Result`；result 超 5000 截断含 `(truncated)`。
  - `inject_task_notifications(conversation, completed) -> None`：每个 task 包成 user message 追加。
- 测试: 格式含各字段 / 超长截断 / 注入后 conversation.history 增条。

## T9: AgentToolParams + AgentTool 壳 + 辅助

- 影响文件: `aixcode/tools/agent_tool.py`、`tests/test_subagent.py`
- 依赖任务: T1, T3, T4, T5, T6, T7
- 完成标准（TDD）:
  - `AgentToolParams(BaseModel)`：必填 `prompt/description`；可选 `subagent_type=""/model=""/run_in_background=False`。
  - `AgentTool(Tool)`：`name="Agent"`、`category="command"`、`is_concurrency_safe=False`；`__init__(agent_loader, task_manager, trace_manager, parent_agent, provider_config, enable_fork=False)`；`description` 由 `agent_loader.get_catalog()` 动态拼（列可用类型 + fork 说明）。
  - `PERMISSION_MODE_MAP` 复用 ch10 `parse_mode_name`；`run_to_completion(sub_agent, task) -> str`（驱动 `sub_agent.run` 收 LoopComplete 文本）；`_build_sub_agent(definition, tools_registry, model_client, work_dir)`（独立 PermissionChecker + 复用父 hook_engine）；`_select_model` + `_create_client_for_model`。
- 测试: params 必填/可选；AgentTool 属性；description 含 general-purpose/plan/explore；run_to_completion 用 stub agent 返回 LoopComplete 文本；_select_model 三优先级；_create_client_for_model 换 model。

## T10: AgentTool.execute 三路径 + 模型路由

- 影响文件: `aixcode/tools/agent_tool.py`、`tests/test_subagent.py`
- 依赖任务: T9
- 完成标准（TDD）:
  - 分发：`subagent_type` 给但 `loader.get` None → 错误列可用类型；`subagent_type==""` → fork（`enable_fork=False` 报错）→ `build_forked_messages` → 强制后台 `task_manager.launch`；否则定义式 `is_background = run_in_background or definition.background` → `resolve_agent_tools` → `_build_sub_agent` → background 走 `launch` 返回 `Task ID: <id>`，sync 走 `await run_to_completion` 返回文本。
  - 每次 spawn `trace_manager.create(...)`，完成/失败 `complete(...)`；前台异常标 failed 返回错误结果不抛。
- 测试: 未知 subagent_type 报错列类型 / fork 关闭报错 / sync 路径返回文本（stub LLM）/ background 返回 Task ID / 定义 background=true 强制后台 / trace 节点被建并 complete。

## T11: /tasks + /trace 命令

- 影响文件: `aixcode/commands/handlers/tasks.py`、`aixcode/commands/handlers/trace.py`、`aixcode/commands/handlers/__init__.py`（加入 ALL_COMMANDS）、`tests/test_subagent.py`/`tests/test_commands.py`
- 依赖任务: T6, T7
- 完成标准（TDD）:
  - `TASKS_COMMAND`(`/tasks list | view <id> | cancel <id>`，LOCAL/LOCAL_UI)：list 列后台任务（id/类型/状态/token/用时）；view 出详情含 result；cancel 调 `ctx.config["task_manager"].cancel`。
  - `TRACE_COMMAND`(`/trace [trace_id]`，LOCAL)：无参列最近 trace；带 id 出调用树（缩进 + token 汇总）。
  - 两者加入 `ALL_COMMANDS`（内置命令变 13 个）；从 `ctx.config["task_manager"]`/`["trace_manager"]` 取句柄，缺失给友好提示。
- 测试: tasks list/view/cancel 主路径（fake task_manager）；trace 列树（fake trace_manager）；ALL_COMMANDS 含 tasks/trace。
- 备注: ch10/ch11 既有 `ALL_COMMANDS` 数量断言需同步更新（11→13）。

## T12: 接入 app.py + __main__.py

- 影响文件: `aixcode/__main__.py`、`aixcode/app.py`、`tests/test_app.py`/`tests/test_subagent.py`
- 依赖任务: T1-T11
- 完成标准:
  - `__main__.py`：建 `agent_loader = AgentLoader(cwd); agent_loader.load_all()`、`task_manager = TaskManager()`、`trace_manager = TraceManager()`；建 Agent 后 `agent_tool = AgentTool(agent_loader, task_manager, trace_manager, parent_agent=agent, provider_config=config, enable_fork=True)` → `registry.register(agent_tool)`；把 `task_manager`/`trace_manager` 传入 `AixCodeApp`。
  - `app.py`：`AixCodeApp.__init__` 增 `task_manager=None, trace_manager=None` 字段；`_build_command_context` 的 `config` 塞 `"task_manager"`/`"trace_manager"`；REPL 主循环每轮 `_run_turn` 前 `completed = task_manager.poll_completed()`（非空 `inject_task_notifications(conversation, completed)`）；中断路径（`_run_turn` 捕获 CancelledError 处）调 `task_manager.adopt_running(...)` 挂后台而非杀。
- 测试: 构造 `AixCodeApp(..., task_manager=fake, trace_manager=fake)` 注册路径绿；registry 含 `Agent` 工具且 description 含可用类型；不传时既有路径仍绿（向后兼容）。

## T13: 端到端验证

- 影响文件: 无（仅运行验证）
- 依赖任务: T12
- 完成标准:
  - `python -m compileall aixcode tests` 通过；`python -m pytest -q` 全绿（ch01–12 既有 + ch13 新增，不少于 ch12 末 502）。
  - 离线 smoke：`AgentLoader(cwd).load_all()` 含 general-purpose/plan/explore；`resolve_agent_tools` 各层正确；`build_forked_messages` 嵌套拒绝；`TaskManager.launch`→`poll_completed` 走通；`format_task_notification` 含 `<task-notification>`；`AgentTool` 注册后 registry.get("Agent") 非空、description 含类型；sync spawn（stub LLM）返回文本；`/tasks`·`/trace` dispatch 正常。
  - 真实手动（本机 `python -m aixcode`，PowerShell，见 checklist §5）。

## 进度

- [x] T1 AgentDef + 三档内置 Markdown
- [x] T2 parse_agent_file + 校验
- [x] T3 AgentLoader 三级搜索 + 热重载
- [x] T4 四层工具过滤
- [x] T5 Fork（build_forked_messages）
- [x] T6 TraceManager
- [x] T7 TaskManager
- [x] T8 notification
- [x] T9 AgentTool 壳 + 辅助
- [x] T10 AgentTool.execute 三路径
- [x] T11 /tasks + /trace 命令
- [x] T12 接入 app + __main__
- [x] T13 端到端验证（compileall 通过；pytest 585 passed；离线 smoke 全通）
