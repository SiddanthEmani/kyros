#!/usr/bin/env python3
"""Refresh the parser test fixtures from the live sites.

The parsers are pinned to committed fixtures so the test suite runs
offline. When a site changes its markup, run this from a machine with
network access, eyeball the diff, and commit the new fixtures together
with any parser change they force.

Usage: python scripts/fetch_fixtures.py [funcheap|stanford|dothebay|cerebralvalley|visitsanjose|all]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyros.http import http_get  # noqa: E402
from kyros.sources import (cerebralvalley, dothebay, funcheap,  # noqa: E402
                           stanford, visitsanjose)

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


def _fetch_to(url: str, name: str, log) -> None:
    raw = http_get(url, log)
    if not raw:
        log.error("%s: fetch failed", name)
        return
    _write(name, raw.decode("utf-8", "replace"), log)


def fetch_stanford(log) -> None:
    _fetch_to(f"{stanford.API_URL}?days=30&pp=100",
              "stanford_events.live.json", log)


def fetch_dothebay(log) -> None:
    _fetch_to(f"{dothebay.BASE}/events.json", "dothebay_day.live.json", log)


def fetch_cerebralvalley(log) -> None:
    _fetch_to(f"{cerebralvalley.API_URL}?approved=true&limit=100",
              "cerebralvalley_events.live.json", log)


def fetch_visitsanjose(log) -> None:
    _fetch_to(visitsanjose.LISTINGS_URL, "visitsanjose_listings.live.json",
              log)


def _write(name: str, text: str, log) -> None:
    path = FIXTURES / name
    path.write_text(text)
    log.info("wrote %s (%d bytes) — review, then rename over the fixture "
             "it replaces", path, len(text))


TARGETS = {"funcheap": fetch_funcheap,
           "stanford": fetch_stanford,
           "dothebay": fetch_dothebay,
           "cerebralvalley": fetch_cerebralvalley,
           "visitsanjose": fetch_visitsanjose}


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
