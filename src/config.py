"""Configuration: environment-backed Settings + YAML source registry loader."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

load_dotenv()  # no-op in CI where vars come from the environment directly


def _split(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


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
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        return cls(
            anthropic_api_key=key,
            model_score=os.environ.get("MODEL_SCORE", "claude-haiku-4-5-20251001"),
            model_analyze=os.environ.get("MODEL_ANALYZE", "claude-sonnet-4-6"),
            model_synthesize=os.environ.get("MODEL_SYNTHESIZE", "claude-opus-4-8"),
            lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
            min_significance=int(os.environ.get("MIN_SIGNIFICANCE", "2")),
            ll2_base=os.environ.get("LL2_BASE", "https://ll.thespacedevs.com/2.3.0").rstrip("/"),
            ll2_api_key=os.environ.get("LL2_API_KEY", ""),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_pass=os.environ.get("SMTP_PASS", ""),
            email_from=os.environ.get("EMAIL_FROM", ""),
            email_to=_split(os.environ.get("EMAIL_TO", "")),
            state_dir=os.environ.get("STATE_DIR", "state"),
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
