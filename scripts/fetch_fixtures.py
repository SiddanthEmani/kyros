#!/usr/bin/env python3
"""Refresh the parser test fixtures from the live sites.

The parsers are pinned to committed fixtures so the test suite runs
offline. When a site changes its markup, run this from a machine with
network access, eyeball the diff, and commit the new fixtures together
with any parser change they force.

Usage: python scripts/fetch_fixtures.py [funcheap|ticketmaster|all]
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyros.geo import geohash  # noqa: E402
from kyros.http import http_get  # noqa: E402
from kyros.sources import funcheap, ticketmaster  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _log() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return logging.getLogger("fixtures")


def fetch_funcheap(log) -> None:
    raw = http_get(funcheap.REGION_RSS.format("san-jose"), log)
    if not raw:
        log.error("funcheap: fetch failed")
        return
    _write("funcheap_sanjose.live.xml", raw.decode("utf-8", "replace"), log)


def fetch_ticketmaster(log) -> None:
    key = os.environ.get(ticketmaster.ENV_KEY, "").strip()
    if not key:
        log.error("ticketmaster: set %s first", ticketmaster.ENV_KEY)
        return
    now = datetime.now(timezone.utc)
    params = {
        "apikey": key,
        "geoPoint": geohash(37.3382, -121.8863, 6),
        "radius": "50", "unit": "miles",
        "classificationName": "music",
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "size": "20", "page": "0", "sort": "date,asc",
    }
    raw = http_get(f"{ticketmaster.API_URL}?{urllib.parse.urlencode(params)}",
                   log)
    if not raw:
        log.error("ticketmaster: fetch failed")
        return
    # Re-dump so the committed fixture is readable and key-free.
    _write("ticketmaster_events.live.json",
           json.dumps(json.loads(raw), indent=2), log)


def _write(name: str, text: str, log) -> None:
    path = FIXTURES / name
    path.write_text(text)
    log.info("wrote %s (%d bytes) — review, then rename over the fixture "
             "it replaces", path, len(text))


TARGETS = {"funcheap": fetch_funcheap,
           "ticketmaster": fetch_ticketmaster}


def main() -> int:
    log = _log()
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    targets = TARGETS.values() if which == "all" else [TARGETS.get(which)]
    if not all(targets):
        log.error("unknown target %r; pick one of %s or 'all'",
                  which, ", ".join(TARGETS))
        return 2
    for fn in targets:
        fn(log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
