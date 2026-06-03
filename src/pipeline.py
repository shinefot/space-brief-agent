"""Pipeline orchestration: wires stages 1-7 together with logging."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from . import ingest, ingest_orbital, process, render, state
from .config import Settings, SourceConfig
from .deliver import send_email
from .llm import LLMClient

log = logging.getLogger("pipeline")


def run(settings: Settings, sources: SourceConfig, dry_run: bool = False) -> str:
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=settings.lookback_days)).date().isoformat()
    week_end = now.date().isoformat()
    llm = LLMClient(settings.anthropic_api_key)

    log.info("STAGE 1-2  Ingestion")
    raw = ingest.fetch_rss(sources, settings.lookback_days)
    launch = ingest.fetch_launches(settings, sources)

    log.info("STAGE 3    Dedup & cluster")
    seen = state.load_seen(settings.state_dir)
    clusters = process.dedup_and_cluster(raw, seen)

    log.info("STAGE 4    Relevance scoring")
    scored = process.score_clusters(clusters, llm, settings, sources)

    log.info("STAGE 5    Per-pillar analysis")
    pillars = process.analyze_pillars(scored, llm, settings, sources)

    log.info("STAGE 5b   Orbital tasking signal (RPO / maneuvers)")
    orbital_state = state.load_orbital(settings.state_dir)
    events = ingest_orbital.detect(settings, sources, orbital_state)
    orbital_items = process.analyze_orbital_events(events, llm, settings, sources)
    if orbital_items:
        pillars.setdefault("dualuse", [])
        # Lead the dual-use section with hard orbital signals.
        pillars["dualuse"] = orbital_items + pillars["dualuse"]

    log.info("STAGE 6    Synthesis & ledger update")
    ledger = state.load_ledger(settings.state_dir)
    exec_summary, movements = process.synthesize(
        pillars, launch, ledger, llm, settings, sources)
    briefing = process.build_briefing(
        pillars, launch, exec_summary, movements, week_start, week_end)

    log.info("STAGE 7    Render & deliver")
    md = render.render_markdown(briefing, sources)
    htmlb = render.render_html(briefing, sources)
    subject = f"Orbital Brief — {week_start} → {week_end}"

    # Always write the markdown to disk (the repo archive).
    os.makedirs("briefings", exist_ok=True)
    out_path = os.path.join("briefings", f"{week_end}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    log.info("  wrote %s", out_path)

    if dry_run:
        log.info("  DRY RUN — skipping email and state write.")
        return out_path

    send_email(settings, subject, md, htmlb)

    # Persist state only after a successful run.
    for it in raw:
        seen[it.id] = now.isoformat()
    state.save_seen(settings.state_dir, state.prune_seen(seen))
    state.save_ledger(settings.state_dir, ledger)
    state.save_orbital(settings.state_dir, orbital_state)
    log.info("  state saved.")
    return out_path
