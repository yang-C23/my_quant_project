# TASK-073: 快照冻结 manifest + PG 归档 dump（033 前置）

- Milestone: M3（工程卡，与 032/071 返工并行；白名单零交集）　|　State: ready
- Branch: `task/TASK-073-snapshot-freeze`　|　Depends: —

## Context
ADR-0005 §8 收紧 PG 退役门槛：TASK-033 删码前必须存在**可核验的不可变数据链快照**
（staging / qlib bin / 黄金 CSV / PG dump / 环境）+ 规划者完成恢复演练。本卡交付
manifest 工具、完成 pg_dump 归档与首次 freeze，并写恢复演练 runbook。演练本身由
规划者执行（integration，不在本卡）。

## Goal
一条命令对研究数据链生成 SHA256 manifest，一条命令核验漂移（任何缺失/新增/内容不符
→ 非零退出并列明细）；PG dump 归档存在、可读、已入 manifest。

## Scope
1. 新建 `scripts/snapshot_manifest.py`（路径全部经 `quant.config.get_settings()`，
   scripts/ 虽豁免硬编码检查，本卡仍按 src 标准写）。CLI：
   - `freeze --out <path>`：生成 manifest JSON，覆盖类别：
     - `staging`：`settings.staging_dir` 递归全部文件（SHA256 + size）；
     - `qlib_cn_daily`：`settings.qlib_cn_daily_uri` 递归全部文件（同上）；
     - `golden`：repo `docs/parity/*.csv`（同上）；
     - `pg_dump`：`settings.archive_dir / "pg_quant_*.dump"`（同上）;
     - `env`：python 版本、`pip freeze` 文本的 SHA256、repo HEAD commit、DATA_ROOT 路径；
     - `tdx_source`：`settings.tdx_home` 仅文件清单 + size + mtime（9P 慢 IO），
       `--hash-tdx` 开关才做全量 hash（默认关）。
     manifest 顶层记录各类别文件数与总字节；**任一必需类别匹配 0 文件 → freeze 失败退出**
     （防 glob 静默空转）。
   - `verify --manifest <path>`：逐文件重算对照，输出 缺失/新增/hash 不符 三类明细；
     全部一致 exit 0，否则 exit 1。
2. **PG 归档**（本卡仅有的两处 DATA_ROOT 写入授权之一，均在 `archive/` 下；PG 只读）：
   ```bash
   docker start pg_quant
   # 连接参数照 scripts/validate_vs_pg.py 现行配置；容器内 pg_dump -Fc、schema tdx 全量
   docker exec pg_quant pg_dump ... > $DATA_ROOT/archive/pg_quant_$(date +%Y%m%d).dump
   pg_restore --list <dump>   # 验证可读；dump 大小 + 表数写 STATUS 备注
   # 容器保持运行（032 审查复跑仍需 PG），不 stop
   ```
3. **首次 freeze**（DATA_ROOT 写入授权之二）：
   `python scripts/snapshot_manifest.py freeze --out $DATA_ROOT/archive/manifest_$(date +%Y%m%d).json`
   （含 dump），随后 `verify` 通过。
4. `docs/data_platform.md` 新增"快照冻结与恢复演练"小节：manifest 用法 + 恢复演练 runbook
   （无 pg_quant 容器的环境：从 dump 起新 postgres 容器恢复 → 跑 `scripts/validate_vs_pg.py`、
   `scripts/m2_gate_parity.py`、032 黄金再生成命令核对——由规划者执行）。

## Non-goals
不删任何 PG 代码（TASK-033）；不停容器；不执行恢复演练（规划者）；默认不全量 hash TDX 源；
不做增量/差分 manifest。

## Files to touch
- `scripts/snapshot_manifest.py`
- `tests/unit/test_snapshot_manifest.py`
- `docs/data_platform.md`

## Acceptance criteria
1. `pytest -q tests/unit/test_snapshot_manifest.py` 全绿（含 AC4 篡改红灯用例）。
2. 真实数据链 freeze 成功：打印各类别文件数 + 总字节且**全部类别 >0**；紧接
   `verify --manifest <同文件>` exit 0。命令与耗时写 STATUS 备注。
3. `ls -lh $DATA_ROOT/archive/pg_quant_*.dump` 存在；`pg_restore --list` 输出 tdx schema
   表清单（头部贴 STATUS 备注）。
4. 篡改敏感性（tmp_path 构造小树，不碰真实数据）：freeze 后 (a) 改 1 字节 (b) 删 1 文件
   (c) 增 1 文件 → verify 均 exit 1 且明细指名文件；用例同时断言 manifest JSON 中每个文件
   含 `sha256` 字段（verify 走内容 hash，非 mtime/文件名）。
5. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` +
   `python scripts/check_no_hardcoded_paths.py` 全绿。

## 验收如何被作弊/退化满足？
1. **verify 恒 0 / 只比文件名**：AC4 三种篡改必须红，且改 1 字节（size 不变）必须被抓——
   钉死"内容 hash 参与比对"。
2. **glob 空匹配静默绿**：freeze 对空类别硬失败 + AC2 要求打印各类别计数且 >0，审查者
   对照真实目录规模核对量级（staging 万级文件、qlib 万级文件）。
3. **只记 mtime/size 不记 hash**：AC4 断言 manifest 结构含 sha256 且 (a) 用例改字节不改
   size 仍必须红。
4. **env 信息写死假值**：审查者当场对照 `git rev-parse HEAD` 与 `python -V`。
5. **TDX 清单整体跳过**：tdx_source 属必需类别，计数为 0 即 freeze 失败（AC2 一并核对）。

## 数值验证类别与变形测试（数值/研究卡必填，其余写 n/a）
Class A（逐字节：SHA256 内容一致性即本卡的全部语义）。变形测试即 AC4 三种篡改。

## Test plan
tmp_path 小树 fixture（新建，不用真实 DATA_ROOT）：freeze 结构断言、verify 三种篡改红灯、
空类别失败、TDX listing 模式（有清单无 hash）。AC2/AC3 为真实数据链本地核查（integration 性质）。

## Notes / risks
- staging + qlib 数 GB，SHA256 分钟级属正常；TDX 全量 hash 小时级（9P），故默认 listing-only。
- dump 与 manifest 属 DATA_ROOT，不进 git；只有路径、大小、校验信息进 STATUS/review。
- 若 dump 过程发现 PG 损坏/数据不全 → 停止报告规划者（不许带伤归档）。
- freeze 之后到 033 之间任何人不得写 staging/qlib/parity/archive（PG 自 M1 已冻结）；
  033 的 AC1 会 verify 同一 manifest，漂移即红。
