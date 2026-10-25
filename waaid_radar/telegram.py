"""A small Telegram Bot API client: throttling, retries, and a dry-run stand-in."""

from __future__ import annotations

import html
import logging
import re
import time
from collections.abc import Callable

import requests

API = "https://api.telegram.org"
log = logging.getLogger("waaid_radar")


class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int, description: str):
        super().__init__(f"{method} failed ({code}): {description}")
        self.code = code
        self.description = description


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


class Telegram:
    """Telegram allows about 20 messages a minute per channel; min_interval keeps us under it."""

    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        min_interval: float = 3.2,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.token = token
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.sleep = sleep
        self.clock = clock
        self._last_sent: dict[str, float] = {}

    def call(self, method: str, payload: dict) -> dict:
        url = f"{API}/bot{self.token}/{method}"
        for attempt in range(5):
            try:
                response = self.session.post(url, json=payload, timeout=30)
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == 4:
                    raise TelegramError(method, 0, str(exc)) from exc
                self.sleep(2 ** attempt)
                continue
            if data.get("ok"):
                return data["result"]
            code = int(data.get("error_code") or response.status_code)
            description = data.get("description", "")
            if code == 429:
                self.sleep(int(data.get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            if code >= 500 and attempt < 4:
                self.sleep(2 ** attempt)
                continue
            raise TelegramError(method, code, description)
        raise TelegramError(method, 429, "still rate-limited after retries")

    def _throttle(self, chat_id: str) -> None:
        last = self._last_sent.get(str(chat_id))
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_sent[str(chat_id)] = self.clock()

    def send(self, chat_id: str, text: str, *, reply_to: int | None = None, silent: bool = False) -> int:
        self._throttle(chat_id)
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": silent,
        }
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            return self.call("sendMessage", payload)["message_id"]
        except TelegramError as exc:
            if exc.code != 400 or "parse" not in exc.description.lower():
                raise
            log.warning("Telegram rejected the HTML, sending plain text instead: %s", exc.description)
            payload.pop("parse_mode")
            payload["text"] = strip_html(text)
            return self.call("sendMessage", payload)["message_id"]

    def forward(self, chat_id: str, from_chat_id: str, message_id: int, *, silent: bool = False) -> int:
        self._throttle(chat_id)
        payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id,
                   "disable_notification": silent}
        return self.call("forwardMessage", payload)["message_id"]

    def get_me(self) -> dict:
        return self.call("getMe", {})

    def get_chat(self, chat_id: str) -> dict:
        return self.call("getChat", {"chat_id": chat_id})

    def get_chat_member(self, chat_id: str, user_id: int) -> dict:
        return self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})


class DryRunTelegram:
    """Prints what would be sent instead of sending it."""

    def __init__(self, out: Callable[[str], None] = print):
        self.out = out
        self.sent: list[dict] = []
        self._next_id = 1000

    def _record(self, **entry) -> int:
        self._next_id += 1
        entry["message_id"] = self._next_id
        self.sent.append(entry)
        return self._next_id

    def send(self, chat_id: str, text: str, *, reply_to: int | None = None, silent: bool = False) -> int:
        flags = " ".join(f for f, on in (("(reply)", reply_to), ("(silent)", silent)) if on)
        self.out(f"\n──── → {chat_id} {flags}\n{strip_html(text)}")
        return self._record(kind="send", chat_id=chat_id, text=text, reply_to=reply_to, silent=silent)

    def forward(self, chat_id: str, from_chat_id: str, message_id: int, *, silent: bool = False) -> int:
        self.out(f"\n──── → {chat_id}: forward of message {message_id} from {from_chat_id}")
        return self._record(kind="forward", chat_id=chat_id, from_chat_id=from_chat_id,
                            forwarded=message_id, silent=silent)
