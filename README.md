# Space Brief Agent

A weekly intelligence briefing on the **U.S. and Chinese orbital-space industry**, written for a reader who sits at the intersection of **tech strategy** and **U.S. national security**. Editorial thesis: *space maneuver and logistics, read through a dual-use lens.*

Each Monday it ingests space-industry news + launch data, filters to what matters, writes analytic summaries with a defense read, updates a persistent **U.S.-vs-China asymmetry ledger**, and emails you the brief.

---

## Architecture

A 7-stage pipeline, all config-driven. The editorial scope and sources live in `config/sources.yaml`; the code is generic.

```
1. Source Registry      config/sources.yaml — feeds, entities, pillars, scope
2. Ingestion            src/ingest.py — RSS/Atom + Launch Library 2 (fault-tolerant)
3. Normalize & Dedup    src/process.py — drop seen items, cluster near-duplicates
4. Relevance Scoring    src/process.py — Haiku: in-scope? pillar? significance 1-5? dual-use?
5. Per-Pillar Analysis  src/process.py — Sonnet: original-wording analytic write-ups
6. Synthesis + Ledger   src/process.py — Opus: exec summary + asymmetry-ledger diff
7. Render & Deliver     src/render.py + src/deliver.py — Markdown archive + HTML email
```

**Tiered model routing** keeps a weekly run to pennies: cheap **Haiku** does high-volume scoring, **Sonnet** writes the analysis, **Opus** does the strategic synthesis where reasoning matters most. Override any of them via env vars.

**State** (`state/seen.json`, `state/ledger.json`) is committed back to the repo by CI after each run, giving the agent memory across GitHub's ephemeral runners — cross-run de-duplication and a ledger that tracks capability *trajectories*, not just weekly snapshots.

### The four pillars
1. **Transport / Movers** — OTVs, tugs, kick stages, reusable heavy-lift
2. **In-Orbit Servicing & Infrastructure (ISAM)** — refueling, docking, life-extension, debris, in-space assembly
3. **Dual-Use & Defense Read** — RPO, responsive space, counterspace; where the U.S.-vs-China asymmetry analysis lives
4. **Access & Constellations** — thin launch-cadence + megaconstellation context, mostly auto-generated from the launch API

---

## Setup

### 1. Local test
```bash
git clone <your-repo> && cd space-brief-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in your keys
python run.py --check-feeds   # confirm feed URLs are alive (see note below)
python run.py --dry-run       # build a brief to briefings/, no email sent
```

### 2. GitHub Actions (production)
1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions → Secrets**, add:
   `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `EMAIL_TO` (and optionally `LL2_API_KEY`).
3. Under **Variables** (optional, non-secret) you can set `MODEL_SCORE`, `MODEL_ANALYZE`, `MODEL_SYNTHESIZE`, `LOOKBACK_DAYS`, `MIN_SIGNIFICANCE`.
4. The workflow runs Mondays 13:00 UTC. Trigger a manual run any time from the **Actions** tab (with an optional dry-run toggle).

**Gmail tip:** use an [App Password](https://support.google.com/accounts/answer/185833), not your account password. Any SMTP provider works (Fastmail, Resend SMTP, Mailgun, etc.).

---

## Configuring scope

Everything editorial is in `config/sources.yaml`:
- **`scope`** — the mission statement injected into every LLM prompt. Tightening this is the highest-leverage way to change what the brief covers.
- **`feeds`** — add/remove RSS sources; tag each with `country`, `trust`, and `pillars`.
- **`entities`** — watchlists that bias scoring and key the ledger.
- **`search_seeds`** — gap-filling query ideas.
- **`min_significance`** (env) — raise to 3 for a tighter, higher-signal brief.

> **Verify feed URLs first.** The included feed URLs are best-effort; RSS endpoints drift. Run `python run.py --check-feeds` and fix any that report `ERROR`/`EMPTY`. Dead feeds are skipped at runtime, never fatal.

---

## Cost

A typical week (≈40–80 items → ≈20–40 clusters) is roughly **1 Haiku scoring call + ≤4 Sonnet analysis calls + 1 Opus synthesis call** — on the order of a few cents per week at current pricing. Verify current rates at https://platform.claude.com/docs (pricing changes).

---

## Orbital tasking signal (RPO / maneuver detection)

`src/ingest_orbital.py` reads **public catalog data** to flag developments that usually *precede* news coverage:
- **Proximity (RPO):** two watchlist objects holding a small separation at low relative velocity — the signature of deliberate station-keeping, not a fast conjunction.
- **Maneuvers:** a step change in an object's semi-major axis since the last run.

Detected events lead the **Dual-Use** section and feed the synthesis/ledger step.

**Enable it:**
1. Create a free account at https://www.space-track.org and set `SPACETRACK_USER` / `SPACETRACK_PASS` (repo secrets in CI).
2. In `config/sources.yaml` set `orbital.enabled: true` and fill the `watchlist` with **current** NORAD catalog IDs (the placeholders there must be verified — catalog numbers change, and `Shijian-25` is `0` pending confirmation). Look IDs up on Space-Track or Celestrak.
3. `pip install -r requirements.txt` pulls the extra deps (`sgp4`, `numpy`, `spacetrack`).

**Honest limitation — it's a tripwire, not a verdict.** Public elements are km-accurate and lag reality, and some sensitive objects aren't published (catalog gaps have appeared around sensitive RPO activity). The module reliably tells you *"X and Y are flying in formation,"* which is the high-value early warning; precise characterization needs commercial SSA (LeoLabs radar, Slingshot/ExoAnalytic optical). If credentials or libraries are absent the module skips silently.

---

## Upgrade paths (designed-in hooks)

- **Embeddings dedup** — swap the `difflib` title clustering in `process.dedup_and_cluster` for embedding similarity when volume grows.
- **SQLite state** — replace `src/state.py` (same function signatures) if JSON-in-git gets noisy.
- **Chinese-language primary sources** — add Chinese-language feeds and a translation pass before scoring, to get ahead of English secondary coverage. The Andrew Jones (*SpaceNews China Report*) and *China Space Monitor* feeds already give a strong English backbone.
- **Commercial SSA** — extend the orbital module with a paid SSA feed for characterization beyond the public-catalog tripwire.
- **Web-search gap-fill** — wire `search_seeds` to the Anthropic web-search tool to cover stories no feed carried.

---

## Project layout
```
config/sources.yaml          scope, pillars, feeds, entities
src/config.py                Settings (env) + SourceConfig (yaml)
src/models.py                canonical dataclasses
src/llm.py                   Anthropic wrapper (retry + JSON repair)
src/ingest.py                RSS + Launch Library 2
src/ingest_orbital.py        Space-Track GP + sgp4 RPO/maneuver detection
src/process.py               dedup, score, analyze, synthesize
src/state.py                 JSON state (seen + ledger)
src/render.py                Markdown + HTML
src/deliver.py               SMTP email
src/pipeline.py              orchestration
run.py                       CLI entrypoint
.github/workflows/           weekly cron + commit-state-back
```

*Automated analysis — verify before acting on any single item.*
