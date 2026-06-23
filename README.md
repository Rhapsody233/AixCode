# AixCode

> 一个用 **Python 从零构建**的终端 AI 编程助手，对标 Claude Code，后端默认接 **Deepseek**（OpenAI 兼容协议）。
> 在终端里通过工具调用，在你的代码仓库中完成真实的编程工作：读写文件、执行命令、检索代码、多轮自治、子 Agent 协作。

<p align="center">
  <img src="img/1.png" alt="AixCode 演示" width="80%">
</p>

---

## ✨ 功能特性

**核心对话与工具**

- Deepseek / OpenAI 兼容协议的异步**流式对话**
- 内置工具：`ReadFile` / `WriteFile` / `EditFile` / `Bash` / `Glob` / `Grep`，以及 `ToolSearch`（按需披露）、`AskUserQuestion`（向用户提问）
- 统一的 `Tool` 抽象 + 工具注册中心，支持「按需工具」渐进披露，避免一次性塞满上下文

**Agent 自治循环**

- 多轮 **ReAct 循环**：调用模型 → 执行工具 → 回灌结果 → 继续，直到任务完成
- 工具批量执行（只读工具可并发）、流式事件输出

**权限与安全**

- 五档**权限模式**：`strict` / `default` / `accept` / `bypass` / `plan`
- 危险命令检测、路径沙箱、规则引擎、人在回路（HITL）确认
- Plan 模式：只读调研、产出计划待审批

**上下文与记忆**

- 上下文**自动压缩**（按真实 token 数触发）、工具结果预算与持久化
- 自动记忆提取、项目指令（`AIXCODE.md`）注入

**扩展机制**

- **MCP**：接入 MCP server 的 **工具 / 资源（`ReadMcpResource`）/ 提示（`/mcp__server__prompt`）**
- **Skill**：渐进式技能加载（`LoadSkill`）
- **Hook**：15 个生命周期事件 × 四类动作（`command` / `prompt` / `http` / `agent`）
- **Slash 命令**：`/help` `/status` `/compact` `/plan` `/do` `/mode` `/memory` `/session` `/skill` `/tasks` `/trace` `/worktree` 等

**多 Agent 协作**

- **SubAgent**：上下文隔离的子 Agent（同步 / 后台 / fork 三种路径）、调用树追踪、内置 `general-purpose` / `plan` / `explore`
- **Worktree**：基于 git worktree 的隔离工作区，工具按各自 `work_dir` 解析路径
- **AgentTeam**：网状协作团队——多队员并行、邮箱互发消息、共享任务清单，主 Agent 可切 **Coordinator Mode** 专职调度（本机走 in-process 后端）

**CLI 与 Headless**

- 交互式 REPL，或 `-p` **单次执行模式**（跑完打印结果退出，可管道/脚本化）

---

## 🚀 安装

需要 Python 3.10+。

```powershell
git clone <your-repo-url> AixCode
cd AixCode
pip install -e .
```

`pip install -e .` 会注册全局命令 `aixcode`（可编辑安装，改代码无需重装）。之后在任意目录都能直接使用。

> 若提示 `aixcode 不是命令`，说明 Python 的 Scripts 目录不在 PATH 上。用
> `python -c "import sysconfig; print(sysconfig.get_path('scripts'))"`
> 查出路径并加入系统 PATH，或改用 `python -m aixcode`。

---

## ⚙️ 配置

在项目根目录（或运行时的当前目录）创建 `config.yaml`：

```yaml
# 必填：供应商配置
protocol: openai                      # OpenAI 兼容协议（承载 Deepseek）
model: deepseek-chat                  # 或 deepseek-reasoner（带思考链）
base_url: https://api.deepseek.com    # 请求地址
api_key: sk-xxxxxxxxxxxxxxxxxxxx       # 你的 API key
```

四个字段缺一不可。换其他 OpenAI 兼容后端时，改 `base_url` / `model` / `api_key` 即可。

<details>
<summary><b>可选配置（MCP / Hook / 团队）</b></summary>

```yaml
# 接入 MCP server（stdio 或 Streamable HTTP）
mcp_servers:
  local-tools:
    command: python
    args: ["-m", "my_mcp_server"]
  remote-tools:
    url: https://example.com/mcp
    headers:
      Authorization: "Bearer ${MY_TOKEN}"   # ${VAR} 会从环境变量展开

# 生命周期 Hook（command / prompt / http / agent 四类动作）
hooks:
  - event: post_tool_use
    action:
      type: command
      command: "echo 工具已执行"

# AgentTeam（Windows 必须设为 in-process）
teammate_mode: in-process
enable_coordinator_mode: false
```

</details>

---

## 📖 使用

```powershell
# 交互式 REPL
aixcode

# 单次执行（headless）：跑完打印结果退出
aixcode -p "帮我给 utils.py 的 parse() 加单元测试"

# 指定工作目录 / 模型 / 配置
aixcode -p "重构 X" --work-dir D:\repo --model deepseek-reasoner --config D:\AixCode\config.yaml
```

进入 REPL 后，直接用自然语言下达任务，或用 `/` 调用斜杠命令（`/help` 查看全部）。

---

## 🖼️ 更多演示

<p align="center">
  <img src="img/2.png" alt="AixCode 演示 2" width="80%">
</p>

<p align="center">
  <img src="img/3.png" alt="AixCode 演示 3" width="80%">
</p>

---

## 🗂️ 项目结构

```
aixcode/
├── agent.py            # 多轮 ReAct 自治循环
├── client.py           # LLM 客户端（OpenAI 兼容流式）
├── conversation.py     # 对话历史模型
├── config.py           # 配置加载
├── cli.py / headless.py / runtime.py   # CLI 入口 / headless / 装配
├── prompts.py          # 系统提示拼装
├── tools/              # 工具系统（文件/Bash/检索 + MCP/Skill/Agent 等）
├── permissions/        # 权限模式 / 沙箱 / 规则引擎
├── context/            # 上下文压缩 / token 预估
├── memory/             # 自动记忆
├── commands/           # Slash 命令
├── skills/             # Skill 系统
├── hooks/              # Hook 引擎
├── agents/             # SubAgent（解析/加载/过滤/fork/追踪）
├── worktree/           # git worktree 隔离
├── teams/              # AgentTeam 协作团队
└── mcp/                # MCP 集成
```

---

## 📝 说明

本项目为逐章构建的终端 AI 编程助手实现，用于学习与实践。欢迎按需改造、扩展后端与工具。
