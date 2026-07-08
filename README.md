# my_quant_project

A-share quantitative research platform v2: TDX data is staged as Parquet,
dumped into qlib bin storage, researched with qlib-first workflows, and
validated with Backtrader where trading constraints matter.

v1 历史见 `main` 分支。

## AI agents start here

本仓库用双代理开发流程，全部流程存在于仓库内、跟 git 走。按角色分流：

- **开发者**（写代码 + 单测）→ 读 `AGENTS.md`
- **规划者 / 审查者**（写卡、审查、合并）→ 读 `CLAUDE.md`
- 两者随后都读 `docs/workflow.md`（状态机）+ `docs/tasks/STATUS.md`（活状态，唯一状态源）

空白上下文接手：直接从 **`docs/ONBOARDING.md`** 开始，它是可粘贴进任意工具的引导语。

## Installation

```bash
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` for local data paths and the temporary PostgreSQL reference DSN.
Runtime paths and connection strings are read through `quant.config.Settings`.

## Commands

| Command | Status | Purpose |
|---|---|---|
| `myquant --version` | available | Print the installed package version. |
| `myquant etl full` | planned M1 | Mirror TDX data and build Parquet staging. |
| `myquant dump cn-daily` | planned M1 | Rebuild qlib `cn_daily` bin data from staging. |
| `myquant update` | planned M1 | Append daily updates to staging and qlib. |
| `myquant validate` | planned M1/M3 | Compare v2 outputs with the temporary PG reference. |

Developer quality gate:

```bash
ruff check .
ruff format --check .
pytest -q -m "not integration"
```

## Documentation

- `docs/architecture.md`: target architecture and module boundaries.
- `docs/data_platform.md`: data root layout, staging schema, and qlib dump contract.
- `docs/backtest_platform.md`: research and backtest tiers.
- `docs/conventions.md`: coding, testing, and financial correctness rules.
- `docs/tasks/STATUS.md`: task board and review state.
- `AGENTS.md`: Codex implementation protocol.
- `CLAUDE.md`: planning and review protocol.
