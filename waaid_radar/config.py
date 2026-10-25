"""Settings, read from environment variables (GitHub secrets/variables or a .env file)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Program

DEFAULT_URL = "https://sites.moe.gov.sa/scholarship-program/paths/path-waaid/"
DEFAULT_PERSONAL_TAGS = frozenset({"حاسب", "لخريجي_الحاسب"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    token: str | None = None
    channel: str | None = None          # "@my_channel" or "-100…": every program is posted here
    admin_chat: str | None = None       # your private chat: alerts + programs matching personal_tags
    personal_tags: frozenset[str] | None = DEFAULT_PERSONAL_TAGS  # None = off, {"*"} = everything
    url: str = DEFAULT_URL
    state_path: Path = Path("data/state.json")
    tz: ZoneInfo = ZoneInfo("Asia/Riyadh")
    quiet_hours: tuple[int, int] | None = (23, 7)  # no reminders, silent posts
    seed_post_active: bool = True       # first run: publish programs whose application has not ended
    render_js: str = "false"            # "false" | "auto" | "true"
    dry_run: bool = False
    user_agent: str | None = None

    @property
    def main_chat(self) -> str | None:
        return self.channel or self.admin_chat

    @property
    def personal_chat(self) -> str | None:
        return self.admin_chat if self.personal_tags is not None else None

    def wants(self, program: Program) -> bool:
        """Does the program match the personal-alert tags?"""
        if self.personal_tags is None:
            return False
        return "*" in self.personal_tags or bool(self.personal_tags & set(program.tags))

    def posts_to_main(self, program: Program) -> bool:
        """A channel gets everything; a private-chat-only setup gets the matching programs."""
        return bool(self.channel) or self.personal_tags is None or self.wants(program)

    def is_quiet(self, now: datetime) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        hour = now.hour
        return (hour >= start or hour < end) if start > end else (start <= hour < end)

    def require_telegram(self) -> None:
        if self.dry_run:
            return
        if not self.token:
            raise ConfigError("TELEGRAM_BOT_TOKEN غير مضبوط.")
        if not self.main_chat:
            raise ConfigError("اضبط TELEGRAM_CHANNEL_ID أو TELEGRAM_ADMIN_CHAT_ID على الأقل.")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = (env.get(name) or "").strip()
            return value or None

        return cls(
            token=get("TELEGRAM_BOT_TOKEN"),
            channel=_chat_id(get("TELEGRAM_CHANNEL_ID")),
            admin_chat=_chat_id(get("TELEGRAM_ADMIN_CHAT_ID")),
            personal_tags=_tags(get("PERSONAL_TAGS")),
            url=get("WAAID_URL") or DEFAULT_URL,
            state_path=Path(get("STATE_PATH") or "data/state.json"),
            tz=ZoneInfo(get("TIMEZONE") or "Asia/Riyadh"),
            quiet_hours=_hours(get("QUIET_HOURS")),
            seed_post_active=_bool(get("SEED_POST_ACTIVE"), True),
            render_js=_render(get("RENDER_JS")),
            dry_run=_bool(get("DRY_RUN"), False),
            user_agent=get("USER_AGENT"),
        )


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env support for local runs (KEY=VALUE lines); real environment variables win."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _chat_id(value: str | None) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"-?\d+", value):
        return value
    if value.startswith("https://t.me/"):
        value = "@" + value.removeprefix("https://t.me/").strip("/")
    return value if value.startswith("@") else "@" + value


def _tags(value: str | None) -> frozenset[str] | None:
    if value is None:
        return DEFAULT_PERSONAL_TAGS
    if value.lower() in {"none", "off", "-", "false"}:
        return None
    if value.lower() in {"*", "all", "الكل"}:
        return frozenset({"*"})
    return frozenset(tag.lstrip("#") for tag in re.split(r"[,\s،]+", value) if tag.strip("#"))


def _hours(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return (23, 7)
    if value.lower() in {"none", "off", "-", "false"}:
        return None
    match = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", value)
    if not match or not all(0 <= int(h) <= 23 for h in match.groups()):
        raise ConfigError(f"QUIET_HOURS should look like 23-7, got {value!r}")
    return int(match.group(1)), int(match.group(2))


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on", "نعم"}


def _render(value: str | None) -> str:
    value = (value or "false").lower()
    if value not in {"false", "auto", "true"}:
        raise ConfigError(f"RENDER_JS must be false, auto or true, got {value!r}")
    return value
