# TASK-073 Review（第一轮）— 快照冻结 manifest + PG 归档 dump

- 分支：`task/TASK-073-snapshot-freeze`（dcbddc6）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-11
- 结论：**changes_requested**（阻塞根因=环境而非代码，另有一处 verify 性能缺陷；协议执行正确——对空 tdx_source 硬失败后停下报告，未绕路改用 mirror，加分项）

## 阻塞根因裁定（审查者独立诊断）

`freeze` 报 `required snapshot categories are empty: tdx_source` 的根因：
**worktree 没有 `.env`**（untracked 文件不随 `git worktree add` 复制），`Settings.tdx_home`
落到默认 `/tdx`（空）。主仓 `.env` 实为 `TDX_HOME=/mnt/d/new_tdx` 且该目录在挂载中
（审查者已核实有文件）。工具对空类别硬失败**正是卡面要求的行为**——代码没错，环境错了。

## 已验证合格的部分

| 项 | 结果 |
|---|---|
| 白名单 | ✅ check_whitelist OK（4 文件含 STATUS） |
| AC1/AC4 | ✅ 审查者亲跑 6 passed：同长度改 1 字节→hash_mismatch、删→missing、增→new、CLI exit 1 且指名文件、空类别硬失败、tdx listing 模式（sha256=None）——反作弊面全部钉死 |
| AC3 | ✅ `archive/pg_quant_20260710.dump` 286M，容器内 `pg_restore --list` 可读（TOC 48、PG 16.13、schema tdx 全部 8 表），容器保持 Up |
| 质量门 | ✅ 审查者亲跑：207 passed、ruff、format、whitelist 全绿（Codex 报"未执行"系保守，实测通过） |
| 代码结构 | ✅ 分块 SHA256、环境身份（pip freeze hash/HEAD/python/data_root）、JSON sort_keys、错误处理与退出码 |

## 返工项（原分支继续）

1. **环境修复 + 完成 AC2**：`cp /home/yang/projects/my_quant_project/.env <worktree>/.env`
   （.env 是运行时配置，不入 git，每个 worktree 需自带——此教训已记 STATUS 总备注），
   然后重跑 `freeze --out $DATA_ROOT/archive/manifest_<date>.json` + `verify`，把各类别
   文件数/总字节/耗时写 STATUS 备注（tdx_source 计数应为数千级）。
2. **verify 性能缺陷**：`_new_files` 每个类别调一次 `_category_files(settings, …)`，而后者
   对**全部类别**构建含 SHA256 的完整条目——一次 verify 把整条数据链重复 hash ~6 遍
   （1 遍 `_current_entries` + 5 类别各 1 遍全链）。"new" 检测只需要**路径集合**：改为
   一次性收集各类别当前路径（不 hash），或 `_category_files` 拆分路径收集与条目构建。
   加防回归用例：monkeypatch 计数 `sha256_file` 调用次数，verify 全程 ≤ 记录文件数。

## 备注（非返工项，记档）

- manifest 记录**绝对路径**：满足 033 同机完整性核验；跨机恢复演练不依赖 manifest verify
  （runbook 以黄金复跑为准），可接受。
- tdx listing 模式以 (size, mtime_ns) 对比：9P 挂载 mtime 跨重挂可能漂移，listing 类别
  属参考性质——033 verify 若仅 tdx_source 的 mtime 漂移，由规划者人工裁定而非自动红。
