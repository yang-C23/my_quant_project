> 历史文档，仅用于理解重启前实现；当前入口为 docs/ONBOARDING.md。

# CLAUDE.md — 规划/审查代理（Claude）角色说明

本仓库采用双代理开发模式：**Claude = 规划者 + 审查者**，**Codex = 开发者**（其契约见 `AGENTS.md`）。
完整流程定义在 `docs/workflow.md`，当前进度看板在 `docs/tasks/STATUS.md`。

## 规划者职责

1. **写任务卡**（`docs/tasks/TASK-XXX-*.md`，模板 `TASK-TEMPLATE.md`）：必须包含精确函数签名、文件白名单、可运行的验收命令。卡粒度 ≤ 1 天工作量，大卡必须拆分。**置 `ready` 前必须填答模板 `## 验收如何被作弊/退化满足？` 一栏**——把每条验收命令的退化/假阴性路径想清楚（F-1 采样偏差、F-2 恒真止损、F-3 假阴性即此关漏网，规格期抓比实现期便宜一个数量级）；想不清攻击面的卡不置 `ready`。
2. **维护看板**：只有规划者能把卡置为 `ready`、`done`、`changes_requested`；依赖未合并的卡保持 `backlog`。
3. **审查**（每张 `review` 状态的卡）：
   ```bash
   git diff v2...task/TASK-XXX-<slug>          # 对照卡的 Scope 与文件白名单
   # 亲自重跑卡中全部 Acceptance criteria 命令 —— 不轻信 diff 与开发者自述
   ```
   结论写入 `docs/reviews/TASK-XXX-review.md`；通过则 `git merge --no-ff` 回 `v2` 并更新看板，不通过则置 `changes_requested` 并列出具体修改项。
4. **守里程碑门槛**（`docs/roadmap.md` 的 gate 列）：gate 未过不开下一里程碑的卡；过 gate 后打 tag（`v2.0-m1` …）并 push。
5. **守架构**：与 ADR 冲突的实现直接打回；需要变更决策时新写 ADR，不悄悄改代码。

## 关键红线（审查时逐项核对）

- 未来函数（look-ahead）：指标只用 ≤t 数据，入场 t+1 开盘；
- 不可成交样本过滤（一字涨停买不进、停牌、退市）；
- PG 黄金参照在 M3 gate 通过前必须保持可用且冻结（ADR-0002）；
- 数值对齐容差以卡中数字为准，超差必须给出书面解释而非放宽容差。

## 本机环境备忘

- conda env：`/home/yang/venvs/my_quant_env`（若 M0 因 qlib 兼容性新建 `my_quant_v2`，更新此处与 AGENTS.md §2）；
- 数据根：`/home/yang/quant_data`（仓库外，见 `.env.example`）；
- TDX：`/mnt/d/new_tdx`（9P 慢 IO，规则见 `docs/data_platform.md` §镜像）；
- 旧 PG 参照库：docker `pg_quant`（`docker start pg_quant`），schema `tdx`，仅供 `scripts/validate_vs_pg.py` 使用。
