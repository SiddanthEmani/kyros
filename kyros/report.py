"""Markdown run report — what the PR check publishes.

The parsers scrape hand-maintained pages, so their real failure mode is
not an exception, it is a source that quietly starts returning nothing.
The report puts per-source counts somewhere a reviewer (or an agent
reading the workflow log) sees them without digging.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import rank


def _source_table(counts: dict[str, int]) -> list[str]:
    rows = ["| source | events fetched |", "|---|---|"]
    for name, n in sorted(counts.items()):
        if n < 0:
            rows.append(f"| `{name}` | **raised an exception** |")
        elif n == 0:
            rows.append(f"| `{name}` | **0** |")
        else:
            rows.append(f"| `{name}` | {n} |")
    return rows


def _category_table(categories: dict) -> list[str]:
    if not categories:
        return []
    rows = ["| category | eligible | kept |", "|---|---|---|"]
    for cat, info in categories.items():
        rows.append(f"| {cat} | {info['eligible']} | {info['kept']} |")
    return rows


def _sample(selected: list, config: dict, limit: int = 12) -> list[str]:
    if not selected:
        return []
    rows = ["| when | event | where | categories | source |",
            "|---|---|---|---|---|"]
    ordered = sorted(selected, key=lambda e: rank.best_score(e, config),
                     reverse=True)[:limit]
    for e in ordered:
        title = e.title.replace("|", "\\|")[:52]
        rows.append(
            f"| {e.start:%a %m-%d %H:%M} | {title} | "
            f"{e.city or e.region or '?'} | "
            f"{', '.join(sorted(e.categories))} | `{e.source}` |")
    return rows


def build(selected: list, raw_count: int, source_counts: dict[str, int],
          stats: dict, config: dict) -> str:
    """Render the run as markdown suitable for $GITHUB_STEP_SUMMARY."""
    dead = [n for n, c in source_counts.items() if c <= 0]
    lines = [
        "## kyros pipeline check",
        "",
        f"**{len(selected)} events selected** from {raw_count} fetched "
        f"across {len(source_counts)} source(s) — "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "",
    ]
    if dead:
        lines += [f"> ⚠️ no events from: {', '.join(f'`{d}`' for d in dead)}",
                  ""]
    lines += _source_table(source_counts) + [""]

    drops = stats.get("drops") or {}
    if drops:
        lines += ["**Dropped:** " + ", ".join(
            f"{k} {v}" for k, v in drops.items() if v)
            + f" · merged {stats.get('merged', 0)} duplicates", ""]

    by_source = stats.get("drops_by_source") or {}
    if by_source:
        lines += ["**Where each source's events were dropped**", "",
                  "| source | " + " | ".join(
                      ("lookahead", "uncategorized", "geo", "schedule"))
                  + " |", "|---|---|---|---|---|"]
        for src, reasons in sorted(by_source.items()):
            lines.append(f"| `{src}` | " + " | ".join(
                str(reasons.get(k, 0)) for k in
                ("lookahead", "uncategorized", "geo", "schedule")) + " |")
        lines.append("")

    cats = _category_table(stats.get("categories") or {})
    if cats:
        lines += cats + [""]

    sample = _sample(selected, config)
    if sample:
        lines += ["<details><summary>Top ranked picks</summary>", ""]
        lines += sample
        lines += ["", "</details>", ""]
    return "\n".join(lines)
