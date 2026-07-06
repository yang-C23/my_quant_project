# M0 Gate Report — 脚手架里程碑验收

- 日期：2026-07-06　|　验收者：Claude (Fable 5)　|　v2 = b2987c4（TASK-001~004 全部合并）

## Gate 标准（roadmap.md）与结果

| 检查 | 结果 |
|---|---|
| 全新克隆 → `pip install -e ".[dev]"` | PASS（临时目录克隆 v2 分支，独立安装） |
| 克隆内 `pytest -q -m "not integration"` | PASS（5 passed） |
| 克隆内 `ruff check .` + `ruff format --check .` | PASS（26 files） |
| `python -c "import qlib, quant"` | PASS（qlib 0.9.7，现有 `my_quant_env`，无需回退环境） |
| CI 云端绿灯 | **待用户网页确认**（私有仓库本机无 token；工作流步骤已本地等价复跑全过，v2 push 触发的 run 可在 GitHub Actions 页查看） |

## 附注

- qlib 0.9.7 与 numpy 2.x / pandas 2.x 在本机组合下 import 正常——ADR-0001 风险条的回退阶梯（新建 env / 钉 numpy<2）**未被触发**；深度兼容性（D.features 等运行时路径）将在 TASK-013 的单测中进一步覆盖。
- 审查期间修复仓库级隐患：v1 CRLF blob 与 .gitattributes 冲突导致的幽灵脏文件，已在 cd8995e 一次性 renormalize。
- 遗留提醒（记入 TASK-016）：ruff 目前 exclude 整个 `scripts/`，新增 validate 脚本时须收窄。

## 结论

**M0 通过**（含一项云端 CI 待确认的条件项）。打 tag `v2.0-m0`；TASK-010（依赖 003）与 TASK-020（依赖 004）置 `ready`。
