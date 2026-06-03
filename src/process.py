"""Stages 3-6 — Normalize/dedup, score, analyze, synthesize + ledger update."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .config import Settings, SourceConfig
from .llm import LLMClient
from .models import (AnalyzedItem, Briefing, Cluster, LaunchContext, RawItem,
                     ScoredCluster)

log = logging.getLogger("process")

_SIM_THRESHOLD = 0.62  # title similarity above which two items are "the same story"


def _norm_title(t: str) -> str:
    return "".join(c.lower() for c in t if c.isalnum() or c.isspace()).strip()


# ---------------------------------------------------------------------------
# Stage 3 — drop already-seen items, cluster near-duplicates within the batch.
# ---------------------------------------------------------------------------
def dedup_and_cluster(items: list[RawItem], seen: dict[str, str]) -> list[Cluster]:
    fresh = [it for it in items if it.id not in seen]
    log.info("  %d new of %d fetched (%d already seen)",
             len(fresh), len(items), len(items) - len(fresh))

    clusters: list[Cluster] = []
    for it in fresh:
        nt = _norm_title(it.title)
        placed = False
        for c in clusters:
            if SequenceMatcher(None, nt, _norm_title(c.title)).ratio() >= _SIM_THRESHOLD:
                c.items.append(it)
                placed = True
                break
        if not placed:
            clusters.append(Cluster(title=it.title, summary=it.summary, items=[it]))
    log.info("  clustered into %d distinct developments", len(clusters))
    return clusters


# ---------------------------------------------------------------------------
# Stage 4 — relevance scoring (cheap model, one batched call).
# ---------------------------------------------------------------------------
def score_clusters(clusters: list[Cluster], llm: LLMClient,
                   settings: Settings, sources: SourceConfig) -> list[ScoredCluster]:
    if not clusters:
        return []

    pillar_doc = "\n".join(f"- {p['id']}: {p['name']} — {p['guidance'].strip()}"
                           for p in sources.pillars)
    catalog = [{"i": i, "title": c.title, "summary": c.summary[:300],
                "country_hint": c.country_hint} for i, c in enumerate(clusters)]

    system = (
        "You are the relevance filter for a U.S. national-security + tech-strategy "
        "space-industry briefing. You are precise and skeptical; most general space "
        "news is NOT in scope.\n\nEDITORIAL SCOPE:\n" + sources.scope +
        "\n\nPILLARS:\n" + pillar_doc +
        "\n\nFor each item return strict JSON. No prose outside JSON."
    )
    user = (
        "Score every item below. Return a JSON array; one object per item with keys:\n"
        '  "i" (int, the item index),\n'
        '  "in_scope" (bool),\n'
        '  "pillar" (one of: transport, isam, dualuse, context),\n'
        '  "country" (US, CN, or INTL),\n'
        '  "significance" (int 1-5; 5 = a genuine capability milestone),\n'
        '  "dual_use" (bool; true if a commercial item has a clear military read),\n'
        '  "reason" (<=20 words).\n\n'
        f"ITEMS:\n{json.dumps(catalog, ensure_ascii=False)}"
    )

    result = llm.complete_json(settings.model_score, system, user, max_tokens=4000)
    by_index = {int(r["i"]): r for r in result if "i" in r}

    scored: list[ScoredCluster] = []
    for i, c in enumerate(clusters):
        r = by_index.get(i)
        if not r:
            continue
        scored.append(ScoredCluster(
            cluster=c,
            in_scope=bool(r.get("in_scope")),
            pillar=r.get("pillar", "context"),
            country=r.get("country", c.country_hint),
            significance=int(r.get("significance", 1)),
            dual_use=bool(r.get("dual_use")),
            reason=r.get("reason", ""),
        ))
    kept = [s for s in scored if s.in_scope and s.significance >= settings.min_significance]
    log.info("  %d in-scope at significance >= %d", len(kept), settings.min_significance)
    return sorted(kept, key=lambda s: s.significance, reverse=True)


# ---------------------------------------------------------------------------
# Stage 5 — per-pillar analytic write-ups (mid model, one call per pillar).
# ---------------------------------------------------------------------------
def analyze_pillars(scored: list[ScoredCluster], llm: LLMClient,
                    settings: Settings, sources: SourceConfig) -> dict[str, list[AnalyzedItem]]:
    out: dict[str, list[AnalyzedItem]] = {}
    for pillar in sources.pillars:
        pid = pillar["id"]
        members = [s for s in scored if s.pillar == pid]
        if not members:
            continue

        payload = [{
            "i": j,
            "title": s.cluster.title,
            "summary": s.cluster.summary[:500],
            "country": s.country,
            "significance": s.significance,
            "dual_use": s.dual_use,
        } for j, s in enumerate(members)]

        system = (
            "You are a space-industry analyst writing for a reader in U.S. defense and "
            "tech strategy. Write tight, analytic, original prose — NEVER quote or copy "
            "source wording; summarize the development in your own words. Be concrete and "
            "skeptical; flag uncertainty.\n\nSCOPE:\n" + sources.scope +
            f"\n\nCURRENT PILLAR: {pillar['name']} — {pillar['guidance'].strip()}"
        )
        user = (
            "For each development return JSON array; one object per item with keys:\n"
            '  "i" (int index),\n'
            '  "headline" (<=12 words, your own words),\n'
            '  "analysis" (2-4 sentences: what happened and why it matters, your own words),\n'
            '  "dual_use_read" (1-2 sentences on the U.S. national-security implication, '
            "or null if genuinely none).\n\n"
            f"DEVELOPMENTS:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        result = llm.complete_json(settings.model_analyze, system, user, max_tokens=4000)
        by_index = {int(r["i"]): r for r in result if "i" in r}

        analyzed = []
        for j, s in enumerate(members):
            r = by_index.get(j, {})
            analyzed.append(AnalyzedItem(
                headline=r.get("headline", s.cluster.title),
                analysis=r.get("analysis", s.cluster.summary[:300]),
                dual_use_read=r.get("dual_use_read"),
                pillar=pid,
                country=s.country,
                significance=s.significance,
                sources=s.cluster.sources,
            ))
        out[pid] = analyzed
        log.info("  analyzed %d items in pillar '%s'", len(analyzed), pid)
    return out


# ---------------------------------------------------------------------------
# Stage 6 — synthesis: exec summary + asymmetry-ledger diff (strongest model).
# Mutates `ledger` in place and returns (exec_summary, movements).
# ---------------------------------------------------------------------------
def synthesize(pillars: dict[str, list[AnalyzedItem]], launch: LaunchContext,
               ledger: dict, llm: LLMClient, settings: Settings,
               sources: SourceConfig) -> tuple[str, list[str]]:
    flat = [{
        "pillar": pid, "country": a.country, "significance": a.significance,
        "headline": a.headline, "analysis": a.analysis, "dual_use": a.dual_use_read,
    } for pid, items in pillars.items() for a in items]

    if not flat:
        return ("No in-scope developments crossed the significance threshold this week.", [])

    system = (
        "You are the lead analyst for a weekly U.S.-vs-China space-capability briefing. "
        "You maintain a persistent ASYMMETRY LEDGER tracking comparative capability across "
        "key areas (e.g. autonomous refueling, GEO RPO, responsive launch, life extension, "
        "megaconstellation deployment). Write in original wording only.\n\nSCOPE:\n"
        + sources.scope
    )
    user = (
        "INPUTS:\n"
        f"- This week's analyzed developments (JSON):\n{json.dumps(flat, ensure_ascii=False)}\n\n"
        f"- Launch context: US={launch.us_count}, CN={launch.cn_count}, {launch.note}\n\n"
        f"- Current asymmetry ledger (JSON, may be empty):\n"
        f"{json.dumps(ledger.get('capabilities', {}), ensure_ascii=False)}\n\n"
        "TASKS — return one JSON object with keys:\n"
        '  "exec_summary" (3-5 sentences; the week\'s strategic bottom line for a U.S. '
        "defense/tech reader; lead with the single most important signal),\n"
        '  "ledger_movements" (array of <=5 short strings: what changed in the U.S.-vs-China '
        "balance THIS WEEK, each naming the capability and who moved),\n"
        '  "updated_ledger" (object: capability_name -> {"us": short status string, '
        '"cn": short status string, "notes": short string}). Merge this week into the prior '
        "ledger; keep capabilities even if unchanged; update only what moved."
    )
    result = llm.complete_json(settings.model_synthesize, system, user, max_tokens=4000)

    updated = result.get("updated_ledger")
    if isinstance(updated, dict) and updated:
        for cap, val in updated.items():
            if isinstance(val, dict):
                val["last_updated"] = datetime.now(timezone.utc).date().isoformat()
        ledger["capabilities"] = updated

    return (result.get("exec_summary", ""), result.get("ledger_movements", []) or [])


def analyze_orbital_events(events, llm: LLMClient, settings: Settings,
                           sources: SourceConfig) -> list[AnalyzedItem]:
    """Turn structured orbital signals into dual-use AnalyzedItems with a defense read."""
    if not events:
        return []
    cfg = getattr(sources, "orbital", {}) or {}
    sig = int(cfg.get("event_significance", 4))
    payload = [{"i": i, "kind": e.kind, "objects": e.objects,
                "facts": e.detail, "summary": e.summary}
               for i, e in enumerate(events)]
    system = (
        "You are a space-domain-awareness analyst. You are given ORBITAL-TRACKING "
        "signals (not news): proximity events (two objects holding close formation) and "
        "maneuvers. Public elements are km-accurate and lag reality, so treat these as "
        "tripwires, not confirmed intent — hedge appropriately. Write original wording.\n\n"
        "SCOPE:\n" + sources.scope
    )
    user = (
        "For each signal return a JSON array; one object per signal with keys:\n"
        '  "i" (int), "headline" (<=12 words), "country" (US, CN, or INTL — infer from '
        'the object names), "analysis" (2-3 sentences stating the observed geometry and '
        "what it plausibly indicates, with appropriate hedging), "
        '"dual_use_read" (1-2 sentences on the U.S. national-security implication).\n\n'
        f"SIGNALS:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    result = llm.complete_json(settings.model_analyze, system, user, max_tokens=3000)
    by_index = {int(r["i"]): r for r in result if "i" in r}

    out: list[AnalyzedItem] = []
    for i, e in enumerate(events):
        r = by_index.get(i, {})
        out.append(AnalyzedItem(
            headline=r.get("headline", e.summary[:80]),
            analysis=r.get("analysis", e.summary),
            dual_use_read=r.get("dual_use_read"),
            pillar="dualuse",
            country=r.get("country", "INTL"),
            significance=sig,
            sources=[("Space-Track (orbital data)", "https://www.space-track.org")],
        ))
    log.info("  analyzed %d orbital event(s)", len(out))
    return out


def build_briefing(pillars, launch, exec_summary, movements,
                   week_start, week_end) -> Briefing:
    return Briefing(
        week_start=week_start,
        week_end=week_end,
        generated_at=datetime.now(timezone.utc).isoformat(),
        exec_summary=exec_summary,
        ledger_movements=movements,
        pillars=pillars,
        launch_context=launch,
    )
