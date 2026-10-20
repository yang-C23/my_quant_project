"""Reject source changes rather than silently treating bad bars as opportunities."""

import pytest

from quant.data.spx_history import parse_spx


def test_spx_close_only_and_timezone():
    f = parse_spx(b"DATE,SPX\n01/02/1975,70.23\n07/02/1975,95.0\n")
    assert f.close.tolist() == [70.23, 95.0]
    assert str(f.available_at.iloc[0]) == "1975-01-02 22:00:00+00:00"
    assert str(f.available_at.iloc[1]) == "1975-07-02 21:00:00+00:00"
    assert not {"open", "volume", "dividend"} & set(f)


@pytest.mark.parametrize(
    "raw",
    [
        b"DATE,CLOSE\n01/02/1975,70\n",
        b"DATE,SPX\n01/02/1975,0\n",
        b"DATE,SPX\n01/02/1975,NaN\n",
        b"DATE,SPX\n01/02/1975,70\n01/02/1975,71\n",
        b"DATE,SPX\n01/04/1975,70\n",
    ],
)
def test_spx_rejects_invalid_source(raw):
    with pytest.raises(ValueError):
        parse_spx(raw)
