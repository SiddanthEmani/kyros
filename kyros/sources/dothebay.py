"""DoTheBay — editor-curated Bay Area listings across every category.

A DoStuff Media site. Every listing page has a `.json` twin that returns
the same events the HTML renders, with venue coordinates, a free flag and
a ticket line ("$36.05, 18+"). Day pages are sorted by popularity, so the
first page or two of each day is the part worth keeping.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from ..http import http_get
from ..model import Event, default_end, parse_iso, safe_str

NAME = "dothebay"

BASE = "https://dothebay.com"
DAY_URL = BASE + "/events/{d.year}/{d.month}/{d.day}.json?page={page}"
PAGES_PER_DAY = 2

# DoTheBay carries no genre data, and club nights are listed as nothing
# more than "21+". These rooms book electronic music almost exclusively.
CLUB_VENUES = (
    "public works", "audio sf", "audio nightclub", "monarch", "the midway",
    "1015 folsom", "the great northern", "halcyon", "temple nightclub",
    "the endup", "underground sf", "f8", "the stud", "raven bar",
    "phonobar", "the crib",
)
_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{2})?)")
_FREE_RE = re.compile(r"\bfree\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _price(e: dict) -> tuple[float | None, float | None, bool]:
    info = safe_str(e.get("ticket_info"))
    amounts = [float(a) for a in _PRICE_RE.findall(info)]
    free = bool(e.get("is_free")) or bool(_FREE_RE.search(info))
    if free and not amounts:
        return 0.0, 0.0, True
    if amounts:
        return min(amounts), max(amounts), False
    return None, None, False


def _start_end(e: dict) -> tuple[datetime, datetime] | None:
    # `begin_time` carries the venue's wall clock with a wrong -05:00
    # offset; the tz-adjusted fields are the ones that agree with the page.
    raw = safe_str(e.get("tz_adjusted_begin_date")) or safe_str(
        e.get("begin_time"))
    if not raw:
        return None
    try:
        start = parse_iso(raw)
    except ValueError:
        return None
    end = None
    if e.get("tz_adjusted_end_date"):
        try:
            end = parse_iso(e["tz_adjusted_end_date"])
        except ValueError:
            end = None
    # Multi-week runs report the run's last night as the end.
    if end is None or end <= start or end - start > timedelta(hours=12):
        end = default_end(start)
    return start, end


def parse_payload(payload, log: logging.Logger) -> list[Event]:
    out: list[Event] = []
    if not isinstance(payload, dict):
        return out
    for e in payload.get("events") or []:
        if not isinstance(e, dict) or e.get("past"):
            continue
        when = _start_end(e)
        if when is None:
            continue
        start, end = when
        venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        venue_name = safe_str(venue.get("title"))
        city = safe_str(venue.get("city"))
        location = safe_str(venue.get("full_address")) or ", ".join(
            p for p in (venue_name, city) if p)
        try:
            lat = float(venue["latitude"])
            lon = float(venue["longitude"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        genres = [safe_str(e.get("category"))]
        if any(v in venue_name.lower() for v in CLUB_VENUES):
            genres.append("Electronic")
        price_min, price_max, free = _price(e)
        permalink = safe_str(e.get("permalink"))
        description = safe_str(e.get("excerpt")) or re.sub(
            r"\s+", " ", _TAG_RE.sub(" ", safe_str(e.get("description"))))
        out.append(Event(
            event_id=f"dothebay-{e.get('id')}",
            title=safe_str(e.get("title")),
            start=start, end=end,
            location=location, description=description[:1200],
            url=BASE + permalink if permalink.startswith("/") else permalink,
            source="dothebay",
            calendar_name=safe_str(e.get("presented_by")) or "DoTheBay",
            venue=venue_name, lat=lat, lon=lon,
            price_min=price_min, price_max=price_max, is_free=free,
            genres=tuple(genres),
        ))
    return out


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    days = max(1, int(config.get("lookahead_days", 30)))
    pages = max(1, int(config.get("dothebay_pages_per_day", PAGES_PER_DAY)))
    today = datetime.now(tz).date()

    out: list[Event] = []
    seen: set[str] = set()
    failures = 0
    for offset in range(days):
        day = today + timedelta(days=offset)
        for page in range(1, pages + 1):
            raw = http_get(DAY_URL.format(d=day, page=page), log)
            if not raw:
                failures += 1
                break
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                failures += 1
                break
            for ev in parse_payload(payload, log):
                # Multi-day runs repeat on every day page they span.
                if ev.event_id not in seen:
                    seen.add(ev.event_id)
                    out.append(ev)
            paging = payload.get("paging") or {}
            if page >= int(paging.get("total_pages") or 1):
                break
        if failures >= 3 and not out:
            log.warning("  dothebay: %d failed fetches, giving up", failures)
            break
    log.info("  dothebay: %d events over %d day(s)", len(out), days)
    return out
