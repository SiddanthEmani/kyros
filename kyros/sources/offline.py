"""Fixture-backed sources for offline runs (`run.py --offline`).

Lets the whole pipeline — enrich, filter, dedup, rank, write — be
exercised without touching the network, which is how the feed shape gets
reviewed in a sandbox or in CI before a live refresh.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from ..config import PROJECT_DIR
from . import funcheap, ticketmaster

FIXTURES = PROJECT_DIR / "tests" / "fixtures"


def _tz(config: dict):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    except Exception:  # noqa: BLE001
        return None


def _shift_to_future(events: list, tz) -> list:
    """Fixtures carry fixed dates. Slide them into the lookahead window so
    the filters see them as upcoming, preserving weekday and hour."""
    if not events:
        return events
    now = datetime.now(timezone.utc)
    earliest = min(e.start for e in events)
    if earliest >= now:
        return events
    weeks = ((now - earliest).days // 7) + 1
    offset = timedelta(weeks=weeks)
    for e in events:
        e.start += offset
        e.end += offset
    return events


def fetch(config: dict, log: logging.Logger) -> list:
    tz = _tz(config)
    events: list = []

    tm = FIXTURES / "ticketmaster_events.json"
    if tm.exists():
        events += ticketmaster.parse_payload(
            json.loads(tm.read_text()), "ticketmaster/music", log)

    fc = FIXTURES / "funcheap_sanjose.xml"
    if fc.exists():
        got, _skipped = funcheap.parse_rss(
            fc.read_text(), "san-jose", log, tz=tz)
        events += got

    log.info("  offline fixtures: %d events", len(events))
    return _shift_to_future(events, tz)
