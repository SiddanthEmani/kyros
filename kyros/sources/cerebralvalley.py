"""Cerebral Valley — curated AI events and hackathons, worldwide.

The events page is a client of a public JSON API (`/v1/public/event/pull`)
that pages by offset, sorted by start time. The list is global, so
only California listings are kept and the geo filter takes it from
there; paging stops once events pass the lookahead window.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..http import http_get
from ..model import Event, default_end, safe_str

NAME = "cerebralvalley"

API_URL = "https://api.cerebralvalley.ai/v1/public/event/pull"
PAGE_SIZE = 100
MAX_PAGES = 30

_NONE = {"", "none", "null", "other", "$undefined"}
# The list is global and the city registry matches bare names, so "Dublin 8,
# Ireland" would pass as Dublin, CA. Only California locations go through.
_CALIFORNIA_RE = re.compile(r",\s*(?:CA|California)\b", re.IGNORECASE)


def _clean(v) -> str:
    s = safe_str(v).strip()
    return "" if s.lower() in _NONE else s


def _utc(raw: str) -> datetime | None:
    """The API returns naive UTC ("2026-09-28 19:00:00"); the site forces
    UTC on every one of them before converting."""
    raw = _clean(raw)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_payload(payload, log: logging.Logger) -> list[Event]:
    out: list[Event] = []
    if not isinstance(payload, dict):
        return out
    for e in payload.get("events") or []:
        if not isinstance(e, dict):
            continue
        start = _utc(e.get("startDateTime"))
        if start is None:
            continue
        end = _utc(e.get("endDateTime"))
        if end is None or end <= start or end - start > timedelta(days=3):
            end = default_end(start)
        location = _clean(e.get("location"))
        venue = _clean(e.get("venue"))
        if not _CALIFORNIA_RE.search(f"{venue}, {location}"):
            continue
        kind = _clean(e.get("type")).title()
        out.append(Event(
            event_id=f"cerebralvalley-{e.get('id')}",
            title=safe_str(e.get("name")),
            start=start, end=end,
            location=", ".join(p for p in (venue, location) if p),
            description=(_clean(e.get("descriptionSummary"))
                         or _clean(e.get("description")))[:1200],
            url=_clean(e.get("url")),
            source="cerebralvalley",
            # Not "... AI": the list carries some plain startup events, and
            # the AI bucket should still need AI vocabulary in the title.
            calendar_name="Cerebral Valley",
            venue=venue,
            genres=(kind,) if kind else (),
        ))
    return out


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=int(config.get("lookahead_days", 30)))
    out: list[Event] = []
    offset = 0
    for _page in range(MAX_PAGES):
        query = urllib.parse.urlencode({
            "approved": "true", "limit": PAGE_SIZE, "offset": offset,
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        })
        raw = http_get(f"{API_URL}?{query}", log)
        if not raw:
            break
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("cerebralvalley: offset %d is not JSON", offset)
            break
        got = parse_payload(payload, log)
        out.extend(got)
        batch = len(payload.get("events") or [])
        offset += batch
        total = int(payload.get("totalCount") or 0)
        if not batch or offset >= total:
            break
        if got and max(e.start for e in got) > horizon:
            break
    kept = [e for e in out if e.start <= horizon]
    log.info("  cerebralvalley: %d events in the window (%d fetched)",
             len(kept), len(out))
    return kept
