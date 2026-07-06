# TASK-003: quant.config 设置模块（消灭硬编码路径）

- Milestone: M0　|　State: backlog
- Branch: `task/TASK-003-config`　|　Depends: TASK-001

## Context
conventions.md（禁止硬编码路径）；data_platform.md §1（DATA_ROOT 布局）。v1 在 `quant/db/connection.py`、旧脚本里硬编码 DSN 与 `/mnt/d`。

## Goal
全部运行时路径/连接串来自 `.env`（pydantic-settings），`src/` 下无任何绝对路径字面量。

## Scope
```python
# src/quant/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")
    data_root: Path = Path("~/quant_data")          # env: DATA_ROOT
    tdx_home: Path = Path("/tdx")                    # env: TDX_HOME（.env.example 里给真实值）
    pg_dsn: str = ""                                 # env: QUANT_DB_DSN（仅 validate_vs_pg 用，M3 删）
    etl_workers: int = 20                            # env: ETL_WORKERS
    #派生属性（@property）：mirror_dir, staging_dir, qlib_cn_daily_uri, qlib_us_daily_uri, archive_dir

@lru_cache
def get_settings() -> Settings: ...
```
- `.env.example`：带注释的真实值模板（`DATA_ROOT=/home/yang/quant_data`、`TDX_HOME=/mnt/d/new_tdx`、`QUANT_DB_DSN=host=localhost port=5432 dbname=quant_db user=quant password=quant123`）。
- 重构 `src/quant/db/connection.py`：DSN 只从 `get_settings().pg_dsn` 读，删除内置默认凭据。
- `.gitignore` 确认含 `.env`。

## Non-goals
不迁移旧冻结脚本的路径参数；不实现任何 ETL 逻辑。

## Files to touch
`src/quant/config.py`(新), `.env.example`(改/建), `src/quant/db/connection.py`, `tests/unit/test_config.py`(新), `.gitignore`。

## Acceptance criteria
1. `grep -rnE "/mnt/d|/home/yang|password=" src/ --include='*.py' | grep -v "FROZEN"` 输出为空（冻结脚本在 scripts/，不在 src 检查范围内的除外——`src/quant/etl/{tdx_parser,gbbq,blocks}.py` 也必须干净）。
2. `pytest -q tests/unit/test_config.py` 全绿。
3. `python -c "from quant.config import get_settings; print(get_settings().staging_dir)"` 输出 DATA_ROOT 下路径。

## Test plan
`test_config.py`：monkeypatch env 覆盖 DATA_ROOT/TDX_HOME → 派生属性正确；无 .env 时默认值可用；`~` 展开正确。

## Notes / risks
`Path` 字段需 `expanduser()`（validator）；`lru_cache` 导致测试间污染 → 测试里 `get_settings.cache_clear()`。
