import pytest

from waaid_radar.telegram import Telegram, TelegramError


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url.rsplit("/", 1)[-1], json))
        return self.responses.pop(0)


def ok(message_id=7):
    return FakeResponse({"ok": True, "result": {"message_id": message_id}})


def make(*responses):
    sleeps = []
    session = FakeSession(*responses)
    return Telegram("TOKEN", session=session, sleep=sleeps.append, clock=lambda: 0.0), session, sleeps


def test_send_uses_html_and_reply_parameters():
    tg, session, _ = make(ok(42))
    assert tg.send("@c", "<b>مرحبا</b>", reply_to=5, silent=True) == 42
    method, payload = session.calls[0]
    assert method == "sendMessage"
    assert payload["parse_mode"] == "HTML" and payload["disable_notification"] is True
    assert payload["reply_parameters"] == {"message_id": 5, "allow_sending_without_reply": True}
    assert payload["link_preview_options"] == {"is_disabled": True}


def test_rate_limit_is_respected():
    limited = FakeResponse({"ok": False, "error_code": 429, "description": "Too Many Requests",
                            "parameters": {"retry_after": 9}}, 429)
    tg, session, sleeps = make(limited, ok())
    tg.send("@c", "x")
    assert sleeps == [10] and len(session.calls) == 2


def test_falls_back_to_plain_text_when_html_is_rejected():
    bad = FakeResponse({"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"}, 400)
    tg, session, _ = make(bad, ok())
    tg.send("@c", "<b>عنوان</b> &amp; نص")
    retry = session.calls[1][1]
    assert "parse_mode" not in retry and retry["text"] == "عنوان & نص"


def test_other_errors_raise():
    forbidden = FakeResponse({"ok": False, "error_code": 403, "description": "Forbidden: bot is not a member"}, 403)
    tg, _, _ = make(forbidden)
    with pytest.raises(TelegramError) as err:
        tg.send("@c", "x")
    assert err.value.code == 403


def test_edit_treats_an_unchanged_text_as_done():
    unchanged = FakeResponse({"ok": False, "error_code": 400,
                              "description": "Bad Request: message is not modified: specified new message content "
                                             "and reply markup are exactly the same"}, 400)
    tg, session, _ = make(unchanged)
    tg.edit("@c", 5, "<b>نص</b>")
    method, payload = session.calls[0]
    assert method == "editMessageText" and payload["message_id"] == 5 and payload["parse_mode"] == "HTML"


def test_edit_falls_back_to_plain_text_and_raises_other_errors():
    bad = FakeResponse({"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"}, 400)
    tg, session, _ = make(bad, ok())
    tg.edit("@c", 5, "<b>عنوان</b>")
    assert "parse_mode" not in session.calls[1][1] and session.calls[1][1]["text"] == "عنوان"
    gone = FakeResponse({"ok": False, "error_code": 400, "description": "Bad Request: message to edit not found"}, 400)
    tg, _, _ = make(gone)
    with pytest.raises(TelegramError):
        tg.edit("@c", 5, "x")


def test_messages_to_one_chat_are_spaced_out():
    times = iter([0.0, 1.0, 4.2])  # first send at t=0, second asked at t=1 → waits 2.2 s
    sleeps = []
    tg = Telegram("T", session=FakeSession(ok(), ok()), sleep=sleeps.append, clock=lambda: next(times))
    tg.send("@c", "a")
    tg.send("@c", "b")
    assert sleeps == [pytest.approx(2.2)]
