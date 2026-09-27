"""Visit San Jose — the city tourism board's events calendar.

The strongest San Jose coverage there is: San Jose Civic, the California
Theatre, the Montgomery, Santana Row, the neighborhood festivals. The
calendar page is an Angular app over one JSON endpoint (`/event-listings`)
that returns every listing with dates but no times. The start time lives
only on each event's detail page, so those are fetched for the events
inside the window; a listing whose time can't be found is dropped, never
guessed.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime, timedelta

from ..http import http_get
from ..model import Event, safe_str

NAME = "visitsanjose"

BASE = "https://www.sanjose.org"
LISTINGS_URL = BASE + "/event-listings"
# Longer runs are installations and exhibitions, not a night out.
MAX_RUN_DAYS = 3
MAX_DETAIL_FETCHES = 80

_TIME_BLOCK_RE = re.compile(
    r'listing-detail--secondary--ticket-info">\s*<p>\s*'
    r"(\d{1,2}):(\d{2})\s*([AP]M)", re.IGNORECASE)
_TIME_TEXT_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", re.IGNORECASE)
_STREET_RE = re.compile(r'itemprop="streetAddress">([^<]+)<')
_TAG_RE = re.compile(r"<[^>]+>")


def _date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except (AttributeError, ValueError):
        return None


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", s or ""))).strip()


def _on(v) -> bool:
    return safe_str(v).strip().lower() == "on"


def select_listings(payload, today: date, days: int) -> list[dict]:
    """Listings worth a detail fetch: public, in person, a short run, and
    with a date inside the window. Adds `_date` (the first date in the
    window) to each."""
    out: list[dict] = []
    if not isinstance(payload, list):
        return out
    horizon = today + timedelta(days=days)
    for item in payload:
        if not isinstance(item, dict):
            continue
        if _on(item.get("field_hide_event_from_search")) or _on(
                item.get("field_show_as_virtaul")):
            continue
        first, last = _date(item.get("start_date")), _date(item.get("end_date"))
        if first is None:
            continue
        last = last or first
        if (last - first).days >= MAX_RUN_DAYS:
            continue
        dates = [d for d in (_date(x) for x in safe_str(
            item.get("events_date")).split("|")) if d] or [first]
        upcoming = [d for d in dates if today <= d <= horizon]
        if not upcoming:
            continue
        out.append({**item, "_date": upcoming[0]})
    return out


def detail_time(page: str) -> tuple[int, int] | None:
    """The start time from a detail page's "When" block."""
    m = _TIME_BLOCK_RE.search(page or "")
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return hour, int(m.group(2))


def description_time(text: str) -> tuple[int, int] | None:
    m = _TIME_TEXT_RE.search(text or "")
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return hour, int(m.group(2) or 0)


def make_event(item: dict, when: tuple[int, int], tz,
               street: str = "") -> Event:
    hour, minute = when
    day: date = item["_date"]
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    categories = [c.strip() for c in html.unescape(
        safe_str(item.get("categories"))).split(",") if c.strip()]
    venue = _text(safe_str(item.get("venue")))
    city = safe_str(item.get("city")).strip() or "San Jose"
    location = ", ".join(p for p in (venue, street.strip(" ,"), f"{city}, CA")
                         if p)
    free = "Free Events" in categories
    link = safe_str(item.get("link"))
    return Event(
        event_id=f"visitsanjose-{link.rsplit('/', 1)[-1]}-{day:%Y%m%d}",
        title=_text(safe_str(item.get("title"))),
        start=start, end=start + timedelta(hours=2),
        location=location,
        description=_text(safe_str(item.get("field_event_description")))[:1200],
        url=BASE + link if link.startswith("/") else link,
        source="visitsanjose",
        calendar_name=_text(safe_str(item.get("field_event_organization")))
        or "Visit San Jose",
        venue=venue,
        price_min=0.0 if free else None, price_max=0.0 if free else None,
        is_free=free,
        # "Music: Latin" -> "Music", "Latin": the classifier keys on "music".
        genres=tuple(dict.fromkeys(
            part.strip() for c in categories for part in c.split(":"))),
        region_hint="south-bay",
    )


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    raw = http_get(LISTINGS_URL, log)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("visitsanjose: listings are not JSON")
        return []
    today = datetime.now(tz).date()
    candidates = select_listings(
        payload, today, int(config.get("lookahead_days", 30)))
    candidates.sort(key=lambda i: i["_date"])

    out: list[Event] = []
    untimed = 0
    for item in candidates[:MAX_DETAIL_FETCHES]:
        link = safe_str(item.get("link"))
        page = ""
        if link.startswith("/"):
            got = http_get(BASE + link, log)
            page = got.decode("utf-8", "replace") if got else ""
        when = detail_time(page) or description_time(
            _text(safe_str(item.get("field_event_description"))))
        if when is None:
            untimed += 1
            continue
        street = _STREET_RE.search(page)
        out.append(make_event(item, when, tz,
                              street=street.group(1) if street else ""))
    log.info("  visitsanjose: %d events (%d listings, %d with no time, "
             "dropped)", len(out), len(candidates), untimed)
    return out
