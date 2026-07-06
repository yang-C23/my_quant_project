# 活跃市值 0AMV（指数级择时指标）

- 来源：`Obsidian/股票/指标/活跃市值.md`（公式，重建自指南针 0AMV，参考"百度文库——0amv指数源代码[教学]，2009年5月"）
  + `z哥课堂笔记/2025-07-02 则时-活跃市值.md`（用法）
- 实现：`quant/indicators/amv.py`（TASK-023）
- **适用范围：仅主要指数**（上证指数 sh999999 / 深成指等）副图使用，个股用法情形不明。

## 公式（逐字，去除加粗标记）

```
{ == 新建副图指标，仅在主要指数品种下方调用，其他用法情形不明 == }
OAMVN:=10; OAMVK:=2.13; {拟合系数，定期更新}
OAMVV1:=SMA(AMOUNT,OAMVN,1)/1000000;
OAMVV3:=MA(REF(CLOSE,1),5);
OAMVO:=OAMVV1*OPEN/OAMVV3*0.1*OAMVK;
OAMVH:=OAMVV1*HIGH/OAMVV3*0.1*OAMVK;
OAMVL:=OAMVV1*LOW/OAMVV3*0.1*OAMVK;
OAMVC:=OAMVV1*CLOSE/OAMVV3*0.1*OAMVK;
OAMV开盘:OAMVO,NODRAW;OAMV最高:OAMVH,NODRAW;
OAMV最低:OAMVL,NODRAW;OAMV收盘:OAMVC,NODRAW;
OAMV昨收:=REF(OAMVC,1);
OAMV涨幅:(OAMVC-OAMV昨收)/OAMV昨收*100,NODRAW;
OAMV生命线:EMA(OAMVC,12),COLORCYAN,LINETHICK1;
STICKLINE(OAMVC>=OAMVO,OAMVC,OAMVO,3,0),COLORRED;   {…蜡烛绘图段（红/绿），量化不需要…}
OAMVH60:=HHV(OAMVH,60);OAMVL60:=LLV(OAMVL,60);
OAMVR60:=OAMVH60-OAMVL60;
OAMV标记位:=OAMVL-OAMVR60*0.025;
DRAWTEXT(CURRBARSCOUNT<=180,OAMV标记位,VAR2STR(OAMV涨幅,2)),COLORGRAY;
```

> 拟合系数备注（原文）：`OAMVK:=1;（拟合系数，定期更新） 当前建议数值：2.13；如需用于较长时间的回测，建议换成：2.07。`

## 语义

用 `SMA(AMOUNT,10,1)`（成交额平滑，百万元）乘以 当日价 / 前5日昨收均值 的比例，再乘系数 K，合成一根"活跃市值"伪 K 线。**可交易信号 = 该序列的日涨幅 `OAMV涨幅`**。红=钱变筹码（做多），绿=筹码变钱（离场）；作者强调**裸看**（不叠加均线/MACD），"没有横盘这回事"。

## 择时规则（2025-07-02 笔记，量化实现目标）

| 信号 | 条件 | 动作 |
|---|---|---|
| **波段发令枪（买）** | 当日涨幅 ≥ **+4%**，或**两日累计 ≥ +4%** | 开新波段；"触发信号后，只要活跃市值没跌破 −2.3%，就拿着" |
| **止损令（卖）** | 单日涨幅 ≤ **−2.3%** | 波段结束，无论盈亏减仓/空仓（案例：某年9月4日 −2.52% → 指数随后 ~10% 下跌） |

结构：永远走 **N 型**（红→绿→红循环）。市况分层：衰退期=只做短波段（10–20% 仓，赚 10–15% 就撤）；趋势反转期=重仓拿住（80–100%）；结构牛=跟红柱轮动板块。仓位默认：有 4% 信号+趋势向上 → 80–100%；−2.3% 后 → 0–20%；无信号 → ~50%。与"少妇战法"组合：+4% → 买 B1；−2.3% → 卖 S1。

## 输出与接口

```python
def amv(df: pd.DataFrame, *, n: int = 10, k: float = 2.13) -> pd.DataFrame
    # 输入：指数日线（须含 amount 元）；输出列：amv_open/high/low/close, amv_pct(百分点), amv_life(EMA12)
def amv_timing_signal(amv_df: pd.DataFrame, *, buy_th: float = 4.0,
                      sell_th: float = -2.3) -> pd.DataFrame
    # 输出列：sig_amv_buy(单日或两日累计≥buy_th), sig_amv_sell(≤sell_th),
    #        regime(int: 1=波段持有中, 0=空仓/观望)——由买卖信号状态机推出
```

## 移植要点

1. 输入是**指数**的 amount；staging 的指数行情随个股一起导入（TDX vipdoc 含 sh999999 等），TASK-011 的 securities 表 sec_type=index。
2. 两日累计口径：`pct_t + pct_{t−1} ≥ 4`（简单加和，与口播一致；不复利）。
3. K 系数必须是参数并在 config 可覆盖（回测长区间用 2.07）；**后续研究任务**：用市场数据重新拟合 K 并检验 +4/−2.3 阈值的稳健性/泛化性（用户明确要求"调整使其更精准有效和有泛化性"——立研究卡进 M6，不在移植期改原式）。
4. 绘图段（STICKLINE/DRAWTEXT）不实现。

## Pine 导出

Pine 无 `AMOUNT` → 用 `hlc3 * volume` 近似成交额（指数 volume 口径差异大，**仅形态参考**，头注释必须声明）。
