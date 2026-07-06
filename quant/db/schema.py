"""PostgreSQL DDL: schema, tables, indexes, and views for TDX quant data."""

SCHEMA = "tdx"

# ── Tables ────────────────────────────────────────────────────────────────────

DDL_TABLES = f"""
-- Schema isolation
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

-- 证券主表（个股 / ETF / 指数 统一元数据）
CREATE TABLE IF NOT EXISTS {SCHEMA}.securities (
    symbol        VARCHAR(12)  PRIMARY KEY,   -- sz000001 / sh600000
    code          VARCHAR(10)  NOT NULL,       -- 000001
    name          VARCHAR(60),
    exchange      VARCHAR(4)   NOT NULL,       -- sz / sh / bj
    board         VARCHAR(20),                 -- main / sme / chinext / star / bse
    sec_type      VARCHAR(10)  NOT NULL DEFAULT 'stock',  -- stock / index / etf / bond
    listing_date  DATE,
    delisting_date DATE,
    is_st         BOOLEAN      DEFAULT FALSE,
    created_at    TIMESTAMPTZ  DEFAULT now()
);

-- 日 K 线（个股 + 指数 统一存储）
CREATE TABLE IF NOT EXISTS {SCHEMA}.daily_kline (
    symbol   VARCHAR(12)  NOT NULL,
    date     DATE         NOT NULL,
    open     DOUBLE PRECISION,
    high     DOUBLE PRECISION,
    low      DOUBLE PRECISION,
    close    DOUBLE PRECISION,
    volume   BIGINT,
    amount   DOUBLE PRECISION,
    PRIMARY KEY (symbol, date)
);

-- 股本变迁 (GBBQ) 原始数据
CREATE TABLE IF NOT EXISTS {SCHEMA}.gbbq (
    id        SERIAL       PRIMARY KEY,
    category  SMALLINT     NOT NULL,
    symbol    VARCHAR(12)  NOT NULL,
    date      DATE         NOT NULL,
    c1        DOUBLE PRECISION DEFAULT 0,  -- 除权: 分红;  股本变动: 前流通盘
    c2        DOUBLE PRECISION DEFAULT 0,  -- 除权: 配股价; 股本变动: 前总股本
    c3        DOUBLE PRECISION DEFAULT 0,  -- 除权: 送转股; 股本变动: 后流通盘
    c4        DOUBLE PRECISION DEFAULT 0   -- 除权: 配股;   股本变动: 后总股本
);
CREATE INDEX IF NOT EXISTS idx_gbbq_symbol_date
    ON {SCHEMA}.gbbq (symbol, date);

-- 前收盘、涨跌、换手率、市值
CREATE TABLE IF NOT EXISTS {SCHEMA}.stocks_basic (
    symbol        VARCHAR(12)       NOT NULL,
    date          DATE              NOT NULL,
    close         DOUBLE PRECISION,
    preclose      DOUBLE PRECISION,
    change_pct    DOUBLE PRECISION,
    amplitude     DOUBLE PRECISION,
    turnover      DOUBLE PRECISION,
    floatmv       DOUBLE PRECISION,
    totalmv       DOUBLE PRECISION,
    PRIMARY KEY (symbol, date)
);

-- 复权因子（每天一条，和日线对齐）
CREATE TABLE IF NOT EXISTS {SCHEMA}.adjust_factor (
    symbol      VARCHAR(12)       NOT NULL,
    date        DATE              NOT NULL,
    hfq_factor  DOUBLE PRECISION  NOT NULL DEFAULT 1.0,
    qfq_scale   DOUBLE PRECISION  NOT NULL DEFAULT 1.0,
    qfq_offset  DOUBLE PRECISION  NOT NULL DEFAULT 0.0,
    PRIMARY KEY (symbol, date)
);

-- 板块 / 指数 主表
CREATE TABLE IF NOT EXISTS {SCHEMA}.blocks_info (
    id            SERIAL       PRIMARY KEY,
    block_type    VARCHAR(30)  NOT NULL,   -- tdx_general / tdx_research / concept / style / region
    block_name    VARCHAR(100) NOT NULL,
    block_symbol  VARCHAR(20),
    block_code    VARCHAR(30)  NOT NULL,
    parent_code   VARCHAR(30)  DEFAULT '',
    block_level   SMALLINT     DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_blocks_info_code
    ON {SCHEMA}.blocks_info (block_code);

-- 板块成分股
CREATE TABLE IF NOT EXISTS {SCHEMA}.blocks_member (
    id            SERIAL       PRIMARY KEY,
    stock_symbol  VARCHAR(12)  NOT NULL,
    block_code    VARCHAR(30)  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blocks_member_stock
    ON {SCHEMA}.blocks_member (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_blocks_member_block
    ON {SCHEMA}.blocks_member (block_code);

-- 假期日历
CREATE TABLE IF NOT EXISTS {SCHEMA}.holidays (
    date  DATE PRIMARY KEY
);
"""

# ── Views ─────────────────────────────────────────────────────────────────────

DDL_VIEWS = f"""
-- 不复权日线 + basic 指标
CREATE OR REPLACE VIEW {SCHEMA}.v_bfq_daily AS
SELECT
    k.symbol,
    k.date,
    k.open,
    k.high,
    k.low,
    k.close,
    k.volume,
    k.amount,
    b.preclose,
    b.change_pct,
    b.amplitude,
    b.turnover,
    b.floatmv,
    b.totalmv,
    f.hfq_factor
FROM {SCHEMA}.daily_kline k
LEFT JOIN {SCHEMA}.stocks_basic b
    ON k.symbol = b.symbol AND k.date = b.date
LEFT JOIN {SCHEMA}.adjust_factor f
    ON k.symbol = f.symbol AND k.date = f.date;

-- 后复权日线
CREATE OR REPLACE VIEW {SCHEMA}.v_hfq_daily AS
SELECT
    k.symbol,
    k.date,
    ROUND((k.open  * f.hfq_factor)::numeric, 2) AS open,
    ROUND((k.high  * f.hfq_factor)::numeric, 2) AS high,
    ROUND((k.low   * f.hfq_factor)::numeric, 2) AS low,
    ROUND((k.close * f.hfq_factor)::numeric, 2) AS close,
    k.volume,
    k.amount,
    ROUND((b.preclose * f.hfq_factor)::numeric, 2) AS preclose,
    f.hfq_factor
FROM {SCHEMA}.daily_kline k
JOIN {SCHEMA}.adjust_factor f
    ON k.symbol = f.symbol AND k.date = f.date
LEFT JOIN {SCHEMA}.stocks_basic b
    ON k.symbol = b.symbol AND k.date = b.date;

-- 前复权日线（TDX 减法公式: QFQ = raw * scale - offset）
CREATE OR REPLACE VIEW {SCHEMA}.v_qfq_daily AS
SELECT
    k.symbol,
    k.date,
    ROUND((k.open  * f.qfq_scale - f.qfq_offset)::numeric, 3) AS open,
    ROUND((k.high  * f.qfq_scale - f.qfq_offset)::numeric, 3) AS high,
    ROUND((k.low   * f.qfq_scale - f.qfq_offset)::numeric, 3) AS low,
    ROUND((k.close * f.qfq_scale - f.qfq_offset)::numeric, 3) AS close,
    k.volume,
    k.amount,
    ROUND((b.preclose * f.qfq_scale - f.qfq_offset)::numeric, 3) AS preclose,
    f.qfq_scale,
    f.qfq_offset,
    f.hfq_factor
FROM {SCHEMA}.daily_kline k
JOIN {SCHEMA}.adjust_factor f
    ON k.symbol = f.symbol AND k.date = f.date
LEFT JOIN {SCHEMA}.stocks_basic b
    ON k.symbol = b.symbol AND k.date = b.date;
"""


def init_schema(conn):
    """Create the tdx schema, all tables, and indexes."""
    with conn.cursor() as cur:
        cur.execute(DDL_TABLES)
    conn.commit()


def create_views(conn):
    """Create or replace all views."""
    with conn.cursor() as cur:
        cur.execute(DDL_VIEWS)
    conn.commit()
