"""Ticketmaster Discovery API — concerts and ticketed shows.

The only source with real coverage of SAP Center, Shoreline, The Ritz,
Fox Oakland and Chase Center. Needs a free API key (5,000 calls/day) in
the TICKETMASTER_API_KEY environment variable; without one this source
logs and returns [] rather than failing the run.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..geo import geohash
from ..http import http_get
from ..model import Event, default_end, parse_iso, safe_str

NAME = "ticketmaster"

API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
# Discovery refuses deep paging past 1,000 items (size * page < 1000).
MAX_PAGES = 5
ENV_KEY = "TICKETMASTER_API_KEY"


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        log.info("  ticketmaster: no %s set, skipping", ENV_KEY)
        return []

    center = config.get("center") or {}
    lat = float(center.get("lat", 37.3382))
    lon = float(center.get("lon", -121.8863))
    radius = int(center.get("radius_miles", 50) or 50)
    lookahead = int(config.get("lookahead_days", 30))
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=lookahead)

    out: list[Event] = []
    for classification in config.get("ticketmaster_classifications",
                                     ["music"]):
        out.extend(_fetch_classification(
            key, classification, geohash(lat, lon, 6), radius,
            now, horizon, log))
    return out


def _fetch_classification(key: str, classification: str, geo_point: str,
                          radius: int, start: datetime, end: datetime,
                          log: logging.Logger) -> list[Event]:
    out: list[Event] = []
    for page in range(MAX_PAGES):
        params = {
            "apikey": key,
            "geoPoint": geo_point,
            "radius": str(radius),
            "unit": "miles",
            "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "size": str(PAGE_SIZE),
            "page": str(page),
            "sort": "date,asc",
        }
        if classification:
            params["classificationName"] = classification
        raw = http_get(f"{API_URL}?{urllib.parse.urlencode(params)}", log)
        if raw is None:
            break
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("  ticketmaster: non-JSON response (%d bytes)",
                        len(raw))
            break
        events = parse_payload(payload, f"ticketmaster/{classification}", log)
        out.extend(events)
        info = payload.get("page") or {}
        total_pages = int(info.get("totalPages") or 0)
        log.info("  ticketmaster %s page=%d: %d events (of %s pages)",
                 classification, page, len(events), total_pages or "?")
        if not events or page + 1 >= total_pages:
            break
    return out


def parse_payload(payload, source: str, log: logging.Logger) -> list[Event]:
    embedded = payload.get("_embedded") if isinstance(payload, dict) else None
    entries = (embedded or {}).get("events") if isinstance(embedded, dict) else None
    if not isinstance(entries, list):
        return []

    out: list[Event] = []
    for ev in entries:
        try:
            if not isinstance(ev, dict):
                continue
            start_info = (ev.get("dates") or {}).get("start") or {}
            start_str = safe_str(start_info.get("dateTime"))
            if not start_str:
                # Date-only listings (time TBA) would land at midnight and
                # get dropped by the schedule filter anyway.
                continue
            start = parse_iso(start_str)
            end_str = safe_str(((ev.get("dates") or {}).get("end") or {})
                               .get("dateTime"))
            end = parse_iso(end_str) if end_str else default_end(start)

            venue_name = city = location = ""
            lat = lon = None
            venues = ((ev.get("_embedded") or {}).get("venues")
                      if isinstance(ev.get("_embedded"), dict) else None)
            if isinstance(venues, list) and venues:
                v = venues[0] if isinstance(venues[0], dict) else {}
                venue_name = safe_str(v.get("name"))
                city = safe_str((v.get("city") or {}).get("name"))
                state = safe_str((v.get("state") or {}).get("stateCode"))
                addr = safe_str((v.get("address") or {}).get("line1"))
                location = ", ".join(p for p in (addr, city, state) if p)
                loc = v.get("location") or {}
                lat = _coord(loc.get("latitude"))
                lon = _coord(loc.get("longitude"))

            price_min = price_max = None
            free = False
            ranges = ev.get("priceRanges")
            if isinstance(ranges, list) and ranges:
                mins = [_coord(r.get("min")) for r in ranges
                        if isinstance(r, dict)]
                maxs = [_coord(r.get("max")) for r in ranges
                        if isinstance(r, dict)]
                mins = [m for m in mins if m is not None]
                maxs = [m for m in maxs if m is not None]
                price_min = min(mins) if mins else None
                price_max = max(maxs) if maxs else None
                free = price_min == 0 and (price_max or 0) == 0

            genres = _genres(ev)
            description = " ".join(p for p in (safe_str(ev.get("info")),
                                               safe_str(ev.get("pleaseNote")))
                                   if p)

            out.append(Event(
                event_id=safe_str(ev.get("id")),
                title=safe_str(ev.get("name")),
                start=start, end=end,
                location=location or city,
                description=description,
                url=safe_str(ev.get("url")),
                is_virtual=False, source=source,
                calendar_name=_promoter(ev),
                venue=venue_name, lat=lat, lon=lon,
                price_min=price_min, price_max=price_max, is_free=free,
                genres=genres,
            ))
        except Exception as e:  # noqa: BLE001
            log.debug("Skip malformed ticketmaster event: %s", e)
    return out


def _genres(ev: dict) -> tuple[str, ...]:
    names: list[str] = []
    for cls in ev.get("classifications") or []:
        if not isinstance(cls, dict):
            continue
        for field in ("segment", "genre", "subGenre"):
            node = cls.get(field)
            if isinstance(node, dict):
                name = safe_str(node.get("name"))
                if name and name.lower() != "undefined":
                    names.append(name)
    return tuple(dict.fromkeys(names))


def _promoter(ev: dict) -> str:
    p = ev.get("promoter")
    if isinstance(p, dict):
        return safe_str(p.get("name"))
    return ""


def _coord(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
