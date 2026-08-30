"""The Event record shared by every source, filter and writer."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


class Event:
    __slots__ = (
        "event_id", "title", "start", "end", "location", "description",
        "url", "is_virtual", "source", "calendar_name",
        # enrichment
        "categories", "city", "region", "lat", "lon", "venue",
        "price_min", "price_max", "is_free", "genres",
    )

    def __init__(self, event_id: str, title: str, start: datetime,
                 end: datetime, location: str = "", description: str = "",
                 url: str = "", is_virtual: bool = False, source: str = "",
                 calendar_name: str = "", venue: str = "",
                 lat: float | None = None, lon: float | None = None,
                 price_min: float | None = None,
                 price_max: float | None = None,
                 is_free: bool = False,
                 genres: tuple[str, ...] = ()):
        self.event_id = event_id or ""
        self.title = (title or "(untitled)").strip() or "(untitled)"
        self.start = start
        self.end = end
        self.location = (location or "").strip()
        self.description = (description or "").strip()
        self.url = (url or "").strip()
        self.is_virtual = bool(is_virtual)
        self.source = source
        self.calendar_name = (calendar_name or "").strip()
        self.venue = (venue or "").strip()
        self.lat = lat
        self.lon = lon
        self.price_min = price_min
        self.price_max = price_max
        self.is_free = bool(is_free)
        self.genres = tuple(g for g in genres if g)
        # Filled in later by geo.resolve() / classify.classify().
        self.categories: set[str] = set()
        self.city = ""
        self.region = ""

    # -- keys ------------------------------------------------------------
    def dedup_key(self) -> str:
        """Exact key: the canonical URL, else the source id."""
        return self.url or self.event_id

    def fuzzy_key(self, tz=None) -> str:
        """Cross-source key: normalized title + local start date + city.

        The same show reaches us from Ticketmaster, 19hz and Funcheap with
        different ids and slightly different titles, so exact keys alone
        leave duplicates in the feed.
        """
        title = re.sub(r"[^a-z0-9]+", "", self.title.lower())[:24]
        start = self.start.astimezone(tz) if tz else self.start
        return f"{title}|{start:%Y-%m-%d}|{self.city or self.location[:12].lower()}"

    # -- merging ---------------------------------------------------------
    def merge_from(self, other: "Event") -> None:
        """Absorb detail from a duplicate, preferring whichever record
        actually has the field. Categories and genres union."""
        self.categories |= other.categories
        self.genres = tuple(dict.fromkeys(self.genres + other.genres))
        self.is_free = self.is_free or other.is_free
        for field in ("location", "description", "url", "venue",
                      "calendar_name", "city", "region"):
            if not getattr(self, field) and getattr(other, field):
                setattr(self, field, getattr(other, field))
        for field in ("lat", "lon", "price_min", "price_max"):
            if getattr(self, field) is None and getattr(other, field) is not None:
                setattr(self, field, getattr(other, field))
        if other.source and other.source not in self.source:
            self.source = f"{self.source}+{other.source}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<Event {self.start:%Y-%m-%d %H:%M} {self.title[:40]!r} "
                f"{sorted(self.categories)} {self.city}>")


def safe_str(v) -> str:
    return v if isinstance(v, str) else ""


def parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp, defaulting a naive value to UTC."""
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", s)
        if not m:
            raise
        dt = datetime.fromisoformat(m.group(1) + "+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def default_end(start: datetime) -> datetime:
    return start + timedelta(hours=2)
