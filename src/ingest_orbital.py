"""Orbital tasking signal — detects RPO (rendezvous & proximity ops) and maneuvers
from public catalog data, which typically *precede* news coverage.

Pipeline within this module:
  1. Fetch latest GP (general-perturbations) elements for a watchlist from
     Space-Track (the `gp` class; the old `tle` class was retired in early 2026).
  2. Propagate each object over a forward window with sgp4 (TEME frame).
  3. Proximity: flag pairs that hold a SMALL separation at LOW relative velocity
     — the signature of deliberate station-keeping, not a fast conjunction.
  4. Maneuver: diff each object's mean motion / semi-major axis against the last
     run's stored value; a step change implies a burn.

Honest limitation: public elements are km-accurate and lag reality, and some
sensitive objects aren't published. Treat output as a TRIPWIRE ("X and Y are
flying in formation"), not a precise characterization of intent.

Dependencies (optional): `spacetrack`, `sgp4`, `numpy`. If missing, or if no
Space-Track credentials are set, the module degrades gracefully and returns [].
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from .config import Settings, SourceConfig
from .models import OrbitalEvent

log = logging.getLogger("orbital")

MU = 398600.4418  # Earth gravitational parameter, km^3/s^2


# --------------------------------------------------------------------------
# Element fetch (Space-Track GP class via the maintained `spacetrack` library).
# --------------------------------------------------------------------------
def _fetch_elements(norad_ids: list[int]) -> dict[int, dict]:
    user = os.environ.get("SPACETRACK_USER", "")
    pw = os.environ.get("SPACETRACK_PASS", "")
    if not (user and pw):
        log.warning("SPACETRACK_USER/PASS not set — skipping orbital module.")
        return {}
    try:
        from spacetrack import SpaceTrackClient  # local import: optional dep
    except ImportError:
        log.warning("`spacetrack` not installed — skipping orbital module.")
        return {}

    try:
        st = SpaceTrackClient(identity=user, password=pw)
        # One combined query (comma-delimited list) — Space-Track requires
        # batching rather than one request per object. 3le = name + TLE lines.
        raw = st.gp(norad_cat_id=norad_ids, format="3le")
    except Exception as e:  # noqa: BLE001
        log.warning("Space-Track query failed: %s", e)
        return {}

    return _parse_3le(raw)


def _parse_3le(text: str) -> dict[int, dict]:
    """Parse 3LE text blocks into {norad_id: {name, l1, l2, mean_motion, epoch}}."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out: dict[int, dict] = {}
    i = 0
    while i + 2 < len(lines) + 1:
        if i + 1 >= len(lines):
            break
        name = lines[i].lstrip("0 ").strip() if lines[i].startswith("0 ") else lines[i].strip()
        l1, l2 = lines[i + 1], lines[i + 2] if i + 2 < len(lines) else ""
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            i += 1
            continue
        try:
            norad = int(l2[2:7])
            mean_motion = float(l2[52:63])  # revs/day
        except ValueError:
            i += 3
            continue
        out[norad] = {"name": name, "l1": l1, "l2": l2, "mean_motion": mean_motion}
        i += 3
    return out


# --------------------------------------------------------------------------
# Propagation + detection.
# --------------------------------------------------------------------------
def _semi_major_axis(mean_motion_rev_day: float) -> float:
    n = mean_motion_rev_day * 2.0 * 3.141592653589793 / 86400.0  # rad/s
    return (MU / (n * n)) ** (1.0 / 3.0)  # km


def _detect(elements: dict[int, dict], prev_state: dict, cfg: dict) -> list[OrbitalEvent]:
    import numpy as np
    from sgp4.api import Satrec, jday

    window_h = cfg.get("window_hours", 72)
    step_m = cfg.get("step_minutes", 10)
    range_km = cfg.get("proximity_range_km", 75.0)
    relv_ms = cfg.get("proximity_rel_velocity_ms", 200.0)
    a_step_km = cfg.get("maneuver_delta_a_km", 2.0)

    # Propagate every object across the window.
    start = datetime.now(timezone.utc)
    steps = int(window_h * 60 / step_m)
    jds, frs = [], []
    for k in range(steps):
        t = start + timedelta(minutes=k * step_m)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second)
        jds.append(jd); frs.append(fr)

    tracks: dict[int, dict] = {}
    for nid, el in elements.items():
        try:
            sat = Satrec.twoline2rv(el["l1"], el["l2"])
        except Exception:  # noqa: BLE001
            continue
        pos, vel, ok = [], [], True
        for jd, fr in zip(jds, frs):
            e, r, v = sat.sgp4(jd, fr)
            if e != 0:
                ok = False
                break
            pos.append(r); vel.append(v)
        if ok and pos:
            tracks[nid] = {"r": np.array(pos), "v": np.array(vel), "name": el["name"]}

    events: list[OrbitalEvent] = []

    # --- Proximity: pairwise sustained small separation at low relative velocity.
    ids = list(tracks.keys())
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            ta, tb = tracks[ids[a]], tracks[ids[b]]
            dr = np.linalg.norm(ta["r"] - tb["r"], axis=1)            # km
            dv = np.linalg.norm(ta["v"] - tb["v"], axis=1) * 1000.0    # m/s
            j = int(dr.argmin())
            if dr[j] <= range_km and dv[j] <= relv_ms:
                t_close = (start + timedelta(minutes=j * step_m)).isoformat()
                events.append(OrbitalEvent(
                    kind="proximity",
                    objects=[f'{ta["name"]} ({ids[a]})', f'{tb["name"]} ({ids[b]})'],
                    detail={"min_range_km": round(float(dr[j]), 1),
                            "rel_velocity_ms": round(float(dv[j]), 1),
                            "closest_approach_utc": t_close},
                    summary=(f'{ta["name"]} and {tb["name"]} hold a '
                             f'{dr[j]:.0f} km separation at {dv[j]:.0f} m/s relative velocity'),
                ))

    # --- Maneuver: semi-major-axis step change vs last run.
    new_state: dict[str, dict] = {}
    for nid, el in elements.items():
        a_now = _semi_major_axis(el["mean_motion"])
        new_state[str(nid)] = {"mean_motion": el["mean_motion"], "a_km": round(a_now, 3)}
        prev = prev_state.get(str(nid))
        if prev and "a_km" in prev:
            delta = a_now - prev["a_km"]
            if abs(delta) >= a_step_km:
                events.append(OrbitalEvent(
                    kind="maneuver",
                    objects=[f'{el["name"]} ({nid})'],
                    detail={"delta_a_km": round(delta, 2),
                            "a_prev_km": prev["a_km"], "a_now_km": round(a_now, 3)},
                    summary=(f'{el["name"]} changed semi-major axis by {delta:+.1f} km '
                             "since last run (possible maneuver)"),
                ))
    prev_state.clear()
    prev_state.update(new_state)
    return events


# --------------------------------------------------------------------------
# Public entrypoint.
# --------------------------------------------------------------------------
def detect(settings: Settings, sources: SourceConfig,
           prev_state: dict) -> list[OrbitalEvent]:
    cfg = getattr(sources, "orbital", None) or {}
    if not cfg.get("enabled", False):
        return []
    watchlist = cfg.get("watchlist", [])
    norad_ids = [int(w["norad_id"]) for w in watchlist if w.get("norad_id")]
    if not norad_ids:
        log.info("  orbital module enabled but watchlist is empty.")
        return []

    elements = _fetch_elements(norad_ids)
    if not elements:
        return []
    try:
        events = _detect(elements, prev_state, cfg)
    except ImportError:
        log.warning("`sgp4`/`numpy` not installed — skipping detection.")
        return []
    log.info("  orbital events detected: %d", len(events))
    return events
