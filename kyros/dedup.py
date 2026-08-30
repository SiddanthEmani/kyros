"""Cross-source duplicate merging.

The same show reaches us from Ticketmaster, 19hz and Funcheap with
different ids and slightly different titles. Merging (rather than letting
one source arbitrarily win) is what keeps the price from Ticketmaster and
the genre tags from 19hz on the same event.
"""

from __future__ import annotations

import logging


def merge_duplicates(events: list, tz=None,
                     log: logging.Logger | None = None) -> list:
    """Collapse duplicates, preserving first-seen order.

    Two passes of keys: the exact key (URL or source id) catches re-fetches
    of the same listing; the fuzzy key (title prefix + local date + city)
    catches the same event described by two different sites.
    """
    out: list = []
    by_key: dict[str, object] = {}
    merged = 0
    for ev in events:
        keys = [k for k in (ev.dedup_key(), ev.fuzzy_key(tz)) if k]
        hit = next((by_key[k] for k in keys if k in by_key), None)
        if hit is not None:
            hit.merge_from(ev)
            merged += 1
            for k in keys:
                by_key.setdefault(k, hit)
            continue
        out.append(ev)
        for k in keys:
            by_key.setdefault(k, ev)
    if log and merged:
        log.info("Dedup: merged %d duplicate listings", merged)
    return out
