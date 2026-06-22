# ch15: AgentTeam 系统 Checklist（AixCode / Python 版）

> 所有条目必须可勾选、可观测。验收方式写在每项后面的括号里。操作目录 `d:\Agent\AixCode`，命令用 Bash 工具的 `grep`/`python`/`git` 即可。先读 [spec.md](spec.md) 与 [tasks.md](tasks.md)。

## 1. 实现完整性（teams 包）

- [x] `BackendType` 在 `aixcode/teams/models.py` 三档常量 `TMUX="tmux" / ITERM2="iterm2" / IN_PROCESS="in-process"`（grep + pytest）
- [x] `TeammateInfo` dataclass 7 字段含 `name/agent_id/agent_type/model/worktree_path/backend_type/is_active`，`is_active: bool | None = None` 三值（pytest）
- [x] `AgentTeam` dataclass 含 `members: list[TeammateInfo]`、`get_member` 按 name 和 agent_id 双向查、`add_member`/`remove_member`/`set_member_active`/`active_members`/`all_idle`/`to_dict`/`from_dict`/`save`/`load`（pytest）
- [x] `resolve_team_dir` 落到 `~/.aixcode/teams/<slug>/`（用 `Path.home()`），`unique_team_name` 同名加 `-2/-3/...` 后缀（pytest，monkeypatch home）
- [x] `MailboxMessage` dataclass 8 字段，`message_type` 注释三档 `text | shutdown_request | shutdown_response`（grep + pytest）
- [x] `Mailbox` 单文件单消息 `<base>/<agent_id>/<timestamp>_<id>.json`，`write/read/consume/broadcast/cleanup/cleanup_all` 六方法；`consume` 后删除保证 FIFO（pytest）
- [x] `create_message` 自动填 `uuid4().hex[:12]` 和 `time.time()`（pytest）
- [x] `BackendDetectionError` + `detect_backend` 优先级链，失败抛错不静默回退（pytest，monkeypatch env/which）
- [x] `SharedTask` + `SharedTaskStore` 单文件 `tasks.json` `{"next_id","tasks":[...]}`，`create/get/list_tasks/update/init_empty` 五方法（pytest）
- [x] `AgentNameRegistry` 单例线程安全 double-checked，`resolve` 同时支持 name 与 agent_id 反查，`instance`/`reset` 类方法（pytest）
- [x] `InProcessTeammateHandle` + `spawn_inprocess_teammate` 用 `asyncio.create_task`，懒导入模块级 `run_to_completion`；handle `done/result/cancel`（pytest）
- [x] `build_cli_command` 输出 `AIXCODE_TEAM_NAME=X AIXCODE_TEAMMATE_NAME=Y AIXCODE_MAILBOX_DIR=Z python -m aixcode -p --work-dir <wt> '<prompt>'`，prompt 内单引号转义为 `'\''`（pytest）
- [x] `spawn_tmux_teammate` 三级 fallback（split-window → new-window → new-session）+ `kill_pane`/`send_keys_to_pane` best-effort（pytest，mock `_run_tmux`）
- [x] `spawn_iterm2_teammate` 复用 `build_cli_command`，经 `it2 split-pane` 创建 pane，失败抛 `ITermSpawnError`（pytest，mock `_run_it2`）
- [x] `save_transcript`/`load_transcript` 序列化扁平 `Message`（role/content/tool_calls/tool_call_id）到 `<team_dir>/transcripts/<agent_id>.json`，load 置 `env_injected=ltm_injected=True`（pytest）
- [x] `TeamManager` 7 内部字典 + 13 公开方法；`__init__(worktree_manager, trace_manager)`；`_detected_backend` 首次后缓存（grep + pytest）
- [x] `delete_team` 先校验全员 `is_active is not False` 须 idle 否则抛 `TeamError`，通过后清 name registry/handle/pane/worktree/trace + cleanup mailbox + 删目录 + 弹三缓存（pytest）
- [x] `is_coordinator_mode` 双开关（flag false 恒 false；true 读 `AIXCODE_COORDINATOR_MODE` ∈ `{1,true,yes}`）；`get_coordinator_system_prompt` 含四阶段 + anti-pattern（pytest）

## 2. 实现完整性（工具 + tool_filter）

- [x] `COORDINATOR_MODE_ALLOWED_TOOLS` 在 `aixcode/agents/tool_filter.py` 含 12 项 `{Agent, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate, TeamCreate, TeamDelete, ReadFile, Glob, Grep, Bash}`（写工具排除）（grep + pytest）
- [x] `TEAMMATE_COORDINATION_TOOLS` 5 项 `{SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate}`；`IN_PROCESS_TEAMMATE_ALLOWED_TOOLS = ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS`（无 Cron）（grep + pytest）
- [x] `apply_coordinator_filter(registry)` 重建只含白名单（MCP 直通）新 registry（pytest）
- [x] `build_teammate_tools(registry, backend)` 按 backend 分流：in-process 严格白名单、pane 只剔除 `TeamCreate`/`TeamDelete`（pytest）
- [x] `TaskCreate/TaskGet/TaskList/TaskUpdate` 四工具经 `parent_agent.team_name` 找 `get_task_store`，无团队返 IsError（pytest）
- [x] `SendMessageTool` 五参数；`text` 缺 summary / 非法 message_type / 未知收件人均返 IsError；`to="*"` 广播（pytest）
- [x] `TeamCreateTool` `team_name+description`；Coordinator Mode 激活时备份 `_full_registry` + 设 `parent_agent.team_name`（pytest）
- [x] `TeamDeleteTool` `team_name`；Coordinator Mode 还原 `_full_registry` + 清 flag/team_name（pytest）
- [x] `AgentTool._execute_as_teammate` 处理 `team_name` 分支，含 worktree 创建 / `build_teammate_tools` / `register_member` / spawn 分发 + done_callback（grep + pytest）

## 3. 接入完整性（必查，杜绝死代码）

- [x] `grep -n "TeamManager" aixcode/__main__.py` 命中导入 + `TeamManager(worktree_manager, trace_manager)` 创建
- [x] `grep -n "TeamCreateTool\|TeamDeleteTool\|SendMessageTool\|TaskCreate" aixcode/__main__.py` 命中七工具注册点
- [x] `grep -n "team_manager=team_manager" aixcode/__main__.py` 命中 AgentTool 注入点
- [x] `grep -n "agent._team_manager" aixcode/__main__.py` 命中主 Agent 注入
- [x] `grep -n "load_team_settings" aixcode/__main__.py aixcode/config.py` 两处命中（定义 + 调用）
- [x] `grep -n "self.agent_id\|self.team_name\|self.coordinator_mode\|self._team_manager" aixcode/agent.py` 命中 `Agent.__init__` 四字段
- [x] `grep -n "_consume_mailbox" aixcode/agent.py` 命中定义 + run 主循环开头钩入（两处）
- [x] `grep -n "coordinator_mode=" aixcode/agent.py` 命中 `build_system_prompt(coordinator_mode=self.coordinator_mode)`
- [x] `grep -n "coordinator_mode" aixcode/prompts.py` 命中 `build_system_prompt` 新参数
- [x] `grep -n "team_name\|_execute_as_teammate\|team_manager" aixcode/tools/agent_tool.py` 命中入参 + 入口分发 + 函数体 + `__init__` 参数

## 4. 编译与测试

- [x] `python -m compileall aixcode tests` 无错误
- [x] `python -m pytest -q tests/test_teams.py` 通过（覆盖 models / mailbox / backend_detect / shared_task / registry / spawn_inprocess / spawn_tmux / spawn_iterm2 / transcript / manager / coordinator / tool_filter / 七工具 / agent 接入 / config）
- [x] `python -m pytest -q tests/test_subagent.py` 全通过（AgentTool 改造未破坏 ch13）
- [x] `python -m pytest -q tests/test_agent.py` 全通过（Agent.__init__ 新字段未破坏 ch04）
- [x] `python -m pytest -q` 全量绿（不低于 ch14 的 694，新增 teams 用例计入）
- [x] 测试运行后用户主目录无 `~/.aixcode/teams/` 残留（fixture 用 `monkeypatch.setattr("aixcode.teams.models.Path.home", ...)` 重定向生效）

## 5. 端到端验证（接线 / 行为，真实 TUI 与 pane 后端见 Out of Scope）

- [x] 创建路径：`TeamCreate(team_name="refactor-x")` →（in-process）`detect_backend` 选 IN_PROCESS → `create_team` 在 `~/.aixcode/teams/refactor-x/` 落 `config.json`+`tasks.json`+`mailbox/` → 返回成功文本含 backend 与 config 路径（pytest 模拟 execute）
- [x] Spawn 路径：`Agent(team_name="refactor-x", name="alice", prompt=...)` → `_execute_as_teammate` → `worktree_manager.create("team-refactor-x/alice")` → `build_teammate_tools` → `spawn_inprocess_teammate` → `get_team` 含 alice 成员 + name registry 命中（pytest）
- [x] 通信路径：alice `SendMessage(to="bob", message, summary)` → `resolve("bob")` → `mailbox.write` → bob 下一轮 `_consume_mailbox` 收到（pytest 直接驱动 `_consume_mailbox`）
- [x] Lead 感知路径：in-process 队员 task 完成 → done_callback → `on_teammate_completed(agent_id)` → `set_member_idle`（`is_active=False` + Lead 邮箱写 `Teammate '<name>' is now idle.`）→ Lead `_consume_mailbox` 注入（pytest）
- [x] Coordinator Mode 路径：`enable_coordinator_mode=True` 且 `AIXCODE_COORDINATOR_MODE=1` → `TeamCreate` 切 `coordinator_mode=True` + `apply_coordinator_filter` → registry 只剩 12 项白名单（无 `WriteFile`/`EditFile`）→ `TeamDelete` 恢复 `_full_registry`（pytest）
- [x] 关闭路径：`TeamDelete(team_name="refactor-x")` → 全员 idle 校验 → 清各资源 → 删团队目录 + 弹三缓存（pytest）
- [x] tmux/iTerm2 后端 spawn 拼命令逻辑经 mock 单测覆盖（真实 pane 启动属 Out of Scope，不验收）

## 6. 文档

- [x] `spec.md` 为 ch15 自包含版（§0 含 ch14 worktree + work_dir 修复、ch15 当前目标、适配差异）
- [x] `tasks.md` 为 ch15 T1-T16
- [x] `checklist.md` 为本文件并逐项验收
- [ ] commit 信息标注 `ch15`（待用户确认后提交）
- [x] 清理临时文件 `_mewcode_ch15_ref.tmp.md`（参考用途完成后删除）
