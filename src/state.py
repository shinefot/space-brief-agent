"""Persistent state. Two JSON files, committed back to the repo by CI so the
agent has memory across ephemeral runs:

  state/seen.json    -> {item_id: iso_timestamp}   (cross-run de-duplication)
  state/ledger.json  -> the U.S.-vs-China asymmetry ledger

For this volume (dozens of items/week) JSON is plenty and stays human-diffable in
git. If volume grows, swap this module for SQLite without touching the pipeline.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

SEEN_FILE = "seen.json"
LEDGER_FILE = "ledger.json"
ORBITAL_FILE = "orbital.json"


def _path(state_dir: str, name: str) -> str:
    return os.path.join(state_dir, name)


def load_seen(state_dir: str) -> dict[str, str]:
    p = _path(state_dir, SEEN_FILE)
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(state_dir: str, seen: dict[str, str]) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(_path(state_dir, SEEN_FILE), "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, sort_keys=True)


def prune_seen(seen: dict[str, str], keep_days: int = 60) -> dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    out = {}
    for k, ts in seen.items():
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                out[k] = ts
        except ValueError:
            out[k] = ts
    return out


def load_ledger(state_dir: str) -> dict:
    p = _path(state_dir, LEDGER_FILE)
    if not os.path.exists(p):
        return {"capabilities": {}, "last_run": None}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ledger(state_dir: str, ledger: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    ledger["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(_path(state_dir, LEDGER_FILE), "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True, ensure_ascii=False)


def load_orbital(state_dir: str) -> dict:
    """Last-seen orbital elements per NORAD id, used to diff for maneuvers."""
    p = _path(state_dir, ORBITAL_FILE)
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_orbital(state_dir: str, orbital: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(_path(state_dir, ORBITAL_FILE), "w", encoding="utf-8") as f:
        json.dump(orbital, f, indent=2, sort_keys=True)
