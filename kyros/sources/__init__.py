"""Source registry.

Every source module exposes `fetch(config, log) -> list[Event]` and is
called inside a try/except by the pipeline, so one broken site can't take
down a refresh.
"""

from __future__ import annotations

from . import cerebralvalley, dothebay, funcheap, luma, stanford, visitsanjose

SOURCES = {
    luma.NAME: luma.fetch,
    cerebralvalley.NAME: cerebralvalley.fetch,
    visitsanjose.NAME: visitsanjose.fetch,
    dothebay.NAME: dothebay.fetch,
    stanford.NAME: stanford.fetch,
    funcheap.NAME: funcheap.fetch,
}

__all__ = ["SOURCES", "luma", "cerebralvalley", "visitsanjose", "dothebay",
           "stanford", "funcheap"]
