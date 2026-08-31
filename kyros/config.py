"""Configuration loading.

Back-compatible with the flat single-file config: the old keys
(`cities`, `min_weekday_hour_local`, `max_events_per_run`) are still read
and mapped onto the category-aware shape.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.json"

DEFAULT_CONFIG: dict = {
    "lookahead_days": 30,
    # IANA timezone for schedule checks. Required because cloud runners
    # run in UTC; without this, "5 PM local" wrongly means UTC.
    "local_tz": "America/Los_Angeles",

    # Everything is measured from downtown San Jose.
    "center": {"lat": 37.3382, "lon": -121.8863, "radius_miles": 50},
    # Score bonus by region — this is what makes San Jose the priority
    # while keeping the rest of the Bay eligible.
    "region_boost": {
        "south-bay": 3.0, "peninsula": 1.5, "sf": 0.5,
        "east-bay": 0.5, "north-bay": 0.0, "bay-area": 1.0,
    },
    "free_bonus": 1.0,

    "sources": {
        "luma": True, "ticketmaster": True, "funcheap": True,
    },
    # Luma discover slugs / categories (AI events).
    "cities": ["san-francisco", "san-jose"],
    "luma_categories": ["ai"],
    "include_virtual_global": True,
    # Ticketmaster Discovery classifications to query.
    "ticketmaster_classifications": ["music"],

    "categories": {
        "ai":        {"enabled": True, "cap": 12, "min_weekday_hour_local": 17},
        "edm":       {"enabled": True, "cap": 15, "min_weekday_hour_local": 16},
        "concert":   {"enabled": True, "cap": 15, "min_weekday_hour_local": 16},
        "free":      {"enabled": True, "cap": 12, "min_weekday_hour_local": 17},
        "community": {"enabled": True, "cap": 8,  "min_weekday_hour_local": 17},
    },
    "combined_cap": 60,
    "prefix_titles": True,
    # Refuse to publish a near-empty feed over a good one.
    "min_events_floor": 5,
}

# old flat key -> where it lands now
_LEGACY_KEYS = ("cities", "include_virtual_global", "lookahead_days",
                "local_tz")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    p = path or CONFIG_PATH
    cfg = dict(DEFAULT_CONFIG)
    if not p.exists():
        return copy.deepcopy(cfg)
    try:
        user = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(cfg)
    if not isinstance(user, dict):
        return copy.deepcopy(cfg)

    merged = _deep_merge(cfg, {k: v for k, v in user.items()
                               if k in DEFAULT_CONFIG})

    # --- legacy shims ---------------------------------------------------
    if "min_weekday_hour_local" in user:
        hour = user["min_weekday_hour_local"]
        for c in merged["categories"].values():
            c["min_weekday_hour_local"] = hour
    if "max_events_per_run" in user:
        merged["combined_cap"] = user["max_events_per_run"]
    for k in _LEGACY_KEYS:
        if k in user:
            merged[k] = user[k]
    return merged


def category_config(config: dict, name: str) -> dict:
    return (config.get("categories") or {}).get(name, {})


def enabled_categories(config: dict) -> list[str]:
    cats = config.get("categories") or {}
    return [n for n, c in cats.items() if c.get("enabled", True)]


def source_enabled(config: dict, name: str) -> bool:
    return bool((config.get("sources") or {}).get(name, True))
