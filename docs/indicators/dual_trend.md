# 双线趋势呼吸选股 V2.1（白线/黄线 + 成交量呼吸度）

- 来源：`Obsidian/股票/指标/双线指标.md`（公式）+ `z哥课堂笔记/2025-10-04 双线战法.md`（用法）
- 实现：`quant/indicators/dual_trend.py`（TASK-021）；v1 参照 `quant/indicators/{dual_trend,volume_breath}.py`

## 公式（逐字）

```
{ === 双线趋势呼吸选股 V2.1 [严格版] === }

{ --- 参数设置 --- }
N1:= 10;      {白线(短期趋势线)周期}
M1:= 14; M2:= 28; M3:= 57; M4:= 114; {黄线(多空线)周期}
N_VOL:= 30;   {计算成交量"呼吸度"的回溯周期}
VOL_RATIO:= 3.5; {成交量高低差倍率}
J_LOW := 13;   {J值超卖触发线}

{1. 双趋势线}
知行短期趋势线 := EMA(EMA(C, N1), N1);
知行多空线 := (MA(CLOSE, M1) + MA(CLOSE, M2) + MA(CLOSE, M3) + MA(CLOSE, M4)) / 4;

{2. KDJ指标}
RSV := (CLOSE - LLV(LOW, 9)) / (HHV(HIGH, 9) - LLV(LOW, 9)) * 100;
K := SMA(RSV, 3, 1);
D := SMA(K, 3, 1);
J := 3 * K - 2 * D;

{3. 成交量呼吸度计算}
VOL_N := VOL;
VH1 := HHV(VOL_N, N_VOL);
VH2 := HHV(IF(VOL_N < VH1, VOL_N, 0), N_VOL);
VH3 := HHV(IF(VOL_N < VH2, VOL_N, 0), N_VOL);
AVGHIGH := (VH1 + VH2 + VH3) / 3;

VL1 := LLV(VOL_N, N_VOL);
VL2 := LLV(IF(VOL_N > VL1, VOL_N, 99999999), N_VOL);
VL3 := LLV(IF(VOL_N > VL2, VOL_N, 99999999), N_VOL);
AVGLOW := (VL1 + VL2 + VL3) / 3;

{ --- 选股条件 --- }
COND_TREND := 知行短期趋势线 > 知行多空线;                {A: 趋势确立}
COND_ACTIVITY := AVGHIGH > VOL_RATIO * AVGLOW;            {B: 呼吸活性}
COND_ENTRY_J := J < J_LOW;                                {C: 回调低点信号}
COND_PRICE_ZONE := C < 知行短期趋势线 AND C > 知行多空线;  {D: 价格进入理想支撑区}
剔除创业板 := NOT(INBLOCK('创业板'));
剔除科创 := NOT(INBLOCK('科创板'));
剔除北证 := NOT(INBLOCK('北证A股'));
XG: COND_TREND AND COND_ACTIVITY AND COND_ENTRY_J AND COND_PRICE_ZONE
    AND 剔除创业板 AND 剔除科创 AND 剔除北证;
```

## 输出列约定

`white`（知行短期趋势线）、`yellow`（知行多空线）、`j`、`avghigh, avglow, breath_active`（条件B）、
`sig_dual_trend_entry`（XG，不含板块剔除——板块过滤属 universe 层）、
`sig_golden_cross` / `sig_dead_cross`（white 上/下穿 yellow，用法层需要）。

## 用法规则（2025-10-04 笔记，供策略层与回测设计）

- **铁律：黄线之下不碰，白线之上敢做**——黄线之下无右侧交易价值，一切反弹当反抽。
- **金叉**（白上穿黄）= 趋势启动最高概率信号；两种玩法：金叉持有到死叉 / 等回调 B1。警惕数日内跌回的假金叉。
- **死叉** = 趋势结束，无条件离场。
- **黄金坑**：要死叉未死叉 + N 型低点未破 + 缩量 → 高胜率低吸（限大市值）。
- **N 型区间高容错买入区**：上升 N 型中价格落在白黄之间即可分批买（"模糊的正确"）。
- **主升浪前奏**：放量金叉后缩量回踩黄线 = 拉升前最后震仓（缩量回踩=震仓，放量回踩=破位）。
- **六步循环**：B1试错 → 拿住等待 → 区间埋满 → +10% 放飞 1/3~1/2 → 跌破白线减仓/止损 → 未出货再买回。禁止金字塔式亏损加仓。
- 适用性：A股/美股大盘股与 ETF 可用；港股不适用；期货需 5 分钟周期。

## 移植要点

1. **top-3/bottom-3 成交量的 HHV(IF(...)) 技巧**必须逐字复刻（先排除第一高再取次高……），不要"聪明地"改成 `sorted()[−3:]`——两者在窗口内有重复值时行为不同；v1 `volume_breath.py` 用的是 sorted 版，**以通达信原式为准**，差异用黄金值测试记录。
2. `99999999` 哨兵值保留（VOL 单位是股时也远大于实际值即可，若 fixture 出现超过哨兵的成交量需改为 `+inf` 并在测试中注明）。
3. 双重 EMA 与四均线直译；warmup 最长 114 根，前段输出 NaN。

## Pine 导出

全部可移植（volume/close 均有）；INBLOCK 降级为注释。
