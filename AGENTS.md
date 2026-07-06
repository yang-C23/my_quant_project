# AGENTS.md — 开发代理（Codex）操作契约

你是本仓库的**开发代理**。规划与审查由另一个代理（Claude，见 `CLAUDE.md`）负责。
你的全部工作以 `docs/tasks/` 下的任务卡为准；本文件定义你必须遵守的环境、命令与纪律。

## 1. 项目一句话

A股（后扩美股）量化研究平台 v2：TDX 数据 → Parquet staging → qlib bin 存储；qlib 为主研究/回测引擎，Backtrader 为交易级验证器；FastAPI + Lightweight Charts 本地看板；指标因子化。架构详见 `docs/architecture.md`，全部关键决策见 `docs/decisions/`。

## 2. 环境与常用命令

```bash
# 激活环境（若 TASK-001 评审后确定新建 my_quant_v2 环境，以 docs/tasks/STATUS.md 顶部公告为准）
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project

# 安装（可编辑模式 + 开发依赖）
pip install -e ".[dev]"

# 质量门（提交前必须全绿）
ruff check . && ruff format --check .
pytest -q -m "not integration"

# 集成测试（需要 DATA_ROOT 真实数据，通常由审查者运行，不进 CI）
pytest -q -m integration
```

运行时路径一律来自 `.env`（模板见 `.env.example`），经 `quant.config.Settings` 读取。
**严禁在代码中硬编码 `/mnt/d`、`/home/yang` 等绝对路径。**

## 3. 任务协议（必须逐条遵守）

1. **只做一张卡**：从 `docs/tasks/STATUS.md` 中挑选状态为 `ready`、且你被指派（或无指派）的一张任务卡；`backlog` 状态的卡不许动。
2. **读卡再动手**：任务卡中的 Context / Scope / Non-goals / Files-to-touch / Acceptance criteria 是唯一需求来源。卡里没写的不要做，卡里写了的必须做完。
3. **分支**：从 `v2` 切出 `task/TASK-XXX-<slug>`，全部提交都在该分支上。
4. **提交格式**：约定式提交 + 卡号后缀，例如
   `feat(etl): parallel .day parser to parquet staging [TASK-010]`。
5. **完成后**：确认 DoD（见下）全部满足 → 把 `docs/tasks/STATUS.md` 中自己那一行状态改为 `review` 并提交 → **停止**。
6. **永不自行合并**到 `v2` / `main`，永不打 tag，永不 push 到 `main`。
7. **返工**：若收到 `docs/reviews/TASK-XXX-review.md` 且状态为 `changes_requested`，在**原分支**上按评审意见继续修改，完成后再次置为 `review`。

## 4. Definition of Done（每张卡通用）

- [ ] 卡中每条 Acceptance criteria 的命令在本地可运行且结果符合预期；
- [ ] 新增/修改的代码有对应单元测试；`pytest -q -m "not integration"` 全绿；
- [ ] `ruff check .` 与 `ruff format --check .` 全绿；
- [ ] 改动文件不超出卡中 Files-to-touch 白名单（`docs/tasks/STATUS.md` 中自己那一行除外）；
- [ ] 公共函数有类型注解与简短 docstring；无 `print` 调试残留（用 `logging`）。

## 5. 硬规则（违反 = 直接打回）

- **不改**：`pyproject.toml` 的依赖、`.github/`（CI）、`AGENTS.md`、`docs/decisions/`、`docs/workflow.md`——除非任务卡明确授权。
- **不新增依赖**，除非卡中列出（含版本）。
- **不写 `DATA_ROOT`**（`/home/yang/quant_data`）下的任何文件，除非通过卡中指定的 CLI 入口；单元测试只用 `tests/fixtures/` 与 `tmp_path`。
- **不提交任何 >200KB 的数据文件**；fixture 必须小而真实（生成方法写进 `tests/fixtures/README.md`）。
- **单元测试不联网**；需要网络的逻辑（如 yfinance）必须 mock。
- **不跑全量历史 ETL/回测当测试**——那是审查者在集成阶段做的事。
- **金融正确性红线**：任何指标/信号只准使用 ≤ t 的数据（禁止未来函数）；入场一律 t 日信号 → t+1 开盘；有涨跌停/停牌标记时必须过滤不可成交样本。语义细节见 `docs/conventions.md` 与 `docs/backtest_platform.md`。

## 6. 代码风格速览（详见 docs/conventions.md）

- Python ≥3.10，src 布局：`src/quant/`；ruff 统一 lint + format（配置在 `pyproject.toml`）。
- 向量化优先：pandas/numpy，禁止逐行 Python 循环处理全市场数据（单文件解析这类天然逐条的除外）。
- 指标层（`quant/indicators/`）只准 import `quant.tdx.functions` + pandas/numpy，输入输出都是 DataFrame/Series；不准触碰 IO。
- 内部符号格式统一 `sh600000` 小写；qlib 侧 `SH600000`；转换只经 `quant.data.symbols`。
- 日期一律 `datetime64[ns]`（naive，交易所本地时区）。

## 7. 你会用到的参考文档

| 要做什么 | 先读 |
|---|---|
| ETL / staging / qlib dump | `docs/data_platform.md` |
| 指标移植（通达信公式 → Python） | `docs/indicators/README.md` + 对应指标文件 |
| 回测/事件研究/约束语义 | `docs/backtest_platform.md` |
| 看板 API / 前端 | `docs/dashboard.md` |
| 为什么是这个架构 | `docs/architecture.md` + `docs/decisions/ADR-000x` |
