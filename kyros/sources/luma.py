"""Luma discover — AI events.

Moved from the original single-file run.py, unchanged in behavior: scrape
the server-rendered discover HTML (works from any IP) and paginate the
JSON discover API (richer, but silently empty-responds from cloud IPs, so
it falls back through CORS relays).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..http import PROXIES, http_get, proxy_wrap, redact
from ..model import Event, default_end, parse_iso, safe_str

NAME = "luma"

DISCOVER_URL = "https://api.lu.ma/discover/get-paginated-events"
DISCOVER_PAGE_LIMIT = 50
DISCOVER_MAX_PAGES = 20  # safety cap: 1000 events per source

# Map our city slugs -> Luma's HTML place slugs. Slugs not in the map
# fall through to the global discover/category page.
CITY_HTML_SLUG = {
    "san-francisco": "sf",
    "san-jose": "san-jose",
    "oakland": "oakland",
    "palo-alto": "palo-alto",
    "new-york": "nyc",
    "los-angeles": "la",
}
HTML_DISCOVER_GLOBAL = "https://lu.ma/discover/category/{}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

_LUMA_HEADERS = {"Origin": "https://lu.ma", "Referer": "https://lu.ma/discover"}

# The CORS relays are free services and are frequently down wholesale
# (520/522/500 across every call). Retrying them per city burned 2.5 of a
# 3-minute run for nothing, so once a relay has failed this many times it
# is dropped for the rest of the run.
_PROXY_FAILURE_LIMIT = 2
_proxy_failures: dict[int, int] = {}


def _proxy_usable(idx: int) -> bool:
    return _proxy_failures.get(idx, 0) < _PROXY_FAILURE_LIMIT


def reset_proxy_state() -> None:
    """Test hook: forget which relays were written off."""
    _proxy_failures.clear()


def _get(url: str, log: logging.Logger) -> bytes | None:
    return http_get(url, log, headers=_LUMA_HEADERS)


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    """Every configured city, plus the global/virtual feed."""
    out: list[Event] = []
    lookahead = int(config.get("lookahead_days", 30))
    categories = config.get("luma_categories") or ["ai"]
    for city in config.get("cities", []):
        for cat in categories:
            h = fetch_discover_html(city, cat, log)
            j = fetch_discover(city, cat, lookahead, log)
            log.info("  luma %s/%s: html=%d json=%d", city, cat, len(h), len(j))
            out.extend(h)
            out.extend(j)
    if config.get("include_virtual_global"):
        for cat in categories:
            h = fetch_discover_html(None, cat, log)
            j = fetch_discover(None, cat, lookahead, log)
            log.info("  luma virtual/%s: html=%d json=%d", cat, len(h), len(j))
            out.extend(h)
            out.extend(j)
    return out


def fetch_discover(city: str | None, category: str, lookahead_days: int,
                   log: logging.Logger) -> list[Event]:
    """Cursor-paginated discover fetch. Stops at the lookahead horizon or
    when has_more is False. If the direct call comes back blocked-empty
    (Luma silently returns {"entries":[]} from datacenter IPs), falls back
    through CORS proxies."""
    horizon = datetime.now(timezone.utc) + timedelta(days=lookahead_days)
    source = f"luma/{city or 'virtual'}"

    def _run(via_proxy: int | None) -> list[Event]:
        out: list[Event] = []
        cursor: str | None = None
        for page in range(DISCOVER_MAX_PAGES):
            params = {
                "category": category, "period": "future",
                "pagination_limit": str(DISCOVER_PAGE_LIMIT),
            }
            if city:
                params["city_slug"] = city
            if cursor:
                params["pagination_cursor"] = cursor
            target = f"{DISCOVER_URL}?{urllib.parse.urlencode(params)}"
            url = proxy_wrap(target, via_proxy) if via_proxy is not None else target
            raw = _get(url, log)
            if raw is None:
                break
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("  luma page=%d proxy=%s: non-JSON (%d bytes)",
                            page, via_proxy, len(raw))
                break
            page_events = extract_discover_events(payload, source, log)
            has_more = bool(payload.get("has_more")) \
                if isinstance(payload, dict) else False
            next_cursor = (payload.get("next_cursor")
                           if isinstance(payload, dict) else None)
            out.extend(page_events)
            if page_events and page_events[-1].start > horizon:
                break
            if not has_more:
                break
            cursor = next_cursor
            if not cursor:
                break
        return out

    direct = _run(via_proxy=None)
    # When Luma blocks our IP it returns a tiny geo-personalized response
    # with has_more=False on page 0. A real first page returns ~50.
    BLOCK_FLOOR = 20
    if len(direct) >= BLOCK_FLOOR:
        return direct
    if direct:
        log.info("Direct discover for %s returned only %d — looks blocked,"
                 " trying proxies", source, len(direct))
    merged = list(direct)
    for idx in range(len(PROXIES)):
        if not _proxy_usable(idx):
            log.info("  luma proxy #%d written off for this run, skipping", idx)
            continue
        proxied = _run(via_proxy=idx)
        log.info("  luma proxy #%d for %s: %d events", idx, source, len(proxied))
        if not proxied:
            _proxy_failures[idx] = _proxy_failures.get(idx, 0) + 1
        merged.extend(proxied)
    return merged


def extract_discover_events(payload, source: str,
                            log: logging.Logger) -> list[Event]:
    """Defensive extractor: accept several plausible payload shapes."""
    candidates = []
    if isinstance(payload, dict):
        for key in ("entries", "events", "results", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                candidates = v
                break
    elif isinstance(payload, list):
        candidates = payload

    out: list[Event] = []
    for entry in candidates:
        try:
            ev = (entry.get("event")
                  if isinstance(entry, dict) and "event" in entry
                  else entry)
            if not isinstance(ev, dict):
                continue
            cal = entry.get("calendar") if isinstance(entry, dict) else None
            calendar_name = (safe_str(cal.get("name"))
                             if isinstance(cal, dict) else "")
            api_id = safe_str(ev.get("api_id") or ev.get("id"))
            title = safe_str(ev.get("name") or ev.get("title"))
            url = safe_str(ev.get("url"))
            if url and not url.startswith("http"):
                url = f"https://lu.ma/{url.lstrip('/')}"
            description = safe_str(
                ev.get("description") or ev.get("description_short"))
            start_str = safe_str(ev.get("start_at") or ev.get("starts_at"))
            end_str = safe_str(ev.get("end_at") or ev.get("ends_at"))
            if not start_str:
                continue
            start = parse_iso(start_str)
            end = parse_iso(end_str) if end_str else default_end(start)
            geo = ev.get("geo_address_info") or ev.get("geo") or {}
            location = venue = ""
            lat = lon = None
            if isinstance(geo, dict):
                location = safe_str(
                    geo.get("full_address") or geo.get("address")
                    or geo.get("city_state") or geo.get("city"))
                venue = safe_str(geo.get("place_name") or geo.get("name"))
                lat = _coord(geo.get("latitude"))
                lon = _coord(geo.get("longitude"))
            is_virtual = bool(ev.get("is_virtual") or ev.get("virtual")) \
                or not location
            out.append(Event(
                event_id=api_id or url, title=title, start=start, end=end,
                location=location, description=description, url=url,
                is_virtual=is_virtual, source=source,
                calendar_name=calendar_name, venue=venue, lat=lat, lon=lon,
            ))
        except Exception as e:  # noqa: BLE001
            log.debug("Skip malformed discover event in %s: %s", source, e)
    return out


def _coord(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_discover_html(city_slug: str | None, category: str,
                        log: logging.Logger) -> list[Event]:
    """Scrape Luma's server-rendered discover HTML for embedded events.
    Used because the JSON endpoint silently empty-responds from cloud IPs;
    the HTML page works from anywhere because it's a regular browser page."""
    if city_slug:
        slug = CITY_HTML_SLUG.get(city_slug, city_slug)
        url = f"https://lu.ma/{slug}?category={category}"
    else:
        url = HTML_DISCOVER_GLOBAL.format(category)
    raw = _get(url, log)
    if not raw:
        return []
    src = raw.decode("utf-8", "replace")
    return parse_next_data(src, f"luma-html/{city_slug or 'discover'}", log,
                           where=redact(url))


def parse_next_data(src: str, source: str, log: logging.Logger,
                    where: str = "") -> list[Event]:
    m = NEXT_DATA_RE.search(src)
    if not m:
        log.warning("No __NEXT_DATA__ in %s", where or source)
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("Malformed __NEXT_DATA__ in %s", where or source)
        return []
    pp = data.get("props", {}).get("pageProps", {})
    ini = pp.get("initialData", {}) or {}
    candidates: list = []
    if isinstance(ini, dict):
        d = ini.get("data") or {}
        if isinstance(d, dict):
            for k in ("featured_events", "events"):
                v = d.get(k)
                if isinstance(v, list):
                    candidates.extend(v)
        fp = ini.get("featured_place") or {}
        if isinstance(fp, dict):
            v = fp.get("events")
            if isinstance(v, list):
                candidates.extend(v)
    return extract_discover_events({"entries": candidates}, source, log)
