"""Configuration: environment-backed Settings + YAML source registry loader."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

load_dotenv()  # no-op in CI where vars come from the environment directly


def _split(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _env(name: str, default: str) -> str:
    """Return an env var, falling back to default when missing OR empty/blank."""
    value = os.environ.get(name, "")
    return value.strip() if value and value.strip() else default


@dataclass
class Settings:
    anthropic_api_key: str
    model_score: str
    model_analyze: str
    model_synthesize: str
    lookback_days: int
    min_significance: int
    ll2_base: str
    ll2_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    email_from: str
    email_to: list[str]
    state_dir: str

    @classmethod
    def from_env(cls) -> "Settings":
        key = _env("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        return cls(
            anthropic_api_key=key,
            model_score=_env("MODEL_SCORE", "claude-haiku-4-5-20251001"),
            model_analyze=_env("MODEL_ANALYZE", "claude-sonnet-4-6"),
            model_synthesize=_env("MODEL_SYNTHESIZE", "claude-opus-4-8"),
            lookback_days=int(_env("LOOKBACK_DAYS", "7")),
            min_significance=int(_env("MIN_SIGNIFICANCE", "2")),
            ll2_base=_env("LL2_BASE", "https://ll.thespacedevs.com/2.3.0").rstrip("/"),
            ll2_api_key=_env("LL2_API_KEY", ""),
            smtp_host=_env("SMTP_HOST", ""),
            smtp_port=int(_env("SMTP_PORT", "587")),
            smtp_user=_env("SMTP_USER", ""),
            smtp_pass=_env("SMTP_PASS", ""),
            email_from=_env("EMAIL_FROM", ""),
            email_to=_split(os.environ.get("EMAIL_TO", "")),
            state_dir=_env("STATE_DIR", "state"),
        )


@dataclass
class SourceConfig:
    scope: str
    pillars: list[dict]
    entities: dict
    feeds: list[dict]
    search_seeds: list[str]
    launch_context: dict = field(default_factory=dict)
    orbital: dict = field(default_factory=dict)

    @property
    def pillar_ids(self) -> list[str]:
        return [p["id"] for p in self.pillars]

    def pillar_name(self, pid: str) -> str:
        for p in self.pillars:
            if p["id"] == pid:
                return p["name"]
        return pid


def load_sources(path: str = "config/sources.yaml") -> SourceConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return SourceConfig(
        scope=data.get("scope", "").strip(),
        pillars=data.get("pillars", []),
        entities=data.get("entities", {}),
        feeds=data.get("feeds", []),
        search_seeds=data.get("search_seeds", []),
        launch_context=data.get("launch_context", {}),
        orbital=data.get("orbital", {}),
    )
