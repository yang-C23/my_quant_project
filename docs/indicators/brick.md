# 砖形振荡器（超短线 绿转强红）

- 来源：`z哥课堂笔记/2026-02-20 砖形图 超短线 小资金翻倍.md`
- 实现：`quant/indicators/brick_osc.py`（TASK-024）；v1 参照 `quant/indicators/brick.py`（BrickIndicator，未接策略）
- 策略定位：2–4 日超短反转爆发（"绿转强红"、"空头被多头干爆"），只做黄线之上。

## 核心指标（逐字）

```
VAR1A:=(HHV(HIGH,4)-CLOSE)/(HHV(HIGH,4)-LLV(LOW,4))*100-90;
VAR2A:=SMA(VAR1A,4,1)+100;
VAR3A:=(CLOSE-LLV(LOW,4))/(HHV(HIGH,4)-LLV(LOW,4))*100;
VAR4A:=SMA(VAR3A,6,1);
VAR5A:=SMA(VAR4A,6,1)+100;
VAR6A:=VAR5A-VAR2A;
砖型图:=IF(VAR6A>4,VAR6A-4,0),COLORRED;
{红砖 = 砖型图较昨日上升；绿砖 = 下降}
AA:=(REF(砖型图,1)<砖型图); BB:=REF(砖型图,1)>砖型图;
CC:=REF(AA,1)=0 &&(AA=1); XG:=CC>0;
```

## 选股变体一（严格版，含 BURST，逐字）

```
A1:=(HHV(H,4)-C)/(HHV(H,4)-LLV(L,4))*100-90;
A2:=SMA(A1,4,1)+100;
A3:=(C-LLV(L,4))/(HHV(H,4)-LLV(L,4))*100;
A4:=SMA(A3,6,1);
A5:=SMA(A4,6,1)+100;
A6:=A5-A2;
ZXT:=IF(A6>4,A6-4,0);
D:=ZXT-REF(ZXT,1);
REDLEN:=D;  GRNLEN:=ABS(REF(D,1));
TURN:=(REF(D,1)<=0) AND (D>0);            {绿转红}
STRONG:=REDLEN>=0.67*GRNLEN;              {红砖≥前绿砖2/3}
SMALLUP:=(C>REF(C,1)) AND ((C/REF(C,1)-1)<=0.03);   {K线涨幅≤3%}
BURST:=(REDLEN>=0.80*HHV(ABS(D),6)) AND (ZXT>0);
N1:=10; M1:=14; M2:=28; M3:=57; M4:=114;
ZX_SHORT:=EMA(EMA(C,N1),N1);
ZX_BULLBEAR:=(MA(C,M1)+MA(C,M2)+MA(C,M3)+MA(C,M4))/4;
COND_TREND:=ZX_SHORT>ZX_BULLBEAR;
XG:TURN AND STRONG AND SMALLUP AND BURST AND COND_TREND;
```

## 变体二（放宽 BURST，加 KDJ 超跌，逐字要点）

去掉 BURST；`SMALLUP` 同上；加 `OVERSOLD:=REF(D,1)<=0 AND REF(J,1)<13;`（或宽松版：变红前 3 日内任一日 J<13）；加板块剔除。`XG:TURN AND STRONG AND SMALLUP AND COND_TREND AND OVERSOLD AND 剔除创业板 AND 剔除科创 AND 剔除北证;`

## 变体三（红绿柱都要够长，逐字要点）

`GOK:=GL>=0.35*HHV(ABS(D1),6); ROK:=RL>=0.35*HHV(ABS(D1),6);`（红绿柱都不能太短）；`SUP` 涨幅上限放宽到 ≤4%；OSD 用 3 日内 J<13 宽松版。`XG:TRN AND STG AND GOK AND ROK AND SUP AND TRE AND OSD AND CYB AND KCB AND BJA;`

## 执行规则（策略层）

1. 只做黄线之上（白线在黄线之上）；2. 绿转强红（红 ≥ 前绿 2/3 是底线，最好大红盖过去）；3. 长上影再定夺；4. 当日尾盘买或次日早盘不追高买；5. 每票一仓（10万分两半）；6. 止损=买入 K 线最低价，或两日不拉起就走；7. 脱离成本 5% 后最多持 4–6 天；8. 可与 B2 共振（红柱一般出现在 B1 后面）；9. 大阳线配大红柱；10. 20cm 涨停板（创业板）未回测过，不做；不玩跳空、尽量不做横盘；"红柱小、砖大，才有爆发力"（K 线涨幅大说明已爆发完）。

## 输出与移植要点

- 输出列：`zxt`（砖值）、`brick_delta`（D）、`sig_brick_turn`（TURN）、`sig_brick_strict`/`sig_brick_relaxed`/`sig_brick_len`（三变体 XG，不含板块剔除）。
- 三变体同骨架 → 单函数 + `BrickParams` 预设（同 B1 的做法）。
- 注意变体间变量重名（D 与 KDJ 的 D）——实现内命名分开；`&&` 与 `=` 是通达信写法，语义即 AND 与 ==。
- TODO（原笔记）：尝试"回调到白线后反弹的红砖"入场 —— 作为 M6 研究项。

## Pine 导出

全部可移植（纯 OHLC）；SMA 用自定义 tdx_sma。
