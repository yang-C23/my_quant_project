# 数据契约、单位与复权

本文件是当前数据语义的唯一正文。原始记录、版本化Parquet为长期依据；Qlib为派生层。
历史规范保存在`docs/archive/pre_restart/data_platform.md`，不再作为公式依据。

## 存储与快照

`DATA_ROOT/current.json`仅指向一个已验收结构的不可变快照；结构验收与研究准入分开。

```text
DATA_ROOT/
  current.json
  snapshots/<id>/
    raw/tdx/                 原始行情、GBBQ、证券资料
    staging/daily/           Parquet兼容层，按交易所分区
    staging/adjust/ basics/  可重建派生表
    staging/tdx_statistics.parquet  特殊统计序列，字段不解释为OHLC
    qlib/cn_daily/           可重建兼容缓存
    quarantine/             异常原值与理由
    manifest.json quality.json progress.json
  lake/<dataset>/<version>/
    raw.bin                  原始响应字节或无损API字符串表
    data/market=<market>/year=<year>/part-000.parquet
    manifest.json            来源、schema、单位、许可、校验和、时间
  audits/ source_reports/ research/ monitor/ backups/ recovery_drills/
```

公开标准层schema2按市场和年份分区，Parquet/ZSTD，Arrow类型显式记录。
schema1单文件版本继续可读；升级追加新版本，不覆盖旧文件。
TDX兼容层暂按交易所分区，源文件保留完整，不强行改变旧Qlib接口。

元数据为UTF-8 JSON，金额序列不写JSON的NaN；缺失使用null。
原始层修订追加；只有来源授权允许时才可作为永久档案，授权不明的公开样本不成为唯一底座。

## 字段及量纲

| 字段 | 类型与语义 |
|---|---|
| symbol/code | 字符串，保留前导零；CN为`sh000300`/`sz399006`，外部指数ID单列 |
| date | Arrow date32，交易所本地经济日期 |
| available_at / retrieved_at | UTC timestamp；分别为可用时点与实际取得时点 |
| open/high/low/close | float64，原始不复权行情；缺少OHLC时不伪造 |
| volume / open_interest | int64，单位必须在契约中注明股、份或合约 |
| amount | float64，明确币种与单位；未核实源单位的字段单独命名 |
| 估值和收益 | float64；PE总股本与计算用股本口径分开，收益率以小数为标准 |
| 现金、应收、成交金额、费用 | 账本Decimal；Parquet decimal128(38,18)，报告统计可转float |
| listing/delisting | 官方生命周期与行情覆盖推断分开；后者不等于历史上市名录 |

GBBQ没有公告/支付日期；新快照不生成未经证明的历史ST/涨跌停标志。
缺失股本、市值或换手率保持缺失，不能补成0。未验证的债券/回购等类别不纳入本轮投资研究。

## 通达信格式与更新

32字节记录：`<IIIIIfII>`。股票和标准指数价格除100，ETF及已识别基金除1000。
股票成交量为股，ETF为份；标准`sh000`/`sh999`/`sz399`/`bj899`指数成交量按源手数乘100。
`reserved & 0xffff0000 == 0xc3640000`的大成交量记录先以`volume*100+低16位余数`解码。
该扩展格式以本地二进制样本和跨来源核对支持，余数>=100即拒绝解析；精度不能高于原始存储。
已核对的日期与差异见`source_reports/crosscheck.json`，不据单日一致推断全历史一致。

`sh8800*`、`sz395*`统计值独立保存，不能统一按OHLC过滤。
其余不可解释异常进入隔离区，保留原值；不静默缩放或前向填成价格。

流程：源镜像冻结 → 先解码GBBQ/证券与板块资料 → 逐证券合并历史ZIP与当前vipdoc →
检查全部现存日期（包括历史修订、缺口）→ 隔离 → 派生重算 → Qlib → 全量结构及清单校验 → 原子发布。
重叠记录当前vipdoc优先，旧快照保留。复用需原始文件及解析/派生源码指纹均不变。
断点恢复仅接受相同处理源码；不同源码新建快照。原始数据未增加时也必须检查公司行动变化。
旧tail-read仅作`update --dry-run`新增日期下界估算，不覆盖修订和补漏。

## 复权与分红

GBBQ category=1的四列为：c1每10股现金分红；c2配股价；c3每10股送转；c4每10股配股数。
历史代码交换c2/c4，已修复；`legacy_swapped_rights`只用于旧结果重放。
字段证据：[pytdx解析](https://github.com/rainx/pytdx/blob/master/pytdx/parser/get_xdxr_info.py)。

设前收盘价P、每10股分红D、配股数R、配股价K、送转数B：

```text
理论除权昨收 P* = (10P - D + R×K) / (10+B+R)
当日调整倍率  = P/P*
后复权因子 F_t = F_(t-1) × 当日调整倍率
前复权因子 Q_t = F_t / F_快照末日
调整价格       = 原始价格 × 因子
```

前复权依赖快照末日，未来公司行动会改变旧价格标度，不能将当前前复权值当历史原始可得价格。
以上乘法复权不是实际现金分红到账再投资的总回报：P=10、D/10=1、除息收盘9.2时，
调整收益9.2/9−1与现金总收益(9.2+1)/10−1并不相等。
现金账本仅用原价：除息前持有份额产生应收，支付后成为现金，下一交易时点才允许再投资。
不得叠加“复权收益＋现金股息”。配股认购需单独建模，不默认为无成本现金分红。

指数价格、指数全收益、ETF净值、ETF成交价分别标注。净值已含的管理费用不再重复扣除。
根据份额估算净申赎：`NAV_t × (份额_t − 份额_(t-1)×拆分倍率_t)`；不是资产规模变化，亦非所谓主力资金。

## 历史查询与准入

`DataCatalog.read(dataset, version=..., as_of=...)`读取固定版本并按可用时间过滤。
`history(..., as_of=..., version=..., strict_pit=True)`跨已保存版本取当时最新可用修订；
`observations`保留全部版本供因果特征构建。原始和标准文件均验证哈希。

仅有经济日期不代表知道历史发布时间。未认证历史来源的`strict_pit`查询直接拒绝。
CSI近期文件首次取得时标记first_observed；不将今天下载的历史估值回填为过去可得。
正式准入还需覆盖、单位、公司行动、交易日历、历史成分/ETF选择范围和长期留存依据。
结构检查通过只是其中一项；异常或过期依赖使相关研究和提醒暂停。
