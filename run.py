#!/usr/bin/env python3
"""kyros — Bay Area event feed refresh job.

Fetches events from Luma (AI), Ticketmaster (concerts), 19hz (electronic)
and Funcheap (free/cheap), classifies and ranks them with San Jose
weighted first, and writes a combined iCalendar feed plus per-category
feeds.

Run: `python run.py [--ics-path events.ics] [--dry-run] [--explain]`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from kyros.pipeline import run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kyros — Bay Area events iCalendar feed builder")
    parser.add_argument("--ics-path", default=None,
                        help="Combined feed output path (default: events.ics)")
    parser.add_argument("--config", default=None,
                        help="Config file path (default: config.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch, filter and rank but write nothing")
    parser.add_argument("--explain", action="store_true",
                        help="Log the ranked keep-list per category")
    parser.add_argument("--offline", action="store_true",
                        help="Read committed fixtures instead of the network")
    parser.add_argument("--report", default=None, metavar="PATH",
                        help="Append a markdown run report to PATH "
                             "(e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--require-events", type=int, default=0,
                        metavar="N",
                        help="Exit non-zero if fewer than N events are "
                             "selected. Use in CI to catch a dead parser")
    args = parser.parse_args()
    try:
        return run(
            ics_path=Path(args.ics_path) if args.ics_path else None,
            dry_run=args.dry_run,
            show_explain=args.explain,
            offline=args.offline,
            report_path=Path(args.report) if args.report else None,
            require_events=args.require_events,
            config_path=Path(args.config) if args.config else None,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        try:
            logging.getLogger("kyros").exception("Unhandled: %s", e)
        except Exception:  # noqa: BLE001
            print(f"FATAL: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
