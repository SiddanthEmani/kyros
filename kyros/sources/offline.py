"""Fixture-backed sources for offline runs (`run.py --offline`).

Lets the whole pipeline — enrich, filter, dedup, rank, write — be
exercised without touching the network, which is how the feed shape gets
reviewed in a sandbox or in CI before a live refresh.
"""

from __future__ import annotations

import logging
import json
from datetime import date, datetime, timedelta, timezone

from ..config import PROJECT_DIR
from . import cerebralvalley, dothebay, funcheap, stanford, visitsanjose

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

    for name, parse in (("cerebralvalley_events.json", cerebralvalley.parse_payload),
                        ("dothebay_day.json", dothebay.parse_payload),
                        ("stanford_events.json", stanford.parse_payload)):
        path = FIXTURES / name
        if path.exists():
            events += parse(json.loads(path.read_text()), log)

    vsj = FIXTURES / "visitsanjose_listings.json"
    if vsj.exists() and tz is not None:
        # Every listing gets the committed detail page's time; the point
        # here is the pipeline, not the time extraction.
        detail = (FIXTURES / "visitsanjose_detail.html").read_text()
        when = visitsanjose.detail_time(detail) or (19, 0)
        for item in visitsanjose.select_listings(
                json.loads(vsj.read_text()), date(2026, 9, 1), 60):
            events.append(visitsanjose.make_event(item, when, tz))

    fc = FIXTURES / "funcheap_sanjose.xml"
    if fc.exists():
        got, _skipped = funcheap.parse_rss(
            fc.read_text(), "san-jose", log, tz=tz)
        events += got

    log.info("  offline fixtures: %d events", len(events))
    return _shift_to_future(events, tz)
