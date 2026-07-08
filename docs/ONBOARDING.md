# ONBOARDING.md — 空白上下文冷接手引导

本文件是一段**可直接粘贴进任意 AI 编码工具**的引导语。任何模型/工具在没有任何先验上下文时，
照此执行即可安全接手本仓库。全部流程存在于仓库内、跟 git 走——不要依赖本对话之外的记忆。

---

## 冷接手引导语（复制以下整段）

> 你正在接手 `my_quant_project`（A股量化研究平台 v2）。这是一个**双代理开发仓库**，
> 全部规则以仓库内文件为准。请严格按下列步骤，不要自行发明流程。
>
> **第 0 步 · 确认你的角色**
> - 如果你要**写代码 + 单测** → 你是开发者，先完整读 `AGENTS.md`。
> - 如果你要**写任务卡 / 审查 / 合并 / 打 tag** → 你是规划者/审查者，先完整读 `CLAUDE.md`。
> - 两种角色随后都必须读 `docs/workflow.md`（状态机全文）与 `docs/tasks/STATUS.md`（唯一活状态源）。
>
> **第 1 步 · 只做一张卡（开发者）**
> - 从 `docs/tasks/STATUS.md` 选一张**状态 = `ready` 且指派给你（或无指派）**的卡；
>   `backlog` / 其他状态的卡一律不许动。
> - 任务卡的 Context / Scope / Non-goals / Files-to-touch / Acceptance criteria 是**唯一需求来源**：
>   卡里没写的不要做，写了的必须做完。
> - 从 `v2` 切出分支 `task/TASK-XXX-<slug>`，所有提交都在该分支；提交信息用
>   `type(scope): summary [TASK-XXX]`。
>
> **第 2 步 · 守住硬红线（违反 = 直接打回，且大多有机器门会拦你）**
> - 改动文件**不得超出**该卡 `## Files to touch` 白名单 → `python scripts/check_whitelist.py` 会拦。
> - `src/quant/` 内**禁止硬编码绝对路径**（用 `quant.config.Settings` / `.env`）→ `python scripts/check_no_hardcoded_paths.py` 会拦。
> - **不提交 >200KB 数据文件**；单测不联网、只用 `tests/fixtures/` 与 `tmp_path`。
> - **金融正确性**：指标只用 ≤t 数据（禁未来函数）；入场一律 t 日信号 → t+1 开盘；
>   有涨跌停/停牌标记时必须过滤不可成交样本。语义见 `docs/conventions.md`、`docs/backtest_platform.md`。
> - **永不**自行合并到 `v2`/`main`、永不打 tag、永不 push `main`。
>
> **第 3 步 · 提交前必须全绿（本地先跑）**
> ```bash
> ruff check . && ruff format --check .
> pytest -q -m "not integration"
> python scripts/check_no_hardcoded_paths.py
> python scripts/check_whitelist.py          # 在 task 分支上
> ```
> 外加：卡内每一条 Acceptance criteria 命令本地可跑且结果符合预期。
>
> **第 4 步 · 收尾**
> - 全部满足 → 把 `docs/tasks/STATUS.md` 中自己那行状态改为 `review` 并提交 → **停止**，等审查者。
> - 若实现中发现卡本身设计不可行 → 不要绕路自造方案，在 STATUS.md 备注列说明并置 `review`，等规划者改卡。

---

## 机器门一览（无需记忆，跑绿即可）

流程红线尽量由检查强制，清单见 `docs/workflow.md` §机器强制门。你不需要背规则，
只要让下列命令全绿、并跑通卡内验收命令即可：`ruff`、`pytest -m "not integration"`、
`check_no_hardcoded_paths.py`、`check_whitelist.py`（task 分支）。语义级红线（未来函数、
对齐口径）无法机器化，由任务卡验收命令 + 规划者审查把守。

## 延伸阅读（按需）

| 要做什么 | 先读 |
|---|---|
| 为什么是这个架构 | `docs/architecture.md` + `docs/decisions/ADR-000x` |
| 里程碑与 gate | `docs/roadmap.md` |
| ETL / staging / qlib dump | `docs/data_platform.md` |
| 指标移植 | `docs/indicators/README.md` |
| 回测 / 事件研究 / 约束语义 | `docs/backtest_platform.md` |
