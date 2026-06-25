"""Messenger agent — owns ALL cared-for communication.

Writes warm, personalized check-ins / nudges / last-calls in the caregiver's
tone, and parses free-text replies ("had a sandwich" -> ate) into structured
ladder replies. Uses Claude when online; deterministic templates otherwise.
"""
from __future__ import annotations

from ..ladder import REPLY_ATE, REPLY_ORDER, REPLY_SKIP
from ..llm import LLM, MODEL_LIGHT
from ..models import Profile

_SYSTEM = (
    "You are the Messenger in a food-care assistant. You write ONE short, warm "
    "message (max 2 sentences, 1 emoji ok) to a loved one, in the given tone and "
    "relationship voice. Never sound like a corporate bot. Output only the message."
)

# Fallback templates per ladder stage.
_TEMPLATES = {
    "check_in": "Hey {name}, swamped day? 🍱 Did you grab {meal} yet, or should I sort it for you?",
    "nudge": "Still no {meal}, {name}? 😟 Say the word and I'll get your usual going.",
    "last_call": "Last call, {name} — I'll order your usual {meal} in {countdown} min unless you tap Skip. 🍲",
    "ate_ack": "Love that. Glad you ate, {name}. 💛",
    "order_ack": "On it — sorting your {meal} now. 🍱",
}

# Free-text reply -> structured ladder reply (offline keyword parser).
_ATE = ("ate", "had", "eaten", "lunch done", "just ate", "finished", "full")
_ORDER = ("order", "get me", "yes please", "go ahead", "sort it", "do it")
_SKIP = ("skip", "no", "not hungry", "i'll handle", "ill handle", "later", "fasting")


class Messenger:
    name = "messenger"

    def __init__(self, llm: LLM, profile: Profile):
        self.llm = llm
        self.p = profile

    def compose(self, stage: str, meal: str) -> str:
        countdown = self.p.ladder.countdown_min
        if self.llm.online:
            user = (
                f"Relationship: {self.p.relationship}. Tone: {self.p.tone}. "
                f"Their name: {self.p.name}. Meal: {meal}. Stage: {stage}. "
                f"(For last_call mention they can tap Skip within {countdown} min.)"
            )
            out = self.llm.complete(_SYSTEM, user, model=MODEL_LIGHT, max_tokens=120)
            if out:
                return out
        tmpl = _TEMPLATES.get(stage, _TEMPLATES["check_in"])
        return tmpl.format(name=self.p.name, meal=meal, countdown=countdown)

    def parse_reply(self, text: str | None) -> str | None:
        """Normalize a raw reply to REPLY_ATE / REPLY_ORDER / REPLY_SKIP / None."""
        if not text:
            return None
        t = text.strip().lower()
        # Exact button labels first.
        if t.startswith("ate"):
            return REPLY_ATE
        if t.startswith("order"):
            return REPLY_ORDER
        if t.startswith("skip"):
            return REPLY_SKIP
        if any(k in t for k in _SKIP):
            return REPLY_SKIP
        if any(k in t for k in _ORDER):
            return REPLY_ORDER
        if any(k in t for k in _ATE):
            return REPLY_ATE
        return None
