# TASK-033: PG 归档退役（ADR-0002 executed）

- Milestone: M3　|　State: backlog
- Branch: `task/TASK-033-pg-retirement`　|　Depends: TASK-016, TASK-025, TASK-032 + **M3 gate 由规划者确认**

## Context
ADR-0002 迁移安全网条款：016/025/032 三份对齐报告全绿 + M3 gate 达成后，PG 黄金参照完成历史使命——pg_dump 归档，容器与 `quant/db` 代码删除。**本卡由规划者在 `docs/reviews/M3-gate-report.md` 写完并确认三报告全绿之后才置 ready**；在那之前任何人不得动 PG（红线：黄金参照在 M3 gate 前保持可用且冻结）。

## Goal
PG 数据完整归档、可恢复验证通过；仓库内 PG 依赖清零；停容器后全测试仍绿。

## Scope
1. **归档**（先归档后删码，顺序不可反）：
   ```bash
   docker start pg_quant
   pg_dump（容器内 pg_dump -Fc，schema tdx 全量）→ /home/yang/quant_data/archive/pg_quant_$(date +%Y%m%d).dump
   pg_restore --list <dump> 验证可读；记录 dump 大小与表清单到 STATUS 备注
   docker stop pg_quant   # 容器与镜像保留不删（用户机器资产，只停不删）
   ```
2. **删码**：`src/quant/db/` 整目录；`scripts/validate_vs_pg.py`；`cli.py` 的 `validate` 命令；相关测试（`tests/unit/test_validate_helpers.py` 等）；`pyproject.toml` 去 psycopg2 依赖。
3. **文档**：ADR-0002 状态行改 `executed（2026-07-xx，dump=archive/…）`；`docs/data_platform.md` 如引用 validate 流程加"已退役"注记；`.env.example` 清 PG 变量（如有）。

## Non-goals
删 docker 容器/镜像本体；动 staging/qlib 数据；改任何研究代码。

## Files to touch
删除：`src/quant/db/**`, `scripts/validate_vs_pg.py`, 相关 tests。修改：`src/quant/cli.py`, `pyproject.toml`, `docs/decisions/ADR-0002-qlib-bin-storage-postgres-decommission.md`, `docs/data_platform.md`, `.env.example`（如涉及）。

## Acceptance criteria
1. `ls -lh /home/yang/quant_data/archive/pg_quant_*.dump` 存在；`pg_restore --list` 输出 tdx schema 表清单（贴 STATUS 备注）。
2. `grep -rn "psycopg2\|pg_quant\|quant.db" src/ scripts/ pyproject.toml` 为空（docs/ 中历史记述除外）。
3. `docker ps -a` 显示 pg_quant 为 Exited 状态下：`pytest -q -m "not integration"` + `pytest -q tests/integration -m integration` + `ruff check .` 全绿。
4. 全新环境冒烟：`pip install -e ".[dev]"` 后 `python -c "import quant"` 成功（无 psycopg2 残留 import）。

## Notes / risks
- 删除类 commit 与 `git mv` 一样要独立、原子（先"删码"一个 commit，再"文档/依赖"一个 commit），方便万一回滚。
- 归档 dump 属于 DATA_ROOT，不进 git；只有路径与校验信息进 STATUS/review。
- 若 dump 过程发现 PG 已损坏/数据不全 → 停止，报告规划者（不许带伤退役）。
