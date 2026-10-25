from datetime import date
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 24)


def fixture_text(name: str) -> str:
    """Fixture files mark zero-width spaces as {ZW} so they stay visible in review."""
    return (FIXTURES / name).read_text(encoding="utf-8").replace("{ZW}", "​")


@pytest.fixture
def lines_text() -> str:
    return fixture_text("page_flat.txt")


@pytest.fixture
def flat_text(lines_text: str) -> str:
    """The same page with every line break removed, like WebFetch's output."""
    return "".join(line.strip() for line in lines_text.splitlines())


@pytest.fixture
def page_html() -> str:
    return fixture_text("page.html")
