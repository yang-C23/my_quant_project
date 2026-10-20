import json

import pandas as pd
import yaml

from quant.config import Settings
from quant.data.snapshots import SnapshotStore
from quant.longterm import monitor


def test_shadow_stale_future_and_replayed_sessions_do_not_become_alerts(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    identifier, folder = store.create()
    (folder / "payload").write_text("fixture")
    store.seal(identifier, {"publication_status": "validated"})
    store.activate(identifier)
    dates = pd.bdate_range("2026-01-01", "2026-10-23")
    bars = pd.DataFrame({"close": 10.0, "open": 10.0, "high": 11.0, "low": 9.0}, index=dates)
    monkeypatch.setattr(
        monitor, "_load_asset", lambda *args, **kwargs: (bars, {"formal_accepted": False})
    )
    monkeypatch.setattr(
        monitor, "valuation_features", lambda *args: pd.Series(float("nan"), index=bars.index)
    )
    config = tmp_path / "protocol.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "protocol_version": "fixture",
                "funding": {},
                "universe": [{"id": "ETF", "name": "ETF", "market": "CN"}],
            }
        )
    )
    settings = Settings(_env_file=None, data_root=tmp_path)
    first = monitor.daily_monitor(settings, config, now="2026-10-20T06:00Z")
    report = json.loads((tmp_path / "monitor/latest.json").read_text())
    assert report["notifications"][0]["data_date"] == "2026-10-19"
    assert first["shadow"]["observed_session_counts"]["ETF"] == 0
    second = monitor.daily_monitor(settings, config, now="2026-10-20T09:00Z")
    assert second["shadow"]["observed_session_counts"]["ETF"] == 1
    repeated = monitor.daily_monitor(settings, config, now="2026-10-20T10:00Z")
    assert repeated["shadow"]["observed_session_counts"]["ETF"] == 1
    stale = monitor.daily_monitor(settings, config, now="2026-11-01T10:00Z")
    report = json.loads((tmp_path / "monitor/latest.json").read_text())
    assert stale["actionable"] == 0 and not stale["shadow"]["passed"]
    assert "stale_prices_9_calendar_days" in report["notifications"][0]["reasons"]
