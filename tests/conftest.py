import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TZ = ZoneInfo("America/Los_Angeles")
# All fixtures are written relative to this date so tests never drift.
TODAY = datetime(2026, 8, 30, 12, 0, tzinfo=TZ)


@pytest.fixture
def log():
    logger = logging.getLogger("kyros-test")
    logger.addHandler(logging.NullHandler())
    return logger


@pytest.fixture
def fixture_text():
    def _read(name):
        return (FIXTURES / name).read_text()
    return _read
