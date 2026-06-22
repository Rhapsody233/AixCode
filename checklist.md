# ch13: SubAgent 系统 Checklist（AixCode / Python 版）

> 所有条目必须可勾选、可观测。验收方式写在每项后面的括号里。操作目录 `d:\Agent\AixCode`，命令用 Bash 工具的 `grep`/`python` 即可。
> 全局背景见 [spec.md](spec.md) §0。

## 1. 实现完整性

### 1.1 定义与加载

- [x] `@dataclass AgentDef` 11 字段（`agent_type/when_to_use/system_prompt/tools/disallowed_tools/model/max_turns/permission_mode/background/file_path/source`），默认 `model="inherit"/max_turns=50/permission_mode="default"`（`grep -n "class AgentDef" aixcode/agents/parser.py` + 单测）
- [x] `VALID_MODELS={"inherit","deepseek-chat","deepseek-pro",""}` + `VALID_PERMISSION_MODES={"","strict","default","accept","bypass"}` + `AgentParseError`（`grep -n "VALID_MODELS\|VALID_PERMISSION_MODES\|class AgentParseError" aixcode/agents/parser.py`）
- [x] `parse_agent_file` 校验 name/description 必填 + model/permissionMode 白名单 + maxTurns 正整数（`grep -n "def parse_agent_file\|def parse_frontmatter" aixcode/agents/parser.py` + 单测逐项）
- [x] 三档内置 `aixcode/agents/builtins/{general-purpose,plan,explore}.md` 存在；`plan` 含 `disallowedTools: [Agent, EditFile, WriteFile]` + `maxTurns: 15` + `model: deepseek-pro`；`explore` 含 `tools: [ReadFile, Grep, Glob]` + `maxTurns: 30` + `model: deepseek-chat`
- [x] `AgentLoader` 三级搜索（`PROJECT_AGENTS_DIR=".aixcode/agents"`/`USER_AGENTS_DIR="~/.aixcode/agents"`/`importlib.resources` 内置）+ 项目覆盖内置 + 热重载（`grep -n "PROJECT_AGENTS_DIR\|USER_AGENTS_DIR\|def load_all\|def get\b" aixcode/agents/loader.py` + 单测）
- [x] `enable_verification` flag 守 verification 内置（默认不出现；`grep -n "enable_verification" aixcode/agents/loader.py`，若提供该内置则单测覆盖）

### 1.2 工具过滤

- [x] `ALL_AGENT_DISALLOWED_TOOLS=frozenset({"Agent","AskUser"})`（防递归）（`grep -n "ALL_AGENT_DISALLOWED_TOOLS" aixcode/agents/tool_filter.py`）
- [x] `CUSTOM_AGENT_DISALLOWED_TOOLS` + `ASYNC_AGENT_ALLOWED_TOOLS` 常量（`grep -n "CUSTOM_AGENT_DISALLOWED_TOOLS\|ASYNC_AGENT_ALLOWED_TOOLS" aixcode/agents/tool_filter.py`）
- [x] `resolve_agent_tools` 四层过滤 + MCP 直通，返回新 `ToolRegistry`（`grep -n "def resolve_agent_tools\|mcp_" aixcode/agents/tool_filter.py` + 单测各层）

### 1.3 Fork

- [x] `FORK_BOILERPLATE_TAG="<fork_boilerplate>"` + `FORK_BOILERPLATE` + `ForkError`（`grep -n "FORK_BOILERPLATE_TAG\|FORK_BOILERPLATE\|class ForkError" aixcode/agents/fork.py`）
- [x] `build_forked_messages` 嵌套 fork 拒绝（扫 TAG）+ `copy.deepcopy` + 补 `"interrupted"` 占位（`grep -n "def build_forked_messages\|deepcopy\|interrupted\|Cannot fork" aixcode/agents/fork.py` + 单测）

### 1.4 追踪与后台

- [x] `TraceNode` + `TraceManager`（create/update/complete/get_tree/get_total_tokens，三元组 agent_id/parent_id/trace_id）（`grep -n "class TraceNode\|class TraceManager\|def get_tree\|def get_total_tokens" aixcode/agents/trace.py` + 单测）
- [x] `BackgroundTask` + `TaskManager`（`_notify_queue: asyncio.Queue`，launch/_run_background/adopt_running/cancel/poll_completed，状态 running/completed/failed/cancelled）（`grep -n "class BackgroundTask\|class TaskManager\|_notify_queue\|def poll_completed\|def adopt_running" aixcode/agents/task_manager.py` + 单测状态机）
- [x] `MAX_NOTIFICATION_RESULT_LENGTH=5000` + `format_task_notification`(`<task-notification>` 含 Task ID/Agent/Status/Elapsed/Tokens/Result，超长截断) + `inject_task_notifications`（`grep -n "MAX_NOTIFICATION_RESULT_LENGTH\|task-notification\|def inject_task_notifications" aixcode/agents/notification.py` + 单测）

### 1.5 AgentTool

- [x] `AgentToolParams`（必填 prompt/description，可选 subagent_type/model/run_in_background）（`grep -n "class AgentToolParams" aixcode/tools/agent_tool.py`）
- [x] `AgentTool(Tool)`：`name="Agent"`、`category="command"`、`is_concurrency_safe=False`；构造参数含 `agent_loader/task_manager/trace_manager/parent_agent/provider_config/enable_fork`（`grep -n "class AgentTool\|name = \"Agent\"\|category" aixcode/tools/agent_tool.py`）
- [x] `execute` 三路径（未知类型报错列可用 / fork 关闭报错 / sync·background）+ `is_background = run_in_background or definition.background`（`grep -n "def execute\|is_background\|build_forked_messages\|run_to_completion\|task_manager.launch" aixcode/tools/agent_tool.py` + 单测）
- [x] 模型路由 `_select_model` + `_create_client_for_model`（inherit/deepseek-chat/deepseek-pro）（`grep -n "_select_model\|_create_client_for_model\|deepseek-pro" aixcode/tools/agent_tool.py` + 单测）
- [x] 子 Agent 独立 `PermissionChecker` 且复用父 `hook_engine`（`grep -n "PermissionChecker\|hook_engine\|PathSandbox" aixcode/tools/agent_tool.py`）

## 2. 接入完整性（杜绝死代码）

- [x] `grep -rn "AgentTool(" aixcode --include="*.py"` 命中 `aixcode/__main__.py` 一个非测试装配点
- [x] `registry.register(agent_tool)` 在 `__main__.py`，依赖（agent_loader/task_manager/trace_manager/parent_agent/provider_config/enable_fork）齐全注入（`grep -n "AgentTool\|register(agent_tool\|AgentLoader\|TaskManager\|TraceManager" aixcode/__main__.py`）
- [x] `task_manager.poll_completed` + `inject_task_notifications` 在 `aixcode/app.py` 主循环调用（`grep -n "poll_completed\|inject_task_notifications" aixcode/app.py`）
- [x] `task_manager.adopt_running` 在 `app.py` 中断路径调用（`grep -n "adopt_running" aixcode/app.py`）
- [x] `AixCodeApp.__init__` 含 `task_manager`/`trace_manager` 字段；`CommandContext.config` 塞 `"task_manager"`/`"trace_manager"`（`grep -n "task_manager\|trace_manager" aixcode/app.py`）
- [x] `/tasks`·`/trace` 加入 `ALL_COMMANDS`（`grep -n "TASKS_COMMAND\|TRACE_COMMAND" aixcode/commands/handlers/__init__.py`）
- [x] 子 Agent 复用父 `hook_engine`（不新建）（`grep -rn "hook_engine" aixcode/tools/agent_tool.py`）

## 3. 编译与测试

- [x] `python -m compileall aixcode tests` 通过
- [x] `python -m pytest tests/test_subagent.py -q` 全部通过，覆盖：parser / loader / tool_filter（各层）/ fork（嵌套拒绝 + deepcopy + interrupted）/ trace / task_manager（状态机）/ notification / AgentToolParams / AgentTool.execute 三路径 / 模型路由
- [x] `python -m pytest -q` 全绿（ch01–12 既有 + ch13 新增，不少于 ch12 末 502）
- [x] `python -c "from aixcode.agents.loader import AgentLoader; print(sorted(AgentLoader('.').load_all().keys()))"` 含 `explore / general-purpose / plan`
- [x] `python -c "from aixcode.tools.agent_tool import AgentTool; print(AgentTool.name, AgentTool.category)"` 输出 `Agent command`

## 4. 离线 smoke（自动验证）

- [x] `AgentLoader('.').load_all()` 含三档；`get("plan")` 的 `disallowed_tools` 含 Agent/EditFile/WriteFile、`model=="deepseek-pro"`
- [x] `resolve_agent_tools`：builtin agent 不含 Agent/AskUser；background 只含 `ASYNC_AGENT_ALLOWED_TOOLS`；project agent 不含 LoadSkill；`mcp_*` 直通
- [x] `build_forked_messages` 对含 `FORK_BOILERPLATE_TAG` 的父对话抛 `ForkError`；deepcopy 不改父
- [x] `TaskManager.launch` 跑一个返回字符串的 coro → `poll_completed` 拿到 `completed` 且 `result` 正确；`cancel` running → `cancelled`
- [x] `format_task_notification` 输出含 `<task-notification>` 与 Task ID/Status/Result
- [x] 装配后 `registry.get("Agent")` 非空，`description` 含 general-purpose/plan/explore；sync spawn（stub LLM 产 LoopComplete）`execute` 返回该文本

## 5. 端到端验证（手动操作 TUI，PowerShell）— 本章待用户手动验收

> 启动：`python -m aixcode`

- [ ] 让主 Agent「用 explore 子 Agent 调研某模块」→ LLM 调 `Agent` 工具（subagent_type=explore）→ 同步路径子 Agent 跑完返回调研结论给主 Agent
- [ ] 让主 Agent「在后台用 plan 子 Agent 制定计划」（run_in_background）→ 立即看到 `Task ID: ...` → 稍后主对话出现 `<task-notification>` 含结果
- [ ] fork：让主 Agent 不指定类型「fork 出去查 X」→ 强制后台 → 完成经 notification 注入
- [ ] `/tasks list` 列出后台任务及状态/token；`/tasks view <id>` 出详情；`/tasks cancel <id>` 取消 running 任务
- [ ] `/trace` 列最近调用树，父子缩进 + token 汇总
- [ ] 子 Agent 内不能再调 `Agent`（验证防递归：observe 子 Agent 的工具集不含 Agent）

## 6. 上一章（ch12 Hook）遗留手动验收 — 一并由用户操作

> 这两项是 ch12 落地时留下的真实 TUI 验收，代码与测试已就绪，仅需手动跑一次。

- [ ] ch12：`config.yaml` 配 pre_tool_use reject hook（`tool == "Bash" && args.command =~ /rm\s+-rf/` + `action.type=prompt` + `reject: true`），让 LLM 触发匹配的 Bash 命令，工具结果为 `Hook rejected: <message>`
- [ ] ch12：`config.yaml` 配缺 `command` 字段的非法 hook，`python -m aixcode` 启动 stderr 见 `Hook 配置错误：... requires 'command' field` 并退出码 1

## 7. 文档

- [x] `spec.md` / `tasks.md` / `checklist.md` 三件套齐全于项目根目录（`ls spec.md tasks.md checklist.md`）
- [x] `tasks.md` 13 个任务全部勾上
- [x] `checklist.md` 全部条目勾上（§5 本章手动 TUI、§6 上章遗留两项除外，留给用户）
