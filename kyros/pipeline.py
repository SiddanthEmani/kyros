"""The run pipeline: fetch -> enrich -> filter -> dedup -> rank -> write."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import classify as C
from . import geo, ics, rank, report
from .config import PROJECT_DIR, category_config, enabled_categories, \
    load_config, source_enabled
from .dedup import merge_duplicates
from .sources import SOURCES

LOGS_DIR = PROJECT_DIR / "logs"
LOG_RETENTION_DAYS = 90


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = LOGS_DIR / f"{today}.log"

    logger = logging.getLogger("kyros")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    fh = logging.FileHandler(log_path)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass
    return logger


def prune_old_logs() -> None:
    if not LOGS_DIR.exists():
        return
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    for p in LOGS_DIR.glob("*.log"):
        try:
            if datetime.strptime(p.stem, "%Y-%m-%d") < cutoff:
                p.unlink()
        except (ValueError, OSError):
            continue


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_all(config: dict, log: logging.Logger,
              offline: bool = False) -> tuple[list, dict[str, int]]:
    """Run every enabled source. A source that raises is logged and
    skipped — a dead site must not take down the whole refresh.

    Returns the events plus a per-source count. The count is what the PR
    check reports on: a source that silently starts returning nothing is
    the failure mode these parsers actually have.
    """
    if offline:
        from .sources import offline as offline_source
        log.info("Offline mode: reading committed fixtures")
        got = offline_source.fetch(config, log)
        return got, {"offline-fixtures": len(got)}
    events: list = []
    counts: dict[str, int] = {}
    for name, fetch in SOURCES.items():
        if not source_enabled(config, name):
            log.info("Source %s disabled in config", name)
            continue
        log.info("Fetching source: %s", name)
        try:
            got = fetch(config, log)
        except Exception as e:  # noqa: BLE001
            log.exception("Source %s failed: %s", name, e)
            counts[name] = -1          # -1 = raised, distinct from 0
            continue
        log.info("Source %s: %d raw events", name, len(got))
        counts[name] = len(got)
        events.extend(got)
    return events, counts


# ---------------------------------------------------------------------------
# Filter / rank
# ---------------------------------------------------------------------------

def _tz(config: dict):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(config.get("local_tz", "America/Los_Angeles")))
    except Exception:  # noqa: BLE001
        return None


def in_lookahead(event, days: int) -> bool:
    now = datetime.now(timezone.utc)
    return now <= event.start <= now + timedelta(days=days)


def fits_schedule(event, config: dict, tz) -> bool:
    """True if a working-hours person could actually attend. Weekends
    always pass; weekdays must start at/after the category's threshold
    (the loosest threshold among the event's categories wins)."""
    s = event.start.astimezone(tz) if tz else event.start.astimezone()
    if s.weekday() >= 5:
        return True
    hours = [int(category_config(config, c).get("min_weekday_hour_local", 17))
             for c in event.categories] or [17]
    return s.hour >= min(hours)


def enrich(events: list, config: dict) -> None:
    """Resolve geography and categories in place."""
    allowed = set(enabled_categories(config))
    for ev in events:
        geo.resolve(ev)
        ev.categories = C.classify(ev) & allowed


def filter_and_rank(events: list, config: dict,
                    log: logging.Logger) -> tuple[list, dict]:
    """Returns (selected, stats). stats carries the drop breakdown and the
    per-category eligible/kept counts for the run report."""
    """Apply lookahead, category, geo and schedule filters, dedup across
    sources, then rank and cap per category."""
    tz = _tz(config)
    drops = {"lookahead": 0, "uncategorized": 0, "geo": 0,
             "schedule": 0, "nokey": 0}
    kept: list = []

    enrich(events, config)
    for ev in events:
        if not in_lookahead(ev, int(config.get("lookahead_days", 30))):
            drops["lookahead"] += 1
            continue
        if not ev.categories:
            drops["uncategorized"] += 1
            continue
        if not geo.in_scope(ev, config):
            drops["geo"] += 1
            continue
        if not fits_schedule(ev, config, tz):
            drops["schedule"] += 1
            continue
        if not ev.dedup_key():
            drops["nokey"] += 1
            continue
        kept.append(ev)
    log.info("Drop breakdown: %s", drops)

    before_dedup = len(kept)
    kept = merge_duplicates(kept, tz=tz, log=log)

    stats: dict = {"drops": drops, "merged": before_dedup - len(kept),
                   "categories": {}}
    selected = apply_caps(kept, config, log, stats["categories"])
    selected.sort(key=lambda e: e.start)
    return selected, stats


def apply_caps(kept: list, config: dict, log: logging.Logger,
               stats: dict | None = None) -> list:
    """Per-category caps first (so every category gets its share), then
    the combined cap over the union."""
    chosen: list = []
    seen: set[int] = set()
    for cat in enabled_categories(config):
        cap = int(category_config(config, cat).get("cap", 0) or 0)
        pool = [e for e in kept if cat in e.categories]
        pool.sort(key=lambda e: (rank.category_score(e, cat, config),
                                 rank.soonness(e)), reverse=True)
        picked = pool[:cap] if cap > 0 else pool
        log.info("Category %-9s: %d eligible -> %d kept", cat, len(pool),
                 len(picked))
        if stats is not None:
            stats[cat] = {"eligible": len(pool), "kept": len(picked)}
        for e in picked:
            if id(e) not in seen:
                seen.add(id(e))
                chosen.append(e)

    combined_cap = int(config.get("combined_cap", 0) or 0)
    if combined_cap > 0 and len(chosen) > combined_cap:
        chosen.sort(key=lambda e: (rank.best_score(e, config),
                                   rank.soonness(e)), reverse=True)
        log.info("Combined cap: %d -> %d", len(chosen), combined_cap)
        chosen = chosen[:combined_cap]
    return chosen


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def explain(kept: list, config: dict, log: logging.Logger) -> None:
    """Print the ranked keep-list per category — the fast way to see why
    the feed looks the way it does after a source changes."""
    for cat in enabled_categories(config):
        rows = [e for e in kept if cat in e.categories]
        rows.sort(key=lambda e: rank.category_score(e, cat, config),
                  reverse=True)
        log.info("--- %s (%d) ---", cat, len(rows))
        for e in rows:
            log.info("  %6.2f %s %-46s %-14s %s",
                     rank.category_score(e, cat, config),
                     e.start.strftime("%m-%d %H:%M"), e.title[:46],
                     e.city or e.region or "?", e.source)


def run(ics_path: Path | None = None, dry_run: bool = False,
        show_explain: bool = False, config_path: Path | None = None,
        offline: bool = False, report_path: Path | None = None,
        require_events: int = 0) -> int:
    log = setup_logging()
    prune_old_logs()
    config = load_config(config_path)
    log.info("=== Kyros run start ===")
    log.info("Config: lookahead=%dd radius=%smi categories=%s combined_cap=%d",
             config["lookahead_days"],
             (config.get("center") or {}).get("radius_miles"),
             enabled_categories(config), int(config.get("combined_cap", 0)))

    events, source_counts = fetch_all(config, log, offline=offline)
    log.info("Fetched %d raw events from all sources", len(events))

    kept, stats = filter_and_rank(events, config, log)
    log.info("Selected %d events for the feed", len(kept))
    if show_explain:
        explain(kept, config, log)

    if report_path is not None:
        text = report.build(kept, len(events), source_counts, stats, config)
        # Append: $GITHUB_STEP_SUMMARY may already hold earlier output.
        with report_path.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        log.info("Wrote run report to %s", report_path)

    if require_events > 0 and len(kept) < require_events:
        log.error("Only %d events selected, required at least %d — "
                  "treating this as a broken pipeline.",
                  len(kept), require_events)
        return 1

    out = ics_path or (PROJECT_DIR / "events.ics")
    if dry_run:
        log.info("Dry run: not writing %s", out)
        return 0

    # Publish guard: never replace a good feed with a near-empty one. A
    # blocked IP or changed markup should show up as a red workflow, not
    # as a wiped calendar.
    floor = int(config.get("min_events_floor", 5) or 0)
    if len(kept) < floor and out.exists() and out.stat().st_size > 0:
        log.error("Only %d events (floor %d) and %s already has content — "
                  "keeping the existing feeds and failing instead.",
                  len(kept), floor, out)
        return 1

    counts = ics.write_all(kept, out, config, log)
    log.info("Wrote feeds: %s", counts)
    log.info("=== Run done: combined=%d ===", counts.get("combined", 0))
    return 0
