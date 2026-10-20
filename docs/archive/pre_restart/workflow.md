> 历史文档，仅用于理解重启前实现；当前入口为 docs/ONBOARDING.md。

# workflow.md — 规划者 ↔ 开发者 双代理工作流

## 角色

| 角色 | 承担者 | 职责 | 契约文件 |
|---|---|---|---|
| 规划者/审查者 | Claude (Fable 5) | 架构、任务卡、代码与结果审查、合并、打 tag | `CLAUDE.md` |
| 开发者 | Codex | 按任务卡实现代码 + 单测 | `AGENTS.md` |
| 决策者 | 用户 | 架构级取舍（记录为 ADR）、里程碑验收 | `docs/decisions/` |

## 任务卡状态机

```
backlog ──(规划者: 依赖就绪)──▶ ready ──(开发者认领)──▶ in_progress ──▶ review
                                                            ▲              │
                                                            │(改完再提)     │(规划者审查)
                                                   changes_requested ◀─────┤
                                                                           ▼
                                                                         done
```

- 状态唯一记录处：`docs/tasks/STATUS.md`（单表看板）。
- 开发者只能做两种状态变更：`ready→in_progress`（认领时）与 `in_progress→review` / `changes_requested→review`（完成时）。
- 其余状态变更（含 `→done`）只有规划者可做。

## 一张卡的完整生命周期

1. **规划者写卡**：复制 `docs/tasks/TASK-TEMPLATE.md`，填入 Context（链接到 architecture/ADR/指标文档的具体小节）、精确签名、文件白名单、**可运行的验收命令**。置 `ready`。
2. **开发者认领**：STATUS.md 行改 `in_progress`，切分支 `task/TASK-XXX-<slug>`（自 `v2`）。
3. **开发**：小步提交，约定式提交信息 + `[TASK-XXX]` 后缀。
4. **自检**：跑完 AGENTS.md §4 的 DoD 清单，STATUS.md 行改 `review`，停止。
5. **审查**（规划者）：
   - `git diff v2...task/TASK-XXX-<slug>` 逐条对照 Scope 与白名单；
   - **亲自重跑**卡中全部验收命令（含单测与 lint）；
   - 结论写 `docs/reviews/TASK-XXX-review.md`（模板见该目录 README）；
   - 通过：`git checkout v2 && git merge --no-ff task/TASK-XXX-<slug>`，STATUS 置 `done`，删任务分支；
   - 不通过：STATUS 置 `changes_requested`，评审文件中列出编号修改项，回到步骤 3。
6. **里程碑 gate**：某里程碑全部卡 `done` 后，规划者运行 `docs/roadmap.md` 中该里程碑的 gate 验证（通常是集成级命令 + 对齐报告），报告存 `docs/reviews/M?-gate-report.md`；通过后 `git tag v2.0-m? && git push origin v2 --tags`。

## Git 约定

- `main`：v2 全部里程碑验收前不动；最终由用户决定何时将 `v2` 合回。
- `v2`：长期集成分支，只接受 `--no-ff` 的任务分支合并与规划者的文档提交。
- `task/TASK-XXX-<slug>`：短命分支，合并后即删。
- 文件移动（`git mv`）必须独立成 commit，不与内容修改混在一起（保 `git log --follow`）。
- 里程碑 tag：`v2.0-docs`, `v2.0-m0` … `v2.0-m6`。
- 提交信息：`type(scope): summary [TASK-XXX]`，type ∈ feat/fix/refactor/test/docs/chore/perf。

## 并行规则

- 同一时间每个开发代理最多一张 `in_progress` 卡。
- 无共享文件白名单的卡可以并行（如 TASK-011 与 TASK-012）；有依赖的卡由规划者用 `Depends:` 字段串行化，依赖未 `done` 不置 `ready`。

## 冲突与升级

- 卡内容与 `docs/` 冲突 → 以卡为准并在 review 时由规划者修文档；
- 卡与 ADR 冲突 → 停止，报告规划者（ADR 优先级最高）；
- 实现中发现卡的设计不可行 → 不要绕路自行发明，在 STATUS.md 备注列说明并置 `review`，等规划者改卡。

## 机器强制门（冷接手鲁棒性来源）

流程红线尽量由检查强制，不依赖模型自觉。任何工具/模型在空白上下文只要能跑绿这些门，交付就满足硬约束：

| 门 | 强制什么 | 触发 |
|---|---|---|
| `ruff check .` / `ruff format --check .` | lint + 格式 | pre-commit + CI |
| `pytest -q -m "not integration"` | 单测全绿 | CI |
| `python -c "import qlib, quant"` | 依赖冒烟（M0 gate 门） | CI |
| `scripts/check_no_hardcoded_paths.py` | `src/quant/` 字符串字面量无硬编码绝对路径（legacy `scripts/` 豁免） | pre-commit + CI |
| `check-added-large-files`（maxkb=200） | 无 >200KB 数据文件（`docs/parity/` 豁免） | pre-commit |
| `scripts/check_whitelist.py` | 改动文件不超任务卡 `## Files to touch` | CI（`task/**`）+ 审查者/开发者本地 |

金融正确性红线（未来函数、不可成交过滤、口径对齐）仍靠任务卡验收命令 + 规划者审查把守——这些是语义门，无法用通用脚本机器化，是审查的核心价值所在（见 `CLAUDE.md` 关键红线）。

## 建议的分支保护（由用户在 GitHub 手动启用，非自动）

- `v2`：要求 PR 且 CI 全绿方可合并；`test` 与 `whitelist` 两 job 设为 required checks。
- `main`：受保护，仅用户手动决定何时把 `v2` 合回。
- `task/**`：不设保护，短命分支。
