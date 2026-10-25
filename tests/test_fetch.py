import pytest
import requests

from waaid_radar.fetch import FetchError, fetch_html


class Response:
    def __init__(self, status, body=b"", encoding=None):
        self.status_code, self.content, self.encoding = status, body, encoding


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.headers_seen = []

    def get(self, url, headers=None, timeout=None):
        self.headers_seen.append(headers)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_retries_then_decodes_arabic_even_with_a_wrong_charset():
    body = "<p>بدء التقديم على برنامج</p>".encode()
    session = Session(Response(503), requests.ConnectionError("reset"), Response(200, body, "ISO-8859-1"))
    sleeps = []
    assert fetch_html("https://x", session=session, sleep=sleeps.append) == "<p>بدء التقديم على برنامج</p>"
    assert sleeps == [2, 4]
    assert session.headers_seen[0]["Accept-Language"].startswith("ar")


def test_client_errors_are_not_retried():
    session = Session(Response(404))
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_html("https://x", session=session, sleep=lambda _: None)
    assert session.responses == []


def test_gives_up_after_the_last_attempt():
    session = Session(Response(500), Response(502), Response(503))
    with pytest.raises(FetchError, match="HTTP 503"):
        fetch_html("https://x", session=session, sleep=lambda _: None)
