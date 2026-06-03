#!/usr/bin/env python3
"""Entry point for the Space Brief Agent.

Usage:
  python run.py                 # full run: ingest -> analyze -> email -> save state
  python run.py --dry-run       # build the brief, write markdown, no email / no state write
  python run.py --check-feeds   # validate every feed URL in the registry
  python run.py --since-days 14 # override the lookback window for this run
"""
from __future__ import annotations

import argparse
import logging
import sys

from src import ingest, pipeline
from src.config import Settings, load_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-9s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly U.S./China orbital-space intelligence brief.")
    ap.add_argument("--dry-run", action="store_true", help="No email, no state write.")
    ap.add_argument("--check-feeds", action="store_true", help="Validate feed URLs and exit.")
    ap.add_argument("--since-days", type=int, default=None, help="Override lookback window.")
    ap.add_argument("--config", default="config/sources.yaml")
    args = ap.parse_args()

    sources = load_sources(args.config)

    if args.check_feeds:
        ingest.check_feeds(sources)
        return 0

    settings = Settings.from_env()
    if args.since_days:
        settings.lookback_days = args.since_days

    try:
        out = pipeline.run(settings, sources, dry_run=args.dry_run)
        print(f"\nDone. Briefing written to: {out}")
        return 0
    except Exception as e:  # noqa: BLE001
        logging.getLogger("run").exception("Run failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
