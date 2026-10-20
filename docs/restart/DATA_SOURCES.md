# 来源、授权、费用与覆盖审查

审查日：2026-10-20。可执行登记在`configs/data_sources.yaml`；每次真实采集结果在
`DATA_ROOT/source_reports/`，原始响应、解析器版本、schema和哈希在`DATA_ROOT/lake/`。
“已取得”只证明该次可获取，不保证永久稳定、历史完全正确或允许永久留存。

## 已完成实测

| 来源 | 本次证据 | 用途与边界 |
|---|---|---|
| 用户通达信 | 全历史ZIP与更新后的vipdoc，逐证券合并 | 迁移对照；无历史发布时间和分红支付日证据 |
| BaoStock | 5条指数历史、一只股票历史，以及2026-10-19共1,708只ETF当日记录 | 股票历史接口和ETF专用日接口分开；个别指数覆盖/价格/金额仍有差异 |
| 中证指数 | 8个指数各20个近期估值观测 | PE总股本与计算用股本、两种股息率分存；不是10年PE历史 |
| Cboe | VIX共9,297行，1990-01-02至2026-10-19 | 现货波动率；早期有回溯，不是可直接投资价格 |
| FRED | SP500约10年、NASDAQ100自1986，另有10年利率、3月贴现率、人民币汇率 | 价格指数不含分红；利率原始单位为百分数；历史修订与发布时间另审 |
| 中金所 | 2026年9月完整21个交易日，14,690条期货/期权合约记录 | 合约级、不拼接连续合约；不推断真实净Gamma |
| CFTC | 2025年TFF期货持仓3,686条 | 经济日期与实际公布日期分开，持仓不等于资金流或爆仓 |

当日ETF逐只核查：1,700只与TDX的OHLC、成交量、成交额在明示容差内一致，8只本地缺失。
价格绝对容差ETF为0.00051、指数/股票为0.0051，成交活动同时考虑TDX有限精度。
历史样本仍有需要裁定的差异，例如中证500在2014-08-07收盘为TDX 4286.09、BaoStock 4341.94；
创业板802天的成交统计明显不同。不得通过平均两个来源或修改容差来隐藏差异。
本次重采一次沪深300分页出现“用户未登录”，原成功版本被保留，失败亦记录；公开源稳定性仍需持续观察。
逐项原值在`source_reports/crosscheck_differences.parquet`，缺失日期在`crosscheck_coverage_gaps.parquet`。

上述行数是本次实测记录，不是服务商承诺的最大覆盖。中证数据来自
[官方估值文件](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/000300indicator.xls)，
VIX来自[Cboe官方历史接口](https://www.cboe.com/tradable_products/vix/vix_historical_data/)，
CFTC来自[官方归档](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm)。

FRED明确限制SP500为约10年日线，且不含股息，并注明再分发限制；不能包装成15年总回报数据。
[FRED序列说明](https://fred.stlouisfed.org/series/SP500)

BaoStock 0.9.4的`get_data()`仍调用旧Pandas接口，适配器改为`next/get_row_data`。
`query_history_k_data_plus`不作为ETF通用历史接口；专用`query_daily_history_k_ETF`已实测。
ETF旧接口曾挂起，采集需有超时限制。[官方项目文档](https://github.com/zxygithub/baostock/blob/master/docs/pythonAPI.md)

## 付费与长期留存：不能沿用旧推荐

| 候选 | 已核实条件 | 当前决定 |
|---|---|---|
| Tiingo | 当前个人标价30美元/月或300美元/年；2026-10-06条款限制持久保存 | 不作为默认永久档案源；有token也不能绕过留存协议门 |
| Norgate | 美国Gold 360美元/年；Platinum 630美元/年含退市和历史成分 | 数据质量候选，但订阅到期留存限制、Windows依赖需解决 |
| Tushare | 积分和单独接口权限，部分指数基本面为社区计算 | 候选补历史；先验证方法、覆盖、许可与实际报价，不自动付费 |
| CME/DataShop | 合约历史/历史期权链按产品授权收费 | 数据不足再询价，保留长期留存与内部研究的书面条件 |
| Nasdaq/指数商/基金发行人 | 指数、成分、基金公司行动的一手发布者 | 优先核验方法和分红；当前公开页面不等于开放完整可留存历史库 |

Tiingo免费/试用计划不允许持久保存数据或派生产物；普通付费结束后须删除数据，
部分交叉核验及可还原派生数据也受限制。永久留存需另行书面约定，不能靠“换成Parquet”规避。
[条款§1.6](https://app.tiingo.com/tos/)、[当前价格](https://www.tiingo.com/about/pricing)

Norgate官方也要求订阅结束且不即刻续订时删除导出数据及备份。
[订阅FAQ](https://norgatedata.com/faq.php)、[覆盖与价格](https://norgatedata.com/stockmarketpackages.php)

没有采购、创建收费账户或对外联系供应商。后续采购需明确能补哪些数据缺口；
价格以实际合同为准，付款本身不代表正确、可复现或允许永久保存。

## 指数历史与红利低波

中证factsheet确认：沪深300发布于2005-04-08、中证500于2007-01-15、中证1000于2014-10-17，
科创50页面标注2020-07-23、科创100为2023-08-07。
这些日期已写入研究配置，早于发布日期的记录单独标为回溯。
[沪深300](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300factsheet.pdf)、
[中证500](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000905factsheet.pdf)、
[中证1000](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000852factsheet.pdf)、
[科创50](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000688factsheet.pdf)、
[科创100](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000698factsheet.pdf)

H30269发布于2013-12-19，当前50个样本、股息率加权、年度调样。2026-09-30事实表的金融权重55.8%，
仅说明当前集中度，不能套到历史成分。930955是另一指数，不能与其混用。
[H30269事实表](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H30269factsheet.pdf)

SPHD成立于2012-10-18，其发行人提供除息日、登记日与支付日信息，需补齐全历史后才可做真实股息账本。
[Invesco产品披露](https://www.invesco.com/us/en/financial-products/etfs/invesco-sp-500-high-dividend-low-volatility-etf.html)

## 雪球温度审查

[雪球基金估值中心](https://danjuanfunds.com/djmodule/value-center)提供PE/PB百分位等展示字段，
但本次取得的页面未给出可验证的窗口、亏损处理、历史成分、修订和发布时间证据。
其百分位不直接进入策略输入；未把页面值当作公式标准。后续只有可追溯定义和历史证据的部分可准入。

## 下一批必需资料

1. 标普500、纳斯达克100及A股各指数至少“预热期＋评估期”的估值、口径与历史发布时间。
2. ETF原价、完整拆分及分红公告/除息/支付日、历史上市退市名录和交易规则；QDII历史NAV与折溢价。
3. 历史成分与权重、方法变更，红利低波行业及分红削减归因。
4. 长期留存与内部计算授权；所有免费源的许可边界仍要逐源确认。
5. 完整期货期限资料、资金/杠杆发布日历和期权链。Gamma方向假设不能由成交量或OI自动推断。

来源中断、字段变更、过期、负估值和未认证修订均进入异常记录并暂停依赖信号。
当前没有任何单一公开平台被证明可完整替代以上所有数据类别。
