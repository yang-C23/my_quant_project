# indicators/ — 指标参考总览与通达信原语语义

本目录每个文件对应一个待移植指标：**原版通达信公式逐字保留**（仅去除 Obsidian 的 `**` 加粗标记）+ 参数表 + Python 移植要点 + 测试向量要求 + Pine 导出注意。
来源：用户 Obsidian 笔记（z哥体系），路径记录在各文件头部。

## 指标清单与实现位置

| 文档 | 指标 | 实现模块 | 任务卡 |
|---|---|---|---|
| kdj.md | KDJ（TDX SMA 变体） | `quant/indicators/kdj.py` | TASK-021 |
| dual_trend.md | 双线趋势呼吸 V2.1（白线/黄线/呼吸度） | `quant/indicators/dual_trend.py` | TASK-021 |
| b1.md | B1 选股三版本 + B1/B2/B3 理论 | `quant/indicators/b1.py` | TASK-022 |
| amv_0amv.md | 活跃市值 0AMV（指数择时） | `quant/indicators/amv.py` | TASK-023 |
| volume_patterns.md | 倍量柱 / 单针下20（代理版） | `quant/indicators/volume_patterns.py` | TASK-024 |
| zhixing_macd.md | 知行 MACD | `quant/indicators/zhixing_macd.py` | TASK-024 |
| brick.md | 砖形振荡器 + 三个选股变体 | `quant/indicators/brick_osc.py` | TASK-024 |

## 通达信原语语义（`quant.tdx.functions` 必须 1:1 实现，TASK-020）

约定：序列 X，周期 N；t 为当前 bar；warmup 不足时输出 NaN（递归类除外，见各条）。

| 函数 | 语义 |
|---|---|
| `REF(X,N)` | N 根前的 X 值（`X.shift(N)`） |
| `MA(X,N)` | 最近 N 根简单均值 |
| `EMA(X,N)` | 递归：`Y = (2·X + (N−1)·Y′) / (N+1)`，首值 Y₀=X₀ |
| `SMA(X,N,M)` | **TDX 特有递归**：`Y = (M·X + (N−M)·Y′) / N`，首值 Y₀=X₀（Wilder 式；等价 `ewm(alpha=M/N, adjust=False)`，NaN 需跳过并保持状态）。**TASK-020 实证**：v1 bt 的 TDXSMA 时钟跟随输入线，种子同为首个有效值 → KDJ 黄金对比可全程精确（rtol 1e-8）；但 bt 的经典 `EMA` 用前 N 均值播种，与 TDX `EMA`(Y₀=X₀) 前段不同、按 ((N−1)/(N+1))^k 收敛——dual_trend 白线对比须避开前段（见 TASK-021 备注） |
| `HHV(X,N)` / `LLV(X,N)` | 最近 N 根最高/最低（含当根）；N=0 表示从头累计 |
| `SUM(X,N)` | 最近 N 根滚动和 |
| `COUNT(cond,N)` | 最近 N 根内条件成立次数 |
| `CROSS(A,B)` | 上穿：`A_t > B_t AND A_{t−1} ≤ B_{t−1}` |
| `BARSLAST(cond)` | 上次条件成立距今根数 |
| `EVERY(cond,N)` / `EXIST(cond,N)` | 最近 N 根全部/存在成立 |
| `IF(cond,A,B)` | 条件选择（`np.where`） |
| `MAX/MIN/ABS/NOT` | 逐点运算 |

### 数据字段映射（TDX → v2 staging/qlib）

| TDX | 含义 | v2 来源 |
|---|---|---|
| `C/O/H/L` | 收/开/高/低 | 复权价（研究）或原始价（涨跌停判断），由调用方指明 |
| `VOL` | 成交量（TDX 公式内单位=手；本仓库 staging 为股。本目录公式全部只用 VOL 的**比值/滚动比较**，单位可约去——移植时用股即可，新公式若用 VOL 绝对值必须先换算） | `volume` |
| `AMOUNT` | 成交额（元） | `amount` |
| `CAPITAL` | 流通股本（手）。`C*CAPITAL*100/1e8` = 流通市值（亿元） | `float_shares`：`close*float_shares/1e8` |
| `INBLOCK('创业板')` 等 | 板块归属 | `quant.data.universe` 过滤（`exclude_boards={"gem","star","bse"}`），**不在指标层实现** |

### 通用移植规则

1. 指标函数签名统一：`def <name>(df: pd.DataFrame, *, <params with defaults>) -> pd.DataFrame`，输入含 open/high/low/close/volume/amount（单符号、按日期升序），输出与输入同 index 的指标列；布尔信号列前缀 `sig_`。
2. **无未来函数**：只准用 shift ≥ 0 方向的数据；warmup 输出 NaN。
3. 除零保护：`HHV−LLV == 0` 时 RSV 类表达式输出 NaN 并由后续递归自然衔接（与 v1 backtrader 行为通过黄金值测试锁定）。
4. 黄金值测试：每个指标至少 2 只真实 fixture 股票、≥500 bar 与 v1/手工参照对齐（`rtol` 见任务卡）。
5. 多符号批量：由 signals 层 `groupby(symbol)` 调度，指标函数本身保持单符号纯函数。
