# KDJ（通达信 SMA 变体）

- 来源：z哥体系通用（B1/双线/砖形各公式内嵌同一定义）；v1 参照实现 `quant/indicators/kdj_tdx.py`
- 实现：`quant/indicators/kdj.py`（TASK-021）

## 公式（逐字，出自 B1 / 双线公式内嵌段）

```
RSV:=(C-LLV(L,9))/(HHV(H,9)-LLV(L,9))*100;
K:=SMA(RSV,3,1); D:=SMA(K,3,1);
J:=3*K-2*D;
```

## 参数与阈值

| 参数 | 默认 | 说明 |
|---|---|---|
| n, k_period(m1), d_period(m2) | 9, 3, 3 | 标准参数 |
| 超卖阈值 | **J < 13**（B1 用 `J<=13`） | 全体系统一的"阶段性低点"判据；候选太少时放宽 **26.5** |

## 用法要点（B1/B2/B3 理论笔记）

- B1 的唯一判断标准就是 J 打到 13 以下，任何周期通用（日/周/月/季）。
- **勾大负值**：月线/季线级 J 出现大负值（案例 −0.62 / −3.03 / −15.89）= 极端恐慌，中长线吸筹买点。
- 与双线体系组合时作为回调入场触发（见 dual_trend.md 条件 C）。

## 移植要点

- `SMA(X,N,1)` 用 TDX 递归语义（README 表），**不是** pandas `rolling().mean()`。
- 除零（TASK-020 实证修订）：`HHV(H,9)==LLV(L,9)`（连续一字板）时 **RSV=0**——通达信 `/0→0` 惯例，v1 亦为 `IF(denom==0, 0, …)`，黄金值锁定此口径；实现用 `IIF(denom==0, 0.0, …)`（warmup 区 denom=NaN → 自然输出 NaN）。
- Warmup：前 9 根 RSV 为 NaN；K/D 从第一个非 NaN RSV 起递归。

## Pine 导出（TASK-043）

TDX SMA 需自定义：`tdx_sma(x, n, m) => s = 0.0, s := (m*x + (n-m)*nz(s[1], x))/n`；其余直译。
