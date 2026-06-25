"""Tiny Anthropic wrapper shared by the agent crew.

If ANTHROPIC_API_KEY is set, agents use Claude. Otherwise `complete` returns
None and each agent falls back to deterministic templates — so the pilot runs
fully offline for demos and CI.
"""
from __future__ import annotations

import os

# Model assignment from the plan: hard reasoning vs cheap high-volume loop.
MODEL_HEAVY = os.getenv("MODEL_HEAVY", "claude-opus-4-8")     # Orchestrator, Concierge
MODEL_LIGHT = os.getenv("MODEL_LIGHT", "claude-sonnet-4-6")   # Messenger, Guardian, Notify


class LLM:
    def __init__(self):
        self._client = None
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=key)
            except Exception:
                self._client = None

    @property
    def online(self) -> bool:
        return self._client is not None

    def complete(self, system: str, user: str, model: str = MODEL_LIGHT,
                 max_tokens: int = 400) -> str | None:
        """Return Claude's text, or None when offline (caller uses a fallback)."""
        if not self._client:
            return None
        msg = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
