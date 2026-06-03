"""Stage 2 — Ingestion. RSS/Atom feeds and the Launch Library 2 launch context.
Every external call is fault-tolerant: a dead feed or API hiccup is logged and
skipped, never fatal."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import requests

from .config import Settings, SourceConfig
from .models import Launch, LaunchContext, RawItem

log = logging.getLogger("ingest")

_TAGS = re.compile(r"<[^>]+>")

# Many news sites block non-browser clients. Identify as a normal browser so
# their bot-protection lets the feed through.
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def _clean(html: str, limit: int = 600) -> str:
    text = _TAGS.sub(" ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parsed_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
    return None


def _fetch_feed(url: str):
    """Fetch a feed as a browser would, then hand the bytes to feedparser."""
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=25)
    return feedparser.parse(resp.content)


def fetch_rss(sources: SourceConfig, lookback_days: int) -> list[RawItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items: list[RawItem] = []
    for feed in sources.feeds:
        try:
            parsed = _fetch_feed(feed["url"])
            if parsed.bozo and not parsed.entries:
                log.warning("Feed unreadable, skipping: %s (%s)", feed["name"], feed["url"])
                continue
            kept = 0
            for e in parsed.entries:
                pub = _parsed_date(e)
                if pub and pub < cutoff:
                    continue
                link = getattr(e, "link", "")
                if not link:
                    continue
                items.append(RawItem(
                    title=getattr(e, "title", "(untitled)").strip(),
                    url=link,
                    summary=_clean(getattr(e, "summary", "")),
                    published=pub,
                    source_name=feed["name"],
                    country=feed.get("country", "INTL"),
                    trust=feed.get("trust", "secondary"),
                    source_pillars=feed.get("pillars", []),
                ))
                kept += 1
            log.info("  %-34s %3d items", feed["name"], kept)
        except Exception as e:  # noqa: BLE001
            log.warning("Feed error %s: %s", feed["name"], e)
    return items


def check_feeds(sources: SourceConfig) -> None:
    """Utility: report which feeds are alive. Run via `python run.py --check-feeds`."""
    for feed in sources.feeds:
        try:
            parsed = _fetch_feed(feed["url"])
            n = len(parsed.entries)
            status = f"OK  ({n} entries)" if n else "EMPTY / unreadable"
        except Exception as e:  # noqa: BLE001
            status = f"ERROR: {e}"
        print(f"  [{status:<22}] {feed['name']}  ->  {feed['url']}")


_COUNTRY_MAP = {"USA": "US", "United States": "US", "CHN": "CN", "China": "CN"}


def fetch_launches(settings: Settings, sources: SourceConfig) -> LaunchContext:
    cfg = sources.launch_context or {}
    if not cfg.get("enabled", True):
        return LaunchContext(note="launch context disabled")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=settings.lookback_days)
    url = f"{settings.ll2_base}/launches/previous/"
    params = {
        "net__gte": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "net__lte": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": cfg.get("max_launches", 60),
        "mode": "list",
    }
    headers = {"User-Agent": "space-brief-agent/1.0"}
    if settings.ll2_api_key:
        headers["Authorization"] = f"Token {settings.ll2_api_key}"

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("Launch Library 2 unavailable: %s", e)
        return LaunchContext(note=f"launch data unavailable: {e}")

    launches: list[Launch] = []
    for L in data.get("results", []):
        provider = (L.get("launch_service_provider") or {})
        country_raw = provider.get("country_code") or provider.get("country") or ""
        country = _COUNTRY_MAP.get(country_raw, country_raw or "INTL")
        mission = (L.get("mission") or {})
        launches.append(Launch(
            name=L.get("name", ""),
            provider=provider.get("name", "Unknown"),
            country=country,
            net=L.get("net"),
            mission=(mission.get("name") if isinstance(mission, dict) else "") or "",
            orbit=((mission.get("orbit") or {}).get("abbrev", "") if isinstance(mission, dict) else ""),
            success=(L.get("status", {}) or {}).get("abbrev", "") == "Success",
        ))

    us = sum(1 for L in launches if L.country == "US")
    cn = sum(1 for L in launches if L.country == "CN")
    log.info("  launches in window: %d (US=%d, CN=%d)", len(launches), us, cn)
    return LaunchContext(launches=launches, us_count=us, cn_count=cn,
                         note=f"{len(launches)} launches in the last {settings.lookback_days} days")
