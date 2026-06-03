"""Thin Anthropic client wrapper: retries, and tolerant JSON extraction."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from anthropic import Anthropic

log = logging.getLogger("llm")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMClient:
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)

    def complete(self, model: str, system: str, user: str,
                 max_tokens: int = 2000, retries: int = 3) -> str:
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                # Join all text blocks (tool blocks, if any, are ignored here).
                return "".join(
                    b.text for b in resp.content if getattr(b, "type", None) == "text"
                ).strip()
            except Exception as e:  # noqa: BLE001 - we want to retry on any API error
                last_err = e
                wait = 2 ** attempt
                log.warning("LLM call failed (attempt %d/%d): %s — retrying in %ds",
                            attempt + 1, retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"LLM call failed after {retries} attempts: {last_err}")

    def complete_json(self, model: str, system: str, user: str,
                      max_tokens: int = 4000) -> Any:
        """Return parsed JSON. One self-correcting retry if the first parse fails."""
        raw = self.complete(model, system, user, max_tokens=max_tokens)
        try:
            return json.loads(_strip(raw))
        except json.JSONDecodeError:
            log.warning("JSON parse failed; asking the model to repair.")
            repair = self.complete(
                model,
                system="You repair malformed JSON. Output ONLY valid JSON, nothing else.",
                user=f"Fix this into valid JSON, preserving all content:\n\n{raw}",
                max_tokens=max_tokens,
            )
            return json.loads(_strip(repair))


def _strip(text: str) -> str:
    return _FENCE.sub("", text).strip()
