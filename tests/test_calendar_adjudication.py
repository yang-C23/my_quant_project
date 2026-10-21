"""A missing session must not be inferred to be a holiday or forward-filled."""

import hashlib
import json

import pandas as pd
import pytest

from quant.data.calendar_adjudication import adjudicate_sessions


def test_calendar_removes_only_evidenced_holiday_keeps_unresolved_gap(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"sessions": ["2000-12-29", "2001-01-02", "2001-01-03"]}))
    frame = pd.DataFrame(
        {"close": [100.0, 100.0, 90.0]},
        index=pd.to_datetime(["2000-12-29", "2001-01-01", "2001-01-03"]),
    )
    decision = dict(
        calendar_file="calendar.json",
        calendar_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        removed_non_sessions={"nasdaq100": ["2001-01-01"]},
        inserted_closes={},
        unresolved_missing_sessions={"nasdaq100": ["2001-01-02"]},
        calendar_library="fixture",
    )
    result, evidence = adjudicate_sessions(frame, "nasdaq100", decision, tmp_path)
    assert list(result.index) == list(pd.to_datetime(["2000-12-29", "2001-01-03"]))
    assert evidence["unresolved_missing_sessions"] == ["2001-01-02"]
    # An authoritative observation may fill the missing session; no interpolation.
    decision["inserted_closes"] = {"nasdaq100": {"2001-01-02": 95.0}}
    decision["unresolved_missing_sessions"]["nasdaq100"] = []
    result, _ = adjudicate_sessions(frame, "nasdaq100", decision, tmp_path)
    assert result.loc["2001-01-02", "close"] == 95.0
    decision["removed_non_sessions"]["nasdaq100"] = []
    with pytest.raises(ValueError, match="unexpected non-session"):
        adjudicate_sessions(frame, "nasdaq100", decision, tmp_path)
