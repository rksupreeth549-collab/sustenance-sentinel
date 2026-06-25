"""Caregiver-Notify agent — closes the loop with the caregiver.

Composes a human-readable order summary + the one-line reasoning, sends it to
the caregiver channel, and (via the orchestrator) the full trace is already in
SQLite for the dashboard replay.
"""
from __future__ import annotations

from ..llm import LLM, MODEL_LIGHT
from ..mcp_client import OrderResult
from ..models import Profile
from ..policy import Decision

_SYSTEM = (
    "You are the Notify agent. Write ONE concise, reassuring line to the caregiver "
    "summarizing a food order placed for their loved one. Include item, restaurant, "
    "price, ETA. Warm but factual. Output only the message."
)


class NotifyAgent:
    name = "notify"

    def __init__(self, llm: LLM, profile: Profile):
        self.llm = llm
        self.p = profile

    def order_summary(self, order: OrderResult, decision: Decision) -> str:
        if self.llm.online:
            user = (
                f"Caregiver: {self.p.caregiver_name}. Loved one: {self.p.name}. "
                f"Ordered {order.item} from {order.restaurant}, ₹{order.total}, "
                f"ETA {order.eta_min} min. Ref {order.order_ref}."
            )
            out = self.llm.complete(_SYSTEM, user, model=MODEL_LIGHT, max_tokens=120)
            if out:
                return out
        return (
            f"Ordered {order.item} for {self.p.name} from {order.restaurant} — "
            f"₹{order.total}, ETA {order.eta_min} min. Ref {order.order_ref}."
        )

    def no_order_summary(self, window: str, reason: str) -> str:
        return f"No {window} order for {self.p.name}: {reason}"
