---
name: test
description: 自动识别项目类型、运行测试套件并定位失败根因
mode: inline
allowedTools: [Bash, ReadFile, Grep, Glob]
---
你现在执行「跑测试」标准流程。

第一步：检测项目类型（按存在的标志文件选测试命令）：
- `pyproject.toml` 或 `setup.py` → `pytest -q`（或 `python -m pytest -q`）。
- `go.mod` → `go test ./...`。
- `package.json` → `npm test`（先看 scripts.test 是否存在）。
- `Cargo.toml` → `cargo test`。
- 多种并存时，先问用户或选与本次改动最相关的那套。

第二步：运行测试，完整读输出。

第三步：若有失败，逐个定位根因，并**区分两类 bug**：
- **代码 bug**：实现不符合预期 → 修实现。
- **测试 bug**：测试本身写错（过期断言 / 错误 fixture / 环境假设）→ 修测试。
判断依据是「需求/规格期望的正确行为」，不要为了让测试变绿而盲目改实现或删断言。

第四步：修复后重跑直到全绿，回报「改了什么、为什么」。
约束：只跑测试与必要的定位命令，不擅自改无关代码。
额外要求：$ARGUMENTS
