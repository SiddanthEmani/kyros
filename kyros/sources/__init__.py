"""Source registry.

Every source module exposes `fetch(config, log) -> list[Event]` and is
called inside a try/except by the pipeline, so one broken site can't take
down a refresh.
"""

from __future__ import annotations

from . import funcheap, luma, ticketmaster

SOURCES = {
    luma.NAME: luma.fetch,
    ticketmaster.NAME: ticketmaster.fetch,
    funcheap.NAME: funcheap.fetch,
}

__all__ = ["SOURCES", "luma", "ticketmaster", "funcheap"]
