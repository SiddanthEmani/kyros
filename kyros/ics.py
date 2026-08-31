"""iCalendar output — one combined feed plus per-category feeds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import classify as C

# feed name -> (filename, calendar name, categories included)
FEEDS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "ai": ("feeds/ai.ics", "Kyros AI", (C.AI,)),
    "edm": ("feeds/edm.ics", "Kyros EDM", (C.EDM,)),
    "music": ("feeds/music.ics", "Kyros Music", (C.EDM, C.CONCERT)),
    "free": ("feeds/free.ics", "Kyros Free", (C.FREE,)),
}

CATEGORY_LABEL = {
    C.AI: "AI", C.EDM: "EDM", C.CONCERT: "Live",
    C.FREE: "Free", C.COMMUNITY: "Bay",
}
# Which label wins the title prefix in the combined feed.
_LABEL_ORDER = (C.EDM, C.CONCERT, C.AI, C.COMMUNITY, C.FREE)


def title_prefix(event) -> str:
    for cat in _LABEL_ORDER:
        if cat in event.categories:
            label = CATEGORY_LABEL[cat]
            if cat is not C.FREE and C.FREE in event.categories:
                label += "/Free"
            return f"[{label}] "
    return ""


def _price_line(event) -> str:
    if event.is_free or C.FREE in event.categories:
        return "Price: Free"
    if event.price_min is None:
        return ""
    if event.price_max is None or event.price_max == event.price_min:
        return f"Price: ${event.price_min:.0f}"
    return f"Price: ${event.price_min:.0f}-${event.price_max:.0f}"


def build_description(event) -> str:
    pieces: list[str] = []
    if event.url:
        pieces.append(event.url)
    if event.venue:
        pieces.append(f"Venue: {event.venue}")
    if event.location and event.location != event.venue:
        pieces.append(f"Location: {event.location}")
    if event.is_virtual:
        pieces.append("(Virtual event)")
    price = _price_line(event)
    if price:
        pieces.append(price)
    if event.genres:
        pieces.append(f"Genres: {', '.join(event.genres)}")
    if event.calendar_name:
        pieces.append(f"Host: {event.calendar_name}")
    if event.categories:
        pieces.append(f"Categories: {', '.join(sorted(event.categories))}")
    pieces.append(f"Source: {event.source}")
    if event.description:
        pieces.append("")
        pieces.append(event.description[:1500])
    return "\n".join(pieces)


def write_ics(events: list, path: Path, log: logging.Logger,
              calname: str = "Kyros Bay Area Events",
              caldesc: str = "",
              prefix_titles: bool = False) -> int:
    """Render events as an iCalendar 2.0 feed. Stateless: each run fully
    replaces the feed."""
    try:
        from icalendar import Calendar, Event as ICalEvent
    except ImportError:
        log.error("'icalendar' not installed. pip install icalendar")
        return 0

    cal = Calendar()
    cal.add("prodid", "-//kyros//bay-area-events//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calname)
    cal.add("x-wr-caldesc",
            caldesc or "Bay Area events curated by Kyros (San Jose first).")
    cal.add("x-published-ttl", "PT6H")

    for ev in events:
        item = ICalEvent()
        item.add("uid", (ev.event_id or ev.url or ev.title))
        summary = ev.title
        if prefix_titles:
            summary = f"{title_prefix(ev)}{ev.title}"
        item.add("summary", summary)
        item.add("dtstart", ev.start)
        item.add("dtend", ev.end)
        item.add("dtstamp", datetime.now(timezone.utc))
        if ev.url:
            item.add("url", ev.url)
        if ev.location:
            item.add("location", ev.location)
        if ev.categories:
            item.add("categories", sorted(ev.categories))
        desc = build_description(ev)
        if desc:
            item.add("description", desc)
        cal.add_component(item)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cal.to_ical())
    return len(events)


def write_all(kept: list, ics_path: Path, config: dict,
              log: logging.Logger) -> dict[str, int]:
    """Write the combined feed plus every per-category feed.

    Category feeds live beside the combined feed, so `--ics-path /tmp/x.ics`
    keeps a scratch run entirely out of the repository.
    """
    base_dir = ics_path.parent
    counts: dict[str, int] = {}
    counts["combined"] = write_ics(
        kept, ics_path, log,
        calname="Kyros Bay Area Events",
        prefix_titles=bool(config.get("prefix_titles", True)),
    )
    for name, (rel, calname, cats) in FEEDS.items():
        subset = [e for e in kept if e.categories & set(cats)]
        counts[name] = write_ics(
            subset, base_dir / rel, log,
            calname=calname,
            caldesc=f"{calname} — {', '.join(cats)} events, San Jose first.",
        )
    return counts
