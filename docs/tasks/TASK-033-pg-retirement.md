# TASK-033: PG 归档退役（ADR-0002 executed）

- Milestone: M3　|　State: backlog
- Branch: `task/TASK-033-pg-retirement`　|　Depends: TASK-016, TASK-025, TASK-032, TASK-073 + **M3 gate 由规划者确认**

## Context
ADR-0002 迁移安全网条款：016/025/032 三份对齐报告全绿 + M3 gate 达成后，PG 黄金参照完成历史使命——归档后容器停用、`quant/db` 代码删除。**ADR-0005 §8 收紧**：pg_dump 归档与快照 manifest 由 TASK-073 前置完成；本卡置 ready 还需规划者完成**恢复演练**（无 pg_quant 容器环境从 dump 恢复并复跑 016/025/032 黄金验证）。**本卡由规划者在 `docs/reviews/M3-gate-report.md`（含演练记录）写完之后才置 ready**；在那之前任何人不得动 PG（红线：黄金参照在 M3 gate 前保持可用且冻结）。

## Goal
PG 数据完整归档、可恢复验证通过；仓库内 PG 依赖清零；停容器后全测试仍绿。

## Scope
1. **归档核验**（dump 已由 TASK-073 完成；先核验后删码，顺序不可反）：
   ```bash
   python scripts/snapshot_manifest.py verify --manifest <TASK-073 生成的最新 manifest>
   # 全绿 = dump 与全数据链自冻结以来无漂移；任何不符 → 停止并报告规划者
   docker stop pg_quant   # 容器与镜像保留不删（用户机器资产，只停不删）
   ```
2. **删码**：`src/quant/db/` 整目录；`scripts/validate_vs_pg.py`；`cli.py` 的 `validate` 命令；相关测试（`tests/unit/test_validate_helpers.py` 等）；`pyproject.toml` 去 psycopg2 依赖。
3. **文档**：ADR-0002 状态行改 `executed（2026-07-xx，dump=archive/…）`；`docs/data_platform.md` 如引用 validate 流程加"已退役"注记；`.env.example` 清 PG 变量（如有）。

## Non-goals
删 docker 容器/镜像本体；动 staging/qlib 数据；改任何研究代码。

## Files to touch
删除：`src/quant/db/**`, `scripts/validate_vs_pg.py`, 相关 tests。修改：`src/quant/cli.py`, `pyproject.toml`, `docs/decisions/ADR-0002-qlib-bin-storage-postgres-decommission.md`, `docs/data_platform.md`, `.env.example`（如涉及）。

## Acceptance criteria
1. `ls -lh /home/yang/quant_data/archive/pg_quant_*.dump` 存在；`python scripts/snapshot_manifest.py verify --manifest <最新>` exit 0（贴 STATUS 备注）。
2. `grep -rn "psycopg2\|pg_quant\|quant.db" src/ scripts/ pyproject.toml` 为空（docs/ 中历史记述除外）。
3. `docker ps -a` 显示 pg_quant 为 Exited 状态下：`pytest -q -m "not integration"` + `pytest -q tests/integration -m integration` + `ruff check .` 全绿。
4. 全新环境冒烟：`pip install -e ".[dev]"` 后 `python -c "import quant"` 成功（无 psycopg2 残留 import）。

## Notes / risks
- 删除类 commit 与 `git mv` 一样要独立、原子（先"删码"一个 commit，再"文档/依赖"一个 commit），方便万一回滚。
- 归档 dump 属于 DATA_ROOT，不进 git；只有路径与校验信息进 STATUS/review。
- 若 dump 过程发现 PG 已损坏/数据不全 → 停止，报告规划者（不许带伤退役）。
