---
name: commit
description: 按 Conventional Commits 规范分析改动并生成一次 git commit
mode: inline
allowedTools: [Bash, ReadFile, Grep]
---
你现在执行「生成 commit」标准流程。严格按顺序：

1. 跑 `git status` 看清楚有哪些改动（暂存的 / 未暂存的 / 未跟踪的）。
2. 跑 `git diff`（必要时 `git diff --staged`）逐处理解改动**意图**，不要只看文件名。
3. 把改动归纳成一条 Conventional Commit：
   - 格式 `type(scope): subject`，type ∈ feat/fix/docs/style/refactor/test/chore。
   - subject 用祈使句、不超过 50 字、聚焦「为什么」而非「改了哪几行」。
   - 改动跨多个不相关主题时，提醒用户拆成多次 commit，不要硬塞一条。
4. `git add` 相关文件后 `git commit -m "..."`；提交完跑 `git log -1 --oneline` 回显结果。

约束：只做与本次改动相关的提交，不擅自改代码、不 `git push`。
额外要求：$ARGUMENTS
