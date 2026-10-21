import pytest

from quant.data.free_history import shiller_workbook_url


def test_author_link_supports_protocol_relative_cdn_and_escaped_query():
    page = b'<a href="//img1.wsimg.com/path/ie_data.xls?ver=1&amp;download=1">Download</a>'
    assert shiller_workbook_url(page) == "https://img1.wsimg.com/path/ie_data.xls?ver=1&download=1"
    with pytest.raises(ValueError, match="host"):
        shiller_workbook_url(b'<a href="https://unknown.example/ie_data.xls">Download</a>')
    with pytest.raises(ValueError, match="ambiguous"):
        shiller_workbook_url(b"<p>ie_data.xls</p>")
