import pandas as pd
import pytest

from quant.data.catalog import DataCatalog
from quant.data.providers import parse_cboe_vix, parse_fred


def test_fred_missing_is_not_zero_or_invented_ohlc():
    raw = b"observation_date,SP500\n2020-01-01,.\n2020-01-02,3000\n"
    frame = parse_fred(raw, "SP500")
    assert len(frame) == 1 and frame.iloc[0]["close"] == 3000
    assert "open" not in frame
    assert str(frame.available_at.dt.tz) == "UTC"
    with pytest.raises(ValueError, match="schema"):
        parse_fred(b"date,value\n2020-01-01,1\n", "SP500")


def test_catalog_versions_pit_gate_types_and_integrity(tmp_path):
    catalog = DataCatalog(tmp_path)
    raw = b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2020,10,12,9,11\n"
    frame = parse_cboe_vix(raw)
    manifest = catalog.ingest(
        "vix",
        raw,
        frame,
        source={"publisher": "fixture"},
        parser_version="1",
        quality={"pit_verified": False},
    )
    replay = catalog.ingest(
        "vix",
        raw,
        frame,
        source={"publisher": "fixture"},
        parser_version="1",
        quality={"pit_verified": False},
    )
    assert replay == manifest
    assert catalog.read("vix", as_of="2020-01-02T00:00Z").empty
    assert len(catalog.read("vix", as_of="2020-01-03T00:00Z")) == 1
    with pytest.raises(ValueError, match="publication"):
        catalog.read("vix", strict_pit=True)
    assert "date32" in manifest["arrow_schema"]
    assert pd.api.types.is_string_dtype(catalog.read("vix").symbol)
    payload = catalog.root / "vix" / manifest["version"] / manifest["data_files"][0]["path"]
    payload.write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        catalog.read("vix")


def test_full_snapshot_backup_restore_and_live_pointer_unchanged(tmp_path):
    from quant.data.recovery import backup_snapshot, restore_drill
    from quant.data.snapshots import SnapshotStore

    store = SnapshotStore(tmp_path)
    identifier, path = store.create()
    (path / "data.txt").write_text("immutable evidence")
    store.seal(identifier, {"publication_status": "validated"})
    store.activate(identifier)
    backup_snapshot(tmp_path, identifier)
    report = restore_drill(tmp_path, identifier)
    assert report["integrity"]["ok"] and report["isolated_publish_and_rollback"]
    assert store.current() == identifier


def test_revision_history_never_exposes_future_publication(tmp_path):
    catalog = DataCatalog(tmp_path)

    def ingest(raw, value, available):
        return catalog.ingest(
            "valuation",
            raw,
            pd.DataFrame(
                {
                    "symbol": ["X"],
                    "date": ["2020-01-01"],
                    "pe": [value],
                    "available_at": [available],
                }
            ),
            source={"publisher": "fixture"},
            parser_version="1",
            quality={"pit_verified": True},
        )

    first = ingest(b"v1", 10.0, "2020-01-02T00:00Z")
    ingest(b"v2", 20.0, "2020-02-01T00:00Z")
    assert catalog.history("valuation", as_of="2020-01-10T00:00Z").iloc[0].pe == 10
    assert catalog.history("valuation", as_of="2020-02-10T00:00Z").iloc[0].pe == 20
    assert (
        catalog.history("valuation", version=first["version"], as_of="2020-02-10T00:00Z").iloc[0].pe
        == 10
    )


def test_baostock_timeout_is_bounded_and_not_a_success(tmp_path, monkeypatch):
    import subprocess
    from quant.data.providers import fetch_baostock

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 90
        raise subprocess.TimeoutExpired("fixture", 90)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = fetch_baostock(DataCatalog(tmp_path), ["sh000300"], end="2020-01-01")
    assert result[0]["status"] == "unavailable" and "90 seconds" in result[0]["reason"]


def test_cffex_null_quotes_and_cftc_release_dates_are_not_invented():
    import io
    import zipfile
    from quant.data.derivatives import parse_cffex, parse_cftc

    def archive(name, text, encoding="utf-8"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as zipped:
            zipped.writestr(name, text.encode(encoding))
        return stream.getvalue()

    raw = archive(
        "20260901_1.csv",
        "合约代码,今开盘,今结算,成交量,持仓量\nIF2609,0,4000,100,200\nIO2609-C-4000,--,10,0,20\n合计,--,0,100,220\n",
        "gb18030",
    )
    frame = parse_cffex(raw, "2026-10-20T00:00Z")
    assert len(frame) == 2 and pd.isna(frame.loc[frame.symbol.str.startswith("IO"), "open"].iloc[0])
    columns = [
        "Report_Date_as_YYYY-MM-DD",
        "CFTC_Contract_Market_Code",
        "Market_and_Exchange_Names",
        "Open_Interest_All",
        "Dealer_Positions_Long_All",
        "Dealer_Positions_Short_All",
        "Asset_Mgr_Positions_Long_All",
        "Asset_Mgr_Positions_Short_All",
        "Lev_Money_Positions_Long_All",
        "Lev_Money_Positions_Short_All",
    ]
    raw = archive("FinFutYY.txt", ",".join(columns) + "\n2025-01-07,001234,TEST,100,1,2,3,4,5,6\n")
    frame = parse_cftc(raw, "2026-10-20T00:00Z")
    assert frame.iloc[0].symbol == "001234"
    assert frame.iloc[0].available_at == pd.Timestamp("2026-10-20T00:00Z")
    assert frame.iloc[0].date == pd.Timestamp("2025-01-07")


def test_crosscheck_covers_other_etfs_and_date32_input(tmp_path):
    from quant.config import Settings
    from quant.data.reconcile import crosscheck
    from quant.data.snapshots import SnapshotStore

    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-10-19")],
            "symbol": ["sh560000"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [100],
            "amount": [100.0],
        }
    )
    store = SnapshotStore(tmp_path)
    identifier, folder = store.create()
    (folder / "staging/daily").mkdir(parents=True)
    frame.to_parquet(folder / "staging/daily/part.parquet", index=False)
    store.seal(identifier, {"publication_status": "validated"})
    store.activate(identifier)
    DataCatalog(tmp_path).ingest(
        "baostock_etf_20261019",
        b"fixture",
        frame,
        source={"publisher": "fixture"},
        parser_version="fixture",
        quality={},
    )
    report = crosscheck(Settings(_env_file=None, data_root=tmp_path))
    assert report["results"][0]["symbol"] == "sh560000"
    assert report["results"][0]["status"] == "within_tolerance"
