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
| 中金所 | 2010年4月至2026年9月，198个月，917,914条合约日记录 | 固定宽度代码尾空格已修复；不拼接事后主力，不推断净Gamma |
| CFTC | 2006—2016合并档案及2017—2026逐年档案，共47,027条新增批次记录 | 2010年前TFF类别为回补；合并档案优先，排除重叠旧年文件 |
| FINRA | 1997年1月至2026年9月，357个月度记录 | 美元百万；次月发布日期仅保守情景，不能当逐条PIT证据 |
| Shiller | Yale旧文件1,833个月至2023年9月；维护中官网新文件1,869个月至2026年9月 | 新文件盈利/股息仅到2026年6月，缺失保持缺失；两个修订版本分别保存，延迟6/12个月仍不证明历史可得性 |
| Cboe补充 | VXN 4,303行、SKEW 9,251行，至2026-10-19；总Put/Call 3,253行，仅至2019-10-04 | Put/Call在2012年6月改变统计方式，分段预热；旧文件不是当前信号源 |
| 上交所融资融券 | 2010-03-31至2026-10-19共4,018日 | 每页实际最多2,000行，已补齐分页；融资+融券余额逐日对账，金额元/数量股 |

当日ETF逐只核查：1,700只与TDX的OHLC、成交量、成交额在明示容差内一致，8只本地缺失。
价格绝对容差ETF为0.00051、指数/股票为0.0051，成交活动同时考虑TDX有限精度。
历史样本仍有需要裁定的差异，例如中证500在2014-08-07收盘为TDX 4286.09、BaoStock 4341.94；
创业板802天的成交统计明显不同。不得通过平均两个来源或修改容差来隐藏差异。
本次重采一次沪深300分页出现“用户未登录”，原成功版本被保留，失败亦记录；
单证券重试已成功取得5,290条，回执在`source_reports/baostock_retry.json`。
一次重试成功不代表已通过长期稳定性验收。
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

512890的2021年份额拆分公告已保存为`official_split_sh512890_20211022`数据集，
原始PDF与解析记录版本为`437cd33ec8ad3f3bc0477e57`。法律生效日、登记日与恢复交易日分别保存，
随后补充的发行人证据完成了本次三只指定ETF账户所需的行动核验，详见下节；
其他缺失完整公司行动的ETF仍暂停账户回测。
[基金官方拆分公告](https://static.cninfo.com.cn/finalpage/2021-10-21/1211340704.PDF)

### 三只指定ETF的发行人闭合核验

声明和逐份源文件哈希在`configs/fund_actions/`，导入版本保存在湖内；不改写原始披露。

| 基金 | 核验结果 | 必须保留的例外 |
|---|---|---|
| 512890 | 2倍拆分，未发现现金分红；1,883行官方单位/累计净值闭合 | 2023-12-31接口累计净值错填单位净值，以2023年报82.86%累计增长核实；2021-10-22停牌旧价只作拆分后估值，不交易 |
| 515100 | 两次分红0.437、0.1053元/份；除息与支付日期分别核验，1,534行NAV闭合 | 2023年大额除息不当作恐慌；支付后才能用现金 |
| 510300 | 14次分红及上市前0.37094933折算；3,506行NAV闭合 | 早期NAV只报3位小数，2013年起4位；舍入容差随原始精度，不全历史统一放宽 |

三只基金合计6,897个TDX交易日均找到同日发行人NAV，没有证据支持统一修改其价格单位。
2015年510300存在较大折溢价，不能用NAV覆盖真实市场成交价格。
此次是指定产品比较，未凭今天存续产品重建历史成交额选基规则。
[华泰柏瑞512890](https://www.huatai-pb.com/products/zhishu/512890/index.html)、
[华泰柏瑞510300](https://www.huatai-pb.com/products/zhishu/510300/index.html)、
[景顺长城515100](https://www.igwfmc.com/main/jjcp/product/515100/detail.html)

补充源原始档案位于`source_probes/20261020T170250Z/`及`source_probes/pressure-*/`，
完整衍生品采集记录为`audits/archive-acquisition-20261020T172052896599Z/`。
旧失败采集、错误时间精度运行及其异常原因均保留，不混入成功结果。
上交所原接口：[融资汇总](https://www.sse.com.cn/market/othersdata/margin/detail/index.shtml)；
FINRA：[历史统计及方法变化](https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics)；
Shiller：[原始说明](https://www.econ.yale.edu/~shiller/data.htm)。

维护中来源为[作者数据站](https://shillerdata.com/)，作者归属由
[Yale Cowles论文脚注6](https://cowles.yale.edu/sites/default/files/2024-07/d2397.pdf)交叉确认。
新工作簿通过官网实际下载链接获取，保存页面、响应字节、SHA256及解析记录；
`shiller_monthly`新版本为`3a48524911896cd5518ff7eb`，旧版`a503673af60d10f6295d636b`保留。
重叠历史中3个盈利值和7个CAPE值发生变化，不能因为文件更新就宣称历史数值未经修订。
新版研究只重跑原先登记的52项估值代理，没有因表现增加或删除规则。

### 历史发布时间的反例

CFTC的固定10/17日延迟不能覆盖政府停摆和供应商中断。根据
[历史特别公告](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm)、
[2013年恢复公告](https://www.cftc.gov/PressRoom/PressReleases/6745-13)、
[2019年恢复公告](https://www.cftc.gov/PressRoom/PressReleases/7864-19)及
[2025年修订补发日程](https://www.cftc.gov/PressRoom/PressReleases/9147-25)，
`configs/cftc_release_audit.yaml`登记四段保守隔离区间，并重算全部六个原持仓规则。
隔离区间由发布时间证据决定，不由回测收益决定；它仍不是逐份历史发布记录的完整重建。
原CFTC假设组不能被当作可执行业绩，隔离组只用于揭示发布时间敏感性。

美联储H.10虽然提供每日观测，正常按周一16:15发布上一周数据；
例如[2021-10-25发布档案](https://www.federalreserve.gov/releases/h10/20211025/)包含10月18—22日观测。
[官方说明](https://www.federalreserve.gov/releases/h10/about.htm)同时说明历史发布档案不随数据库修订。
现有人民币/溢价实验使用的日频延迟假设不满足这个发布时间边界，
只能作为不可执行的渠道敏感性情景，不能替代当时可成交汇率或实际QDII价格。
上述网页及原始证据已保存在`source_probes/cftc-release-audit-20261020/`
和`source_probes/h10-publication-audit-20261020/`。

Put/Call分段预热造成的2012—2017年内部缺口必须保留在账户日历中；
不能把五年账户起点推到2017年，再将实际两年左右的账户标为五年。
扩展首版48条相关窗口标签已列入审计，修复版使用完整价格日历，缺失期间暂停依赖因子的买入。
这属于研究窗口修复，不改变原始Put/Call文件。

中金所成交额/成交量换算均价越出高低价的记录进入隔离，未擅自修正原值；
其占比、缺Delta和不明到期日均在每个因子的质量报告中列出。
合约收盘时间与交割日依据[官方合约细则](https://www.cffex.com.cn/u/cms/www/202003/27165450o6vr.pdf)，
量额单位参照[2024年官方统计](https://www.cffex.com.cn/sj/yearlyReport/2024/2024YearlyReport.pdf)。
这些资料不足以证明交易参与者方向，亦不能解释每一条异常；对应结果仍为探索代理。

SPHD继续保留暂停记录。发行人[美国使用条款](https://www.invesco.com/us/en/resources/terms-of-use.html)
限制自动批量下载等使用，不能把公开产品页面等同于免费完整历史数据授权。
本轮没有购买任何数据，也没有将来源许可未决的数据晋级为唯一长期底座。

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
