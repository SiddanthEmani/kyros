"""Stanford Events — talks, performances and exhibitions on campus.

Localist's public read-only API, no key. Most of the calendar is internal
(PhD defenses, benefits sessions, grand rounds), so only events tagged for
the public audience and of a public-facing type are kept. AI talks come
through here from HAI, CS and the engineering departments.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from ..geo import SJ_LAT, SJ_LON, haversine_miles
from ..http import http_get
from ..model import Event, default_end, parse_iso, safe_str

NAME = "stanford"

API_URL = "https://events.stanford.edu/api/2/events"
PAGE_SIZE = 100
MAX_PAGES = 12

# Audience tags that mean "you can walk in". Everything else (Students,
# Faculty, Staff, ...) is an internal event even when it's on the calendar.
PUBLIC_AUDIENCES = {"everyone", "general public"}
SKIP_TYPES = {
    "academic dates", "student billing dates", "phd defense", "meeting",
    "support space", "religious/spiritual",
}
_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{2})?)")
_FREE_RE = re.compile(r"^\s*free\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _names(filters: dict, key: str) -> list[str]:
    return [safe_str(f.get("name")) for f in (filters.get(key) or [])
            if isinstance(f, dict)]


def _is_public(e: dict) -> bool:
    filters = e.get("filters") or {}
    audiences = {a.lower() for a in _names(filters, "event_audience")}
    if not audiences & PUBLIC_AUDIENCES:
        return False
    types = {t.lower() for t in _names(filters, "event_types")}
    return not types & SKIP_TYPES


def _cost(e: dict) -> tuple[float | None, float | None, bool]:
    text = safe_str(e.get("ticket_cost"))
    if e.get("free") or _FREE_RE.match(text):
        # "Free to Current Students" still says free for the public
        # audience we already filtered to.
        return 0.0, 0.0, True
    amounts = [float(a) for a in _PRICE_RE.findall(text)]
    if amounts:
        return min(amounts), max(amounts), False
    return None, None, False


def _coords(e: dict) -> tuple[float | None, float | None]:
    geo = e.get("geo") or {}
    try:
        lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
    except (TypeError, ValueError):
        return None, None
    # Localist geocodes free-text venue names; "Central Energy Facility"
    # once landed in Australia. Anything off-campus-scale is ignored.
    if haversine_miles(lat, lon, SJ_LAT, SJ_LON) > 75:
        return None, None
    return lat, lon


def parse_payload(payload, log: logging.Logger) -> list[Event]:
    out: list[Event] = []
    if not isinstance(payload, dict):
        return out
    for wrapper in payload.get("events") or []:
        e = (wrapper or {}).get("event") if isinstance(wrapper, dict) else None
        if not isinstance(e, dict) or not _is_public(e):
            continue
        if e.get("experience") == "virtual":
            continue
        filters = e.get("filters") or {}
        # Localist's "Tour" is a campus or museum walk, not a concert tour.
        genres = tuple(("Guided Tour" if g == "Tour" else g)
                       for g in _names(filters, "event_types")
                       + _names(filters, "event_subject"))
        departments = [safe_str(d.get("name"))
                       for d in (e.get("departments") or [])
                       if isinstance(d, dict)]
        venue = safe_str(e.get("location_name")).strip()
        city = safe_str((e.get("geo") or {}).get("city")) or "Stanford"
        location = ", ".join(p for p in (venue, f"{city}, CA") if p)
        lat, lon = _coords(e)
        price_min, price_max, free = _cost(e)
        description = safe_str(e.get("description_text")) or re.sub(
            r"\s+", " ", _TAG_RE.sub(" ", safe_str(e.get("description"))))

        for inst_wrapper in e.get("event_instances") or []:
            inst = (inst_wrapper or {}).get("event_instance") or {}
            if inst.get("all_day") or not inst.get("start"):
                # All-day rows are exhibitions and deadlines; a feed entry
                # at midnight would mislead.
                continue
            try:
                start = parse_iso(inst["start"])
                end = (parse_iso(inst["end"]) if inst.get("end")
                       else default_end(start))
            except (TypeError, ValueError):
                continue
            out.append(Event(
                event_id=f"stanford-{inst.get('id') or e.get('id')}",
                title=safe_str(e.get("title")),
                start=start, end=end,
                location=location, description=description[:1200],
                url=safe_str(e.get("localist_url")),
                is_virtual=False, source="stanford",
                calendar_name=departments[0] if departments else "Stanford",
                venue=venue, lat=lat, lon=lon,
                price_min=price_min, price_max=price_max, is_free=free,
                genres=genres, region_hint="peninsula",
            ))
    return out


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    days = max(1, min(int(config.get("lookahead_days", 30)), 365))
    out: list[Event] = []
    page = 1
    while page <= MAX_PAGES:
        query = urllib.parse.urlencode(
            {"days": days, "pp": PAGE_SIZE, "page": page})
        raw = http_get(f"{API_URL}?{query}", log)
        if not raw:
            break
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("stanford: page %d is not JSON", page)
            break
        out.extend(parse_payload(payload, log))
        total = int(((payload.get("page") or {}).get("total")) or 1)
        if page >= total:
            break
        page += 1
    log.info("  stanford: %d public events over %d page(s)", len(out), page)
    return out
