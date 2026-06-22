# ch15: AgentTeam 系统 Tasks（AixCode / Python 版）

> 任务粒度：每个任务可在一次会话内完成、可独立交付。先读 [spec.md](spec.md) §0 全局背景与适配差异，再按本表顺序 TDD（先写失败测试→看红→最小实现→转绿），配 [checklist.md](checklist.md) 验收。测试统一纯 pytest 函数 + `asyncio.run`，新增用例集中在 `tests/test_teams.py`；涉及 home 落盘的用例用 `monkeypatch.setattr("aixcode.teams.models.Path.home", lambda: tmp_path)` 重定向，`AgentNameRegistry.reset()` 用 autouse fixture。每个任务后跑 `python -m compileall aixcode tests` + `python -m pytest -q`。

## T1: teams 包骨架 + 核心模型（BackendType / TeammateInfo / AgentTeam）
- 影响文件: `aixcode/teams/__init__.py`（新建，先空导出占位）、`aixcode/teams/models.py`（新建）
- 依赖任务: 无
- 完成标准:
  - `BackendType(str, Enum)` 三档 `TMUX="tmux"` / `ITERM2="iterm2"` / `IN_PROCESS="in-process"`；
  - `TeammateInfo` dataclass 7 字段 `name / agent_id / agent_type / model / worktree_path / backend_type / is_active`，`is_active: bool | None = None` 三值语义；
  - `AgentTeam` dataclass 含 `name / lead_agent_id / members: list[TeammateInfo] / config_path / description`，方法 `get_member`（按 name 或 agent_id 双向查）/ `add_member` / `remove_member`（列表移除不留墓碑）/ `set_member_active` / `active_members` / `all_idle` / `to_dict` / `from_dict` / `save` / `load`；
  - `resolve_team_dir(name)` 用 `Path.home()` 落到 `~/.aixcode/teams/<slug>/`（`_sanitize_name` 规整 slug）；`unique_team_name(name)` 同名冲突自动加 `-2/-3/...` 后缀。
- 测试: `BackendType` 取值；`TeammateInfo` 三值 `is_active`；`AgentTeam.get_member` 按 name 和按 agent_id 都命中；`set_member_active`/`all_idle`/`active_members`；`save`→`load` round-trip（monkeypatch home）；`unique_team_name` 冲突加后缀。
- [x] 完成

## T2: Mailbox + MailboxMessage + create_message（单文件单消息）
- 影响文件: `aixcode/teams/mailbox.py`（新建）
- 依赖任务: 无
- 完成标准:
  - `MailboxMessage` dataclass 8 字段 `id / from_agent / to_agent / content / summary / message_type / timestamp / metadata`（`message_type` 注释三档 `text | shutdown_request | shutdown_response`，`metadata: dict` 默认空）；
  - `Mailbox(base_dir)`：`write(agent_id, msg)` 以 `<base>/<agent_id>/<timestamp>_<id>.json` 落盘；`read(agent_id)` 只读不删按时间序；`consume(agent_id)` 读完逐个 `unlink` 保证 FIFO；`broadcast(agent_ids, msg, exclude=None)` 逐个 write 排除 exclude；`cleanup(agent_id)` / `cleanup_all()` 清目录；
  - `create_message(from_agent, to_agent, content, summary="", message_type="text", metadata=None)` 自动填 `id=uuid4().hex[:12]`、`timestamp=time.time()`。
- 测试: `write`→`read` 拿回同一条；`consume` 后再 `read` 为空（FIFO + 删除）；多条 `write` 后 `consume` 时间有序；`broadcast` 排除 exclude 后各 agent_id 收到；`create_message` 自动填 id/timestamp。
- [x] 完成

## T3: detect_backend 优先级链
- 影响文件: `aixcode/teams/backend_detect.py`（新建）
- 依赖任务: T1
- 完成标准: `BackendDetectionError`；私有探测 `_in_tmux_session`（`TMUX` env）/ `_in_iterm2`（`TERM_PROGRAM=="iTerm.app"`）/ `_it2_available`（`shutil.which("it2")`）/ `_tmux_installed`（`shutil.which("tmux")`）；`detect_backend(teammate_mode, is_interactive)` 优先级 `teammate_mode == "in-process" or not is_interactive` → TMUX env → iTerm2+it2 → tmux → 否则抛 `BackendDetectionError`（消息含 tmux/iTerm2 安装指引 + `teammate_mode: "in-process"` 选项），不静默回退。
- 测试: `teammate_mode="in-process"` → IN_PROCESS；`is_interactive=False` → IN_PROCESS；monkeypatch `os.environ`/`shutil.which`：TMUX env → TMUX、iTerm2+it2 → ITERM2、仅 tmux → TMUX、全不命中 → 抛 `BackendDetectionError`。
- [x] 完成

## T4: SharedTaskStore + SharedTask
- 影响文件: `aixcode/teams/shared_task.py`（新建）
- 依赖任务: 无
- 完成标准:
  - `SharedTask` dataclass 8 字段 `id / title / description / status / assignee / blocks / blocked_by / created_by`（`status` 注释四档 `pending | in_progress | completed | blocked`，`blocks`/`blocked_by` 默认空列表）；
  - `SharedTaskStore(path)` 用单文件 `tasks.json` 结构 `{"next_id": int, "tasks": [...]}`，`__init__`+`_load`+`_save`；`create(title, description="", assignee="", blocks=None, blocked_by=None, created_by="")` 自增 id 返 `SharedTask`；`get(task_id)`；`list_tasks(status=None, assignee=None)` 双过滤；`update(task_id, **fields)` 部分更新 + `add_blocks`/`add_blocked_by` 去重追加；`init_empty()` 清空 + `next_id=1` + save。
- 测试: `create` 自增 id；`get` 命中/未命中；`list_tasks` 按 status/assignee 过滤；`update` 改 status + `add_blocks` 去重；`init_empty` 后列表空且 next_id 重置；落盘后新建 store 能 `_load` 回来。
- [x] 完成

## T5: AgentNameRegistry 单例
- 影响文件: `aixcode/teams/registry.py`（新建）
- 依赖任务: 无
- 完成标准: 进程内单例（`_lock = threading.Lock()` double-checked locking）；类方法 `instance()` / `reset()`；实例方法 `register(name, agent_id)` / `resolve(name_or_id)`（先按 name 查再按 id 反查，命不中返 None）/ `unregister(name)` / `list_all()`；内部 `_names: dict[str, str]`。
- 测试: `register`+`resolve` 按 name 命中；按 agent_id 反查命中；`resolve` 未知返 None；`unregister` 后 resolve 失败；`reset` 清空；`instance()` 多次返回同一对象。
- [x] 完成

## T6: spawn_inprocess_teammate + InProcessTeammateHandle
- 影响文件: `aixcode/teams/spawn_inprocess.py`（新建）
- 依赖任务: T1
- 完成标准: `InProcessTeammateHandle(agent, task, name)` 属性 `done`（task.done()）/ `result`（已完成且无异常返结果否则 None）/ `cancel()`（未完成时取消）；`spawn_inprocess_teammate(agent, prompt, name, conversation=None)` **懒导入** `aixcode.tools.agent_tool.run_to_completion`，无 conversation 时用 `prompt` 构造 `ConversationManager`，`asyncio.create_task(run_to_completion(agent, conv), name=f"teammate-{name}")` 起协程，返 handle。
- 测试（用 `asyncio.run` 包一个 async 主体 + 假 agent）：传入一个 `run` 产 `LoopComplete("done")` 的假 agent，spawn 后 await handle.task，`handle.done` 为真、`handle.result == "done"`；`cancel` 一个未完成 task 后 `done` 为真。
- [x] 完成

## T7: spawn_tmux_teammate + build_cli_command + kill_pane（移植 + mock 测试）
- 影响文件: `aixcode/teams/spawn_tmux.py`（新建）
- 依赖任务: T1
- 完成标准: `TmuxPaneInfo`/`TmuxSpawnError`/`_run_tmux`；`build_cli_command(team_name, teammate_name, mailbox_dir, work_dir, prompt, agent_type="", model="")` 输出 `AIXCODE_TEAM_NAME=X AIXCODE_TEAMMATE_NAME=Y AIXCODE_MAILBOX_DIR=Z python -m aixcode -p --work-dir <wt> [--agent-type X] [--model X] '<prompt>'`，prompt 内单引号转义为 `'\''`；`spawn_tmux_teammate(...)` 三级 fallback（`split-window -h -t <team>` → `new-window`+`split-window` → `new-session -d`+`list-panes`）后 `send-keys -t <pane> <cmd> Enter`；`kill_pane(pane_id)` / `send_keys_to_pane(pane_id, keys)` best-effort 静默失败。
- 测试（mock `_run_tmux`/`subprocess`）: `build_cli_command` 字符串含三个 env 前缀 + `python -m aixcode -p` + 转义后的单引号；`build_cli_command` 带 agent_type/model 时拼入对应 flag；`spawn_tmux_teammate` 在 split-window 失败时回退 new-window（断言调用序列）；`kill_pane` 在 `_run_tmux` 抛错时不传播。
- [x] 完成

## T8: spawn_iterm2_teammate（移植 + mock 测试）
- 影响文件: `aixcode/teams/spawn_iterm2.py`（新建）
- 依赖任务: T7
- 完成标准: `ITermPaneInfo{session_id}`/`ITermSpawnError`/`_run_it2`；`spawn_iterm2_teammate(...)` 复用 `build_cli_command`，经 `it2 split-pane --command "/bin/zsh -c '<cmd>'"` 创建 pane，返 `ITermPaneInfo`，失败抛 `ITermSpawnError`（不静默吞）。
- 测试（mock `_run_it2`）: 成功返回带 session_id 的 `ITermPaneInfo`；`_run_it2` 失败时抛 `ITermSpawnError`；命令字符串含 `it2 split-pane` 和 `build_cli_command` 产物。
- [x] 完成

## T9: transcript 持久化（扁平 Message）
- 影响文件: `aixcode/teams/transcript.py`（新建）
- 依赖任务: T1
- 完成标准: `_serialize_message(m)` / `_deserialize_message(d)` 处理 `Message{role,content,tool_calls,tool_call_id}`；`save_transcript(team_name, agent_id, conv)` 把 `conv.history` 序列化 JSON 落 `~/.aixcode/teams/<team>/transcripts/<agent_id>.json`；`load_transcript(team_name, agent_id)` 反序列化为 `Message` 列表回填新建 `ConversationManager` 的 `history`，置 `env_injected = ltm_injected = True`；文件缺失返 None。
- 测试: 含 user/assistant(tool_calls)/tool 三类消息的 conversation `save`→`load` round-trip 字段一致；load 后 `env_injected`/`ltm_injected` 为 True；缺文件返 None。
- [x] 完成

## T10: TeamManager 全套方法
- 影响文件: `aixcode/teams/manager.py`（新建）
- 依赖任务: T1, T2, T3, T4, T5, T6
- 完成标准: `TeamError`；`TeamManager(worktree_manager=None, trace_manager=None)` 七字段 `_teams / _task_stores / _mailboxes / _inprocess_handles / _pane_ids / _teammate_team_map / _detected_backend` 初始化；`detect_backend` 首次后缓存到 `_detected_backend`；`create_team` 链 `detect_backend → unique_team_name → mkdir → AgentTeam(...).save → SharedTaskStore.init_empty → Mailbox` + 缓存三字典；`get_team`/`get_task_store`/`get_mailbox`；`register_member`（同时 `AgentNameRegistry.register` + 写 `_teammate_team_map`）；`set_member_idle`（翻 `is_active=False` + 写 idle 通知到 Lead 邮箱）；`register_inprocess_handle`/`register_pane_id`/`get_pane_id`；`get_team_for_teammate`；`on_teammate_completed(agent_id)`（查团队 → `set_member_idle`）；`delete_team`（先校验全员 `is_active is not False` 须 idle 否则抛 `TeamError`，通过后遍历 member 清 name registry / handle.cancel / `_kill_pane` / `_cleanup_worktree` / trace remove，再 `cleanup_all` + 删目录 + 弹三缓存）；私有 `_kill_pane`/`_cleanup_worktree`/`_remove_dir`。
- 测试: `create_team` 落盘三件 + 缓存命中；`detect_backend` 第二次不重新探测（缓存）；`register_member`+`get_team_for_teammate` 反查；`set_member_idle` 翻标志 + Lead 邮箱有 idle 消息；`delete_team` 有 active 成员时抛 `TeamError`；全员 idle 后 `delete_team` 清缓存 + 删目录。（worktree/trace 用假对象注入。）
- [x] 完成

## T11: coordinator 提示词 + tool_filter 扩展
- 影响文件: `aixcode/teams/coordinator.py`（新建）、`aixcode/agents/tool_filter.py`（改）
- 依赖任务: T5, T10
- 完成标准:
  - `coordinator.py`：`is_coordinator_mode(enable_flag)` 双开关（flag false 直接 false；true 时读 `AIXCODE_COORDINATOR_MODE` ∈ `{1,true,yes}`）；`get_coordinator_system_prompt()` 输出含 `Research / Synthesis / Implementation / Verification` 四阶段引导 + `based on your findings` anti-pattern；
  - `tool_filter.py`：新增 `COORDINATOR_MODE_ALLOWED_TOOLS`（12 项 `{Agent, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, TeamCreate, TeamDelete, ReadFile, Glob, Grep, Bash}`）、`TEAMMATE_COORDINATION_TOOLS`（5 项 `{SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate}`）、`IN_PROCESS_TEAMMATE_ALLOWED_TOOLS = ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS`；`apply_coordinator_filter(registry)` 重建只含白名单（MCP 直通）的新 `ToolRegistry`；`build_teammate_tools(registry, backend)` 按 backend 分流：in-process 用 `IN_PROCESS_TEAMMATE_ALLOWED_TOOLS` 严格白名单，pane 模式只剔除 `TeamCreate`/`TeamDelete`。
- 测试: `is_coordinator_mode(False)` 恒 False；`True` 且 env=`1` 为 True、env 缺为 False；`get_coordinator_system_prompt` 含四阶段关键词；`apply_coordinator_filter` 后 registry 只剩白名单内工具 + MCP；`build_teammate_tools` in-process 含 5 项协调工具且无 Agent/AskUser、pane 模式含写工具但无 TeamCreate/TeamDelete。
- [x] 完成

## T12: 共享任务工具四件（TaskCreate / TaskGet / TaskList / TaskUpdate）
- 影响文件: `aixcode/tools/task_create.py`、`aixcode/tools/task_get.py`、`aixcode/tools/task_list.py`、`aixcode/tools/task_update.py`（均新建）
- 依赖任务: T4, T10
- 完成标准: 四工具均持 `(team_manager, parent_agent)`，经 `parent_agent.team_name` 找 `team_manager.get_task_store(team_name)`；无活跃团队返 IsError。
  - `TaskCreate(title, description="", assignee="", blocks=None, blocked_by=None)` → `store.create(..., created_by=parent_agent.agent_id)`，返新任务 id + 摘要；
  - `TaskGet(task_id)` → 返任务详情或未找到 IsError；
  - `TaskList(status="", assignee="")` → 过滤后列表文本；
  - `TaskUpdate(task_id, status="", assignee="", title="", description="", add_blocks=None, add_blocked_by=None)` → 部分更新，返更新后摘要；
  - 四工具 `category` 取 `read`（Get/List）/`write`（Create/Update）合理值，`is_system_tool=False`。
- 测试: 用假 `team_manager`（含真实 `SharedTaskStore`）+ 假 `parent_agent(team_name, agent_id)`：`TaskCreate` 后 `TaskGet` 拿回；`TaskList` 过滤；`TaskUpdate` 改 status；`parent_agent.team_name=""` 时四工具均返 IsError。
- [x] 完成

## T13: SendMessageTool / TeamCreateTool / TeamDeleteTool
- 影响文件: `aixcode/tools/send_message.py`、`aixcode/tools/team_create.py`、`aixcode/tools/team_delete.py`（均新建）
- 依赖任务: T2, T5, T10, T11
- 完成标准:
  - `SendMessageTool(team_manager, parent_agent)` 参数 `to / message / summary / message_type / metadata`；`VALID_MESSAGE_TYPES = {text, shutdown_request, shutdown_response}`；先校验 type 合法、`text` 必须有 `summary`；`to=="*"` 走 `broadcast(member_ids ∪ {lead_agent_id} \ {self.agent_id})`，否则 `AgentNameRegistry.instance().resolve(to)` 解析（失败返 IsError `Cannot resolve recipient '...'`）→ `mailbox.write` →（pane）`_wake_pane(target_id)`；
  - `TeamCreateTool(team_manager, parent_agent, teammate_mode="", is_interactive=True, enable_coordinator_mode=False)` 参数 `team_name`+`description`；先 `detect_backend` 不通过返 IsError；通过后 `create_team(team_name, lead_agent_id=parent_agent.agent_id, description, teammate_mode, is_interactive)` + 设 `parent_agent.team_name = team.name`；若 `is_coordinator_mode(enable_coordinator_mode)` 则 `parent_agent.coordinator_mode=True` + 备份 `_full_registry` + `registry = apply_coordinator_filter(registry)` + 输出附 "Coordinator Mode activated"；
  - `TeamDeleteTool(team_manager, parent_agent)` 参数 `team_name`；`delete_team` 捕获 `TeamError` 返 IsError；若 `parent_agent.coordinator_mode` 则恢复 `_full_registry` + 清零 flag + 清 `team_name` + 输出附 "Coordinator Mode deactivated"。
- 测试: 假 team_manager + 假 parent_agent(agent_id, registry)：`SendMessage` text 缺 summary 返 IsError；非法 message_type 返 IsError；`to="*"` 广播写到各成员邮箱；`to=未知名` 返 IsError；`TeamCreate` 成功落盘 + 设 parent_agent.team_name；coordinator 开关开时切 registry + 备份；`TeamDelete` 还原 registry。
- [x] 完成

## T14: AgentTool._execute_as_teammate（team_name 分支）
- 影响文件: `aixcode/tools/agent_tool.py`（改）
- 依赖任务: T10, T11, T13（及 ch13/ch14 现有 AgentTool / WorktreeManager）
- 完成标准:
  - `AgentToolParams` 加 `team_name: str | None = None` 和 `name: str = ""` 字段；
  - `AgentTool.__init__` 加 `team_manager=None` 关键字参数 + `self._team_manager` 字段；
  - `execute` 入口看到 `params.team_name` 非空时优先走 `_execute_as_teammate`（先于 fork/sync/background 分发）；
  - `_execute_as_teammate(params)`：校验 `_team_manager`/`worktree_manager` 已装配、`get_team(team_name)` 不存在返 IsError；base_name（`params.name` 或缺省生成）同名冲突自动加 `-2/-3/...`；可选解析 `subagent_type`，无 type + `enable_fork` 走 `build_forked_messages`（从 `parent_agent.active_conversation`）否则用空白 builtin `AgentDef`；`worktree_manager.create(f"team-{team_name}/{teammate_name}", "HEAD")` 建 wt；`detect_backend` 决定后端；`build_teammate_tools(parent_agent.registry, backend)` 构造工具池；建 sub-agent 后设 `sub_agent.agent_id`（新 uuid）/`sub_agent.team_name=team_name`/`sub_agent._team_manager=team_manager`，prompt 前拼队员说明 addendum；`AgentNameRegistry.instance().register(teammate_name, agent_id)`；`TeammateInfo(...)` 后 `team_manager.register_member`；in-process 走 `spawn_inprocess_teammate` 并 `handle.task.add_done_callback(lambda t: team_manager.on_teammate_completed(agent_id))` + `register_inprocess_handle`，pane 走 spawn_tmux/iterm2 + `register_pane_id`；**立即返回** spawn 确认文本（不 await 跑完）。
- 测试: 假 parent_agent(registry, agent_id, active_conversation) + 真 WorktreeManager（临时 git 仓库或 mock create）+ 真 TeamManager(in-process)：`Agent(team_name=X, name=alice, prompt=...)` → `_execute_as_teammate` 返确认文本、`team_manager.get_team(X).get_member("alice")` 存在、`AgentNameRegistry.resolve("alice")` 命中、同名再 spawn 得 `alice-2`；`team_name` 为空时仍走 ch13 原路径（回归）。
- [x] 完成

## T15: Agent 接入（agent_id / team 字段 / _consume_mailbox / coordinator 提示词）+ build_system_prompt + config
- 影响文件: `aixcode/agent.py`（改）、`aixcode/prompts.py`（改）、`aixcode/config.py`（改）
- 依赖任务: T2, T10, T11
- 完成标准:
  - `Agent.__init__` 加 `self.agent_id`（默认 `uuid4().hex[:12]`）/`self.team_name: str = ""`/`self.coordinator_mode: bool = False`/`self._team_manager = None` 四字段；
  - `Agent._consume_mailbox(conversation)`：`team_name` 和 `_team_manager` 都非空时 `get_mailbox(team_name).consume(self.agent_id)`，每条前缀 `[Message from <from>] ` 或 `[<type> from <from>] ` 后 `conversation.add_user_message`，异常吞掉记 `logger.debug`；
  - `Agent.run` 的 `while True` 循环体最开头（`iteration += 1` 后）`await self._consume_mailbox(conversation)`；
  - `run` 内 `build_system_prompt(...)` 调用加 `coordinator_mode=self.coordinator_mode`；
  - `prompts.build_system_prompt(custom_instructions="", deferred_tools=None, coordinator_mode=False)`：`coordinator_mode` 为真时追加一段协调模式 section（引导阶段化工作流，复用 `teams.coordinator.get_coordinator_system_prompt` 或内联等价文本）；
  - `config.load_team_settings(path="config.yaml") -> tuple[str, bool]`：读 `teammate_mode`（默认 `""`，校验 ∈ `{"", "in-process"}` 否则 ValueError）与 `enable_coordinator_mode`（默认 `False`），缺文件返 `("", False)`。
- 测试: 新 `Agent` 有非空 `agent_id` 且默认 `team_name=""`/`coordinator_mode=False`；`_consume_mailbox` 在配好 team_manager+mailbox 后把消息注入 conversation（带前缀）、无 team 时 no-op；`build_system_prompt(coordinator_mode=True)` 含协调关键词、默认不含；`load_team_settings` 读合法值、非法 teammate_mode 抛 ValueError、缺文件返默认。
- [x] 完成

## T16: __main__ 装配 + 端到端验证
- 影响文件: `aixcode/__main__.py`（改）、`aixcode/teams/__init__.py`（补全导出）
- 依赖任务: T12, T13, T14, T15
- 完成标准:
  1. `__main__.main()` 经 `load_team_settings()` 取 `teammate_mode`/`enable_coordinator_mode`；
  2. 在 AgentTool 构造前建 `team_manager = TeamManager(worktree_manager, trace_manager)`；
  3. `AgentTool(..., team_manager=team_manager)` 注入；
  4. 注册 `TeamCreateTool(team_manager, agent, teammate_mode, is_interactive=True, enable_coordinator_mode)`、`TeamDeleteTool(team_manager, agent)`、`SendMessageTool(team_manager, agent)`、`TaskCreate/TaskGet/TaskList/TaskUpdate(team_manager, agent)` 七工具进 registry；
  5. `agent._team_manager = team_manager`（`agent.agent_id` 已在构造时生成）；
  6. `teams/__init__.py` 导出 `BackendType/TeammateInfo/AgentTeam/TeamManager/TeamError/Mailbox/MailboxMessage/create_message/SharedTask/SharedTaskStore/AgentNameRegistry/detect_backend/BackendDetectionError` 等对外符号。
- 验证（端到端 / 接线，非 TUI）:
  - `python -m compileall aixcode tests` 通过；
  - `python -m pytest -q` 全绿（含新 `tests/test_teams.py` 与 ch13 `tests/test_subagent.py`、ch04 `tests/test_agent.py` 回归）；
  - 接线检查：`grep` 确认 `__main__.py` 含 `TeamManager` + 七工具注册 + `agent._team_manager`；`agent.py` 含 `_consume_mailbox`/`agent_id`/`coordinator_mode` 三处接入；`agent_tool.py` 含 `_execute_as_teammate` 入口分发 + 函数体；
  - 测试运行不在用户主目录残留 `~/.aixcode/teams/`（fixture 重定向 home 生效）。
- [x] 完成

## 进度
- [x] T1 / [x] T2 / [x] T3 / [x] T4 / [x] T5 / [x] T6 / [x] T7 / [x] T8 / [x] T9 / [x] T10 / [x] T11 / [x] T12 / [x] T13 / [x] T14 / [x] T15 / [x] T16
