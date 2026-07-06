# 知行 MACD

- 来源：`Obsidian/股票/指标/通达信 - 知行MACD指标.md`
- 实现：`quant/indicators/zhixing_macd.py`（TASK-024）

## 公式（逐字）

```
DIFF:EMA(CLOSE,12) - EMA(CLOSE,26); DEA:EMA(DIFF,9); MACD:2*(DIFF-DEA),COLORSTICK;
STICKLINE(CROSS(DIFF,0) AND MACD>0,0,MACD,3,0),COLOR0000FF;
STICKLINE(CROSS(DIFF,0) AND MACD<0,0,MACD,3,0),COLOR0000FF;
STICKLINE(CROSS(0,DIFF) AND MACD>0,0,MACD,3,0),COLORLIGREEN;
STICKLINE(CROSS(0,DIFF) AND MACD<0,0,MACD,3,0),COLORLIGREEN;
```

## 语义

标准 MACD(12,26,9)，柱 = 2×(DIFF−DEA)；绘图部分把 **DIFF 上穿/下穿 0 轴当根的柱子高亮**（红/绿）——即零轴金叉/死叉标记。

## 移植要点

- 输出列：`diff, dea, macd, sig_diff_cross_up_zero, sig_diff_cross_dn_zero`（STICKLINE 颜色仅是绘图，量化上等价于这两个 CROSS 布尔列）。
- TDX `EMA` 递归语义见 README（≠ pandas `ewm(span)` 的 adjust=True 默认，需 `adjust=False` 且首值=首个数据点）。

## Pine 导出

直译（`ta.ema`, `ta.cross`）。
