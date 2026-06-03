"""Canonical data model. Everything that flows through the pipeline is one of these."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def item_id(url: str) -> str:
    """Stable id for de-duplication across runs."""
    return hashlib.sha1(url.strip().lower().encode("utf-8")).hexdigest()[:16]


@dataclass
class RawItem:
    """A single article/post pulled from a feed before any processing."""
    title: str
    url: str
    summary: str
    published: Optional[datetime]
    source_name: str
    country: str                 # US | CN | INTL
    trust: str                   # primary | secondary | aggregator
    source_pillars: list[str]    # pillars the *source* is tagged with (a hint, not a verdict)

    @property
    def id(self) -> str:
        return item_id(self.url)


@dataclass
class Cluster:
    """One or more RawItems that report the same underlying development."""
    title: str
    summary: str
    items: list[RawItem]

    @property
    def primary_url(self) -> str:
        return self.items[0].url

    @property
    def sources(self) -> list[tuple[str, str]]:
        # De-duplicate by source name, preserve order.
        seen, out = set(), []
        for it in self.items:
            if it.source_name not in seen:
                seen.add(it.source_name)
                out.append((it.source_name, it.url))
        return out

    @property
    def country_hint(self) -> str:
        countries = {it.country for it in self.items}
        if countries == {"CN"}:
            return "CN"
        if countries == {"US"}:
            return "US"
        return "INTL"


@dataclass
class ScoredCluster:
    cluster: Cluster
    in_scope: bool
    pillar: str          # transport | isam | dualuse | context
    country: str         # US | CN | INTL
    significance: int    # 1-5
    dual_use: bool
    reason: str


@dataclass
class AnalyzedItem:
    headline: str
    analysis: str                       # original-wording summary (copyright-safe)
    dual_use_read: Optional[str]        # the "so what for U.S. security" line
    pillar: str
    country: str
    significance: int
    sources: list[tuple[str, str]]


@dataclass
class Launch:
    name: str
    provider: str
    country: str
    net: Optional[str]      # ISO timestamp
    mission: str
    orbit: str
    success: Optional[bool]


@dataclass
class LaunchContext:
    launches: list[Launch] = field(default_factory=list)
    us_count: int = 0
    cn_count: int = 0
    note: str = ""


@dataclass
class OrbitalEvent:
    """A signal derived from orbital-tracking data, not from news."""
    kind: str                 # "proximity" | "maneuver"
    objects: list[str]        # human-readable names/ids involved
    detail: dict              # numeric facts (min_range_km, rel_v_ms, delta_a_km, ...)
    summary: str              # one-line factual description (no interpretation)


@dataclass
class Briefing:
    week_start: str
    week_end: str
    generated_at: str
    exec_summary: str
    ledger_movements: list[str]
    pillars: dict[str, list[AnalyzedItem]]   # pillar_id -> items
    launch_context: LaunchContext
