"""SF Funcheap — free and cheap Bay Area events.

WordPress-backed, no key. Tries the WP REST API per region first and
falls back to the region RSS feeds. Funcheap writes dates in prose, so
date extraction is the fragile part: any item whose start can't be parsed
confidently is dropped and counted, never guessed.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ..http import http_get
from ..model import Event

NAME = "funcheap"

BASE = "https://sf.funcheap.com"
# South Bay first — it's the priority region and the thinnest coverage.
REGIONS = ("san-jose", "south-bay", "peninsula", "san-francisco", "east-bay")
# Feed slug -> the region its events are in, for items whose text names no
# city we know.
REGION_OF_FEED = {
    "san-jose": "south-bay", "south-bay": "south-bay",
    "peninsula": "peninsula", "san-francisco": "sf", "east-bay": "east-bay",
}
WP_POSTS = BASE + "/wp-json/wp/v2/posts?per_page=50&page=1&search={}"
REGION_RSS = BASE + "/region/{}/feed/"

_TAG_RE = re.compile(r"<[^>]+>")
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7,
    "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "September 5, 2026" / "Sept 5" / "Sep 5-7"
_DATE_RE = re.compile(
    rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})"
    rf"(?:\s*[-–]\s*\d{{1,2}})?(?:,?\s*(?P<year>20\d{{2}}))?\b",
    re.IGNORECASE)
_TIME_RE = re.compile(
    r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)", re.IGNORECASE)
_COST_RE = re.compile(r"cost\s*:?\s*([^\n|]{0,40})", re.IGNORECASE)
_WHERE_RE = re.compile(r"(?:where|venue|location)\s*:?\s*([^\n|]{0,80})",
                       re.IGNORECASE)
_FREE_RE = re.compile(r"\bfree\b|\bno cost\b|\$0\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{2})?)")


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", s or ""))).strip()


def _infer_year(month: int, day: int, today: datetime) -> int:
    year = today.year
    if month < today.month - 1:
        year += 1
    return year


def extract_datetime(text: str, tz, today: datetime | None = None
                     ) -> tuple[datetime, datetime] | None:
    """Pull a start/end from Funcheap's prose. Returns None when no date
    is stated — the caller drops those rather than guessing."""
    today = today or datetime.now(tz)
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS[m.group("month").lower()]
    day = int(m.group("day"))
    year = int(m.group("year")) if m.group("year") else _infer_year(
        month, day, today)

    times = _TIME_RE.findall(text[m.start():m.start() + 400]) \
        or _TIME_RE.findall(text[:400])
    hour, minute = (19, 0)
    if times:
        hour, minute = _to_24h(times[0])
    try:
        start = datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError:
        return None
    if len(times) > 1:
        eh, em = _to_24h(times[1])
        end = datetime(year, month, day, eh, em, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + timedelta(hours=2)
    return start, end


def _to_24h(match: tuple[str, str, str]) -> tuple[int, int]:
    h = int(match[0]) % 12
    minute = int(match[1]) if match[1] else 0
    if match[2].lower().startswith("p"):
        h += 12
    return h, minute


def extract_cost(text: str) -> tuple[float | None, float | None, bool]:
    m = _COST_RE.search(text)
    segment = m.group(1) if m else text[:200]
    amounts = [float(a) for a in _PRICE_RE.findall(segment)]
    free = bool(_FREE_RE.search(segment))
    if free and not amounts:
        return 0.0, 0.0, True
    if not amounts:
        return None, None, False
    lo, hi = min(amounts), max(amounts)
    if free:
        lo = 0.0
    return lo, hi, lo == 0.0 and hi == 0.0


def _make_event(title: str, link: str, body: str, region: str,
                tz, today: datetime | None) -> Event | None:
    text = strip_html(body)
    when = extract_datetime(f"{title} {text}", tz, today)
    if when is None:
        return None
    start, end = when
    price_min, price_max, free = extract_cost(text)
    where = _WHERE_RE.search(text)
    venue = where.group(1).strip() if where else ""
    location = venue or region.replace("-", " ")
    return Event(
        event_id=f"funcheap-{start:%Y%m%d}-"
                 f"{re.sub(r'[^a-z0-9]+', '', title.lower())[:24]}",
        title=re.sub(r"\s*\((?:free|\$[^)]*)\)\s*$", "", title).strip(),
        start=start, end=end,
        location=location, description=text[:1200], url=link,
        source=f"funcheap/{region}", venue=venue,
        price_min=price_min, price_max=price_max, is_free=free,
        region_hint=REGION_OF_FEED.get(region, ""),
        price_text_trusted=True,   # posts carry an explicit "Cost:" line
    )


def parse_wp_json(payload, region: str, log: logging.Logger, tz,
                  today: datetime | None = None) -> tuple[list[Event], int]:
    events: list[Event] = []
    skipped = 0
    if not isinstance(payload, list):
        return events, skipped
    for post in payload:
        if not isinstance(post, dict):
            continue
        title = strip_html((post.get("title") or {}).get("rendered", ""))
        body = ((post.get("content") or {}).get("rendered", "")
                or (post.get("excerpt") or {}).get("rendered", ""))
        link = post.get("link") or ""
        ev = _make_event(title, link, body, region, tz, today)
        if ev is None:
            skipped += 1
            continue
        events.append(ev)
    return events, skipped


def parse_rss(src: str, region: str, log: logging.Logger, tz,
              today: datetime | None = None) -> tuple[list[Event], int]:
    events: list[Event] = []
    skipped = 0
    try:
        root = ET.fromstring(src)
    except ET.ParseError as e:
        log.warning("funcheap %s: malformed RSS (%s)", region, e)
        return events, skipped
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        body = (item.findtext("content:encoded", default="", namespaces=ns)
                or item.findtext("description") or "")
        ev = _make_event(title, link, body, region, tz, today)
        if ev is None:
            skipped += 1
            continue
        events.append(ev)
    return events, skipped


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    except Exception:  # noqa: BLE001
        tz = None

    out: list[Event] = []
    total_skipped = 0
    for region in REGIONS:
        events: list[Event] = []
        skipped = 0
        raw = http_get(WP_POSTS.format(urllib.parse.quote(
            region.replace("-", " "))), log)
        if raw:
            try:
                events, skipped = parse_wp_json(
                    json.loads(raw), region, log, tz)
            except json.JSONDecodeError:
                events = []
        if not events:
            raw = http_get(REGION_RSS.format(region), log)
            if raw:
                events, skipped = parse_rss(
                    raw.decode("utf-8", "replace"), region, log, tz)
        log.info("  funcheap %s: %d events (%d undated, dropped)",
                 region, len(events), skipped)
        total_skipped += skipped
        out.extend(events)
    if total_skipped:
        log.info("  funcheap: dropped %d items with no parseable date",
                 total_skipped)
    return out
