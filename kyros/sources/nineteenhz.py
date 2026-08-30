"""19hz.info — the Bay Area electronic music listing.

A hand-maintained, server-rendered HTML table (no API, no key). Because
the markup is hand-maintained, columns are located by *header text*
rather than by position, so a reordered or added column degrades instead
of silently corrupting the feed.

Row shape (as published):
    Date/Time | Event Title @ Venue | Tags | Price | Age | Organizers | Links
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser

from ..http import http_get
from ..model import Event

NAME = "nineteenhz"

# What the last parse actually saw. The workflow log is only readable from
# the tail, so the layout is reported at the end of a run rather than where
# it is discovered — two failed fixes went in blind for want of this.
LAST_LAYOUT: dict = {}

URL = "https://19hz.info/eventlisting_BayArea.php"

# Header keyword -> logical column. First match wins per header cell.
# Order matters: the first hint found in a header cell wins, so the most
# specific phrasings come first. A generic "event" rule ahead of "tags"
# lets a header like "Event Tags" steal the title column, which is exactly
# how genre lists ended up as event titles in the feed.
_COLUMN_HINTS = (
    ("date/time", "date"),
    ("date", "date"),
    ("event title", "title"),
    ("title", "title"),
    ("venue", "title"),
    ("tags", "tags"),
    ("genre", "tags"),
    ("price", "price"),
    ("cost", "price"),
    ("age", "age"),
    ("organizer", "organizer"),
    ("promoter", "organizer"),
    ("link", "links"),
    ("event", "title"),
)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

_DATE_RE = re.compile(
    r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})", re.IGNORECASE)
_TIME_RE = re.compile(
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)", re.IGNORECASE)
# "$19-30" is a range: only the first number carries the dollar sign, so a
# per-number pattern silently reported the maximum as 19.
_PRICE_RE = re.compile(
    r"\$\s*(\d+(?:\.\d{2})?)(?:\s*[-–—]\s*\$?\s*(\d+(?:\.\d{2})?))?")
_FREE_RE = re.compile(r"\bfree\b|\bno cover\b", re.IGNORECASE)


class _TableParser(HTMLParser):
    """Collect every table row as a list of cell texts (plus the first
    href per cell, which is the event link)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.hrefs: list[list[str]] = []
        self._row: list[str] | None = None
        self._hrefs: list[str] | None = None
        self._cell: list[str] | None = None
        self._cell_href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row, self._hrefs = [], []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._cell_href = [], ""
        elif tag == "a" and self._cell is not None and not self._cell_href:
            for k, v in attrs:
                if k == "href" and v:
                    self._cell_href = v
                    break
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._hrefs.append(self._cell_href)
            self._cell, self._cell_href = None, ""
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
                self.hrefs.append(self._hrefs)
            self._row, self._hrefs = None, None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _column_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header):
        low = cell.lower()
        for hint, name in _COLUMN_HINTS:
            if hint in low and name not in mapping:
                mapping[name] = idx
                break
    return mapping


def _looks_like_header(row: list[str]) -> bool:
    low = " ".join(row).lower()
    return "date" in low and ("event" in low or "title" in low)


def _infer_year(month: int, day: int, today: datetime) -> int:
    """19hz omits the year. A month more than one behind today has rolled
    over into next year."""
    year = today.year
    if month < today.month - 1:
        year += 1
    elif month == today.month and day < today.day - 20:
        year += 1
    return year


def parse_datetime(cell: str, tz, today: datetime | None = None
                   ) -> tuple[datetime, datetime] | None:
    """Parse a 19hz date cell like 'Fri: Sep 05 (10pm-4am)'."""
    today = today or datetime.now(tz)
    m = _DATE_RE.search(cell)
    if not m:
        return None
    month = _MONTHS[m.group("month").lower()[:3]]
    day = int(m.group("day"))
    year = _infer_year(month, day, today)

    times = _TIME_RE.findall(cell)
    start_h, start_min = 21, 0  # club-night default when no time is given
    if times:
        start_h, start_min = _to_24h(times[0])
    try:
        start = datetime(year, month, day, start_h, start_min, tzinfo=tz)
    except ValueError:
        return None

    if len(times) > 1:
        end_h, end_min = _to_24h(times[1])
        end = datetime(year, month, day, end_h, end_min, tzinfo=tz)
        if end <= start:  # after-hours listing crossing midnight
            end += timedelta(days=1)
    else:
        end = start + timedelta(hours=4)
    return start, end


def _to_24h(match: tuple[str, str, str]) -> tuple[int, int]:
    h = int(match[0]) % 12
    minute = int(match[1]) if match[1] else 0
    if match[2].lower() == "pm":
        h += 12
    return h, minute


def parse_price(cell: str) -> tuple[float | None, float | None, bool]:
    """'Free', '$20', '$20-$30', 'Free b4 11pm/$15' -> (min, max, is_free)."""
    amounts = [float(a) for pair in _PRICE_RE.findall(cell or "")
               for a in pair if a]
    free = bool(_FREE_RE.search(cell or ""))
    if free and not amounts:
        return 0.0, 0.0, True
    if not amounts:
        return None, None, False
    lo, hi = min(amounts), max(amounts)
    if free:
        lo = 0.0
    return lo, hi, lo == 0.0 and hi == 0.0


def parse_html(src: str, log: logging.Logger, tz=None,
               today: datetime | None = None) -> list[Event]:
    parser = _TableParser()
    try:
        parser.feed(src)
    except Exception as e:  # noqa: BLE001
        log.warning("19hz: HTML parse failed: %s", e)
        return []

    out: list[Event] = []
    columns: dict[str, int] = {}
    skipped = 0
    for row, hrefs in zip(parser.rows, parser.hrefs):
        if _looks_like_header(row):
            columns = _column_map(row)
            LAST_LAYOUT.setdefault("headers", []).append(
                {"header": [c[:24] for c in row], "columns": dict(columns)})
            continue
        if not columns or len(row) < 2:
            continue
        offset = _row_offset(row, columns)
        if "sample_row" not in LAST_LAYOUT:
            LAST_LAYOUT["sample_row"] = [c[:24] for c in row]
            LAST_LAYOUT["sample_offset"] = offset
        date_cell = _cell(row, columns, "date", offset)
        title_cell = _cell(row, columns, "title", offset)
        if not date_cell or not title_cell:
            continue
        when = parse_datetime(date_cell, tz, today)
        if when is None:
            skipped += 1
            continue
        start, end = when

        title, _, venue = title_cell.partition(" @ ")
        tags = _cell(row, columns, "tags", offset)
        price_cell = _cell(row, columns, "price", offset)
        price_min, price_max, free = parse_price(price_cell)
        url = ""
        idx = columns.get("title")
        if idx is not None and 0 <= idx + offset < len(hrefs):
            url = hrefs[idx + offset]
        if not url:
            link_idx = columns.get("links")
            if link_idx is not None and 0 <= link_idx + offset < len(hrefs):
                url = hrefs[link_idx + offset]

        # Every row on this page is electronic music, whatever the title
        # says, so vouch for the genre rather than relying on the title
        # regex — most rows are just a promoter and an artist name.
        genres = tuple(t.strip() for t in re.split(r"[,/]", tags) if t.strip())
        if not any("electronic" in g.lower() for g in genres):
            genres += ("electronic",)
        details = [p for p in (venue.strip(), price_cell,
                               _cell(row, columns, "age", offset),
                               _cell(row, columns, "organizer", offset)) if p]
        out.append(Event(
            event_id=f"19hz-{start:%Y%m%d}-"
                     f"{re.sub(r'[^a-z0-9]+', '', title.lower())[:24]}",
            title=title.strip() or title_cell,
            start=start, end=end,
            location=venue.strip(),
            description=" | ".join(details),
            url=url,
            source="19hz",
            venue=venue.strip(),
            price_min=price_min, price_max=price_max, is_free=free,
            genres=genres,
            # The listing is Bay-Area-only, so a venue we cannot place is
            # still in the Bay; geo.OUT_OF_AREA excludes its Sacramento and
            # Tahoe rows. The price column is authoritative.
            region_hint="bay-area",
            price_text_trusted=True,
        ))
    if skipped:
        log.info("  19hz: skipped %d rows with unparseable dates", skipped)
    return out


def _row_offset(row: list[str], columns: dict[str, int]) -> int:
    """How far this row's cells sit from where the header said they would.

    Data rows on the live page carry a leading cell the header row does not,
    so header positions alone put the tags column where the title should be
    and shipped events titled "house, tech house, techno". The date is the
    one cell we can recognise by content, so it anchors the whole row.
    """
    want = columns.get("date")
    if want is None:
        return 0
    for idx, cell in enumerate(row):
        if _DATE_RE.search(cell):
            return idx - want
    return 0


def _cell(row: list[str], columns: dict[str, int], name: str,
          offset: int = 0) -> str:
    idx = columns.get(name)
    if idx is None:
        return ""
    idx += offset
    if idx < 0 or idx >= len(row):
        return ""
    return row[idx]


def fetch(config: dict, log: logging.Logger) -> list[Event]:
    LAST_LAYOUT.clear()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    except Exception:  # noqa: BLE001
        tz = None
    raw = http_get(URL, log)
    if not raw:
        return []
    events = parse_html(raw.decode("utf-8", "replace"), log, tz=tz)
    log.info("  19hz: %d events", len(events))
    return events
