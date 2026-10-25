"""The Program record extracted from the page."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .textutil import fold


class Status(str, Enum):
    UPCOMING = "upcoming"
    OPEN = "open"
    ENDED = "ended"
    UNKNOWN = "unknown"


@dataclass
class Program:
    title: str
    company: str | None = None
    program: str | None = None
    institution: str | None = None
    country: str | None = None
    duration: str | None = None
    start: str | None = None
    period_raw: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    ended_flag: bool = False
    conditions: list[str] = field(default_factory=list)
    degree: str | None = None
    tags: list[str] = field(default_factory=list)
    pid: str = ""

    def identity(self) -> str:
        """What makes two postings the same program.

        The study start date (or, failing that, the application start) is part
        of it, so a program re-offered in a later round counts as new, while a
        deadline extension does not.
        """
        when = self.start or (self.period_start.isoformat() if self.period_start else "")
        return "|".join(fold(part) for part in (self.title, self.company or "", self.institution or "", when))

    def compute_pid(self) -> str:
        return hashlib.sha1(self.identity().encode("utf-8")).hexdigest()[:12]

    def status(self, today: date) -> Status:
        if self.ended_flag:
            return Status.ENDED
        if self.period_end and today > self.period_end:
            return Status.ENDED
        if self.period_start and today < self.period_start:
            return Status.UPCOMING
        if self.period_start or self.period_end:
            return Status.OPEN
        return Status.UNKNOWN
