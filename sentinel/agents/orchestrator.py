"""Orchestrator — owns the workflow, delegates to the crew, enforces hard rules.

For one window evaluation it: checks kill-switch/idempotency, asks the Messenger
to parse any reply, runs the escalation `ladder`, and fans the resulting Action
out to Messenger / Concierge / Guardian / Notify. Every handoff is written to
the trace so the dashboard can replay "who decided what."
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ladder import Action, decide
from ..llm import LLM
from ..mcp_client import Dish, FoodClient
from ..models import (EATEN, NOT_EATEN, ORDERED, PENDING, SKIPPED, Profile, Store)
from ..notify import LADDER_BUTTONS
from .concierge import Concierge
from .guardian import Guardian
from .messenger import Messenger
from .notify_agent import NotifyAgent

# Map ladder send-actions to Messenger stage + which agent line to trace.
_SEND_STAGE = {
    Action.SEND_CHECK_IN: "check_in",
    Action.SEND_NUDGE: "nudge",
    Action.SEND_LAST_CALL: "last_call",
}


@dataclass
class TickResult:
    action: Action
    detail: str


class Orchestrator:
    name = "orchestrator"

    def __init__(self, profile: Profile, store: Store, food: FoodClient, llm: LLM,
                 cared_for_channel, caregiver_channel):
        self.p = profile
        self.store = store
        self.food = food
        self.messenger = Messenger(llm, profile)
        self.concierge = Concierge(food, profile)
        self.guardian = Guardian(profile)
        self.notify = NotifyAgent(llm, profile)
        self.cared_ch = cared_for_channel
        self.care_ch = caregiver_channel

    def _trace(self, day, window, agent, msg, data=None):
        self.store.trace(self.p.person_id, day, window, agent, msg, data)

    def tick(self, day: str, window: str, elapsed_min: float, window_len_min: float,
             reply_text: str | None) -> TickResult:
        pid = self.p.person_id

        # Hard rule: kill switch halts everything.
        if self.store.is_killed(pid):
            return TickResult(Action.WAIT, "kill-switch on")

        row = self.store.get_window(pid, day, window)
        status = row["status"] if row else PENDING
        step = row["ladder_step"] if row else 0
        if status in (EATEN, ORDERED, SKIPPED, NOT_EATEN):
            return TickResult(Action.WAIT, f"window already {status}")

        reply = self.messenger.parse_reply(reply_text)
        if reply:
            self._trace(day, window, self.messenger.name,
                        f"parsed reply '{reply_text}' -> {reply}")

        res = decide(elapsed_min, window_len_min, self.p.ladder, reply, step,
                     self.p.full_auto)
        action = res.action

        # --- send a ladder message ---
        if action in _SEND_STAGE:
            stage = _SEND_STAGE[action]
            text = self.messenger.compose(stage, window)
            self.cared_ch.send(self.p.name, text, LADDER_BUTTONS)
            self.store.set_window(pid, day, window, PENDING, res.step)
            self._trace(day, window, self.messenger.name, f"sent {stage}", {"text": text})
            return TickResult(action, text)

        # --- terminal: ate / skip ---
        if action == Action.MARK_EATEN:
            ack = self.messenger.compose("ate_ack", window)
            self.cared_ch.send(self.p.name, ack)
            self.store.set_window(pid, day, window, EATEN, res.step)
            self._trace(day, window, self.messenger.name, "marked EATEN")
            return TickResult(action, "ate")

        if action == Action.MARK_SKIPPED:
            self.store.set_window(pid, day, window, SKIPPED, res.step)
            self._trace(day, window, self.orchestrator_name(), "marked SKIPPED")
            return TickResult(action, "skipped")

        # --- close with no order (confirm-first silence / autonomy off) ---
        if action == Action.CLOSE_NO_ORDER:
            reason = "confirm-first: no tap during countdown"
            self.store.set_window(pid, day, window, NOT_EATEN, res.step)
            self.care_ch.send(self.p.caregiver_name,
                              self.notify.no_order_summary(window, reason))
            self._trace(day, window, self.notify.name, f"closed no-order: {reason}")
            return TickResult(action, reason)

        # --- place an order (explicit "order" reply, or full-auto countdown) ---
        if action == Action.PLACE_ORDER:
            return self._order_flow(day, window)

        return TickResult(Action.WAIT, "nothing due")

    def orchestrator_name(self) -> str:
        return self.name

    def _order_flow(self, day: str, window: str) -> TickResult:
        pid = self.p.person_id

        # Idempotency: never a second order in the same window.
        if self.store.order_exists(pid, day, window):
            return TickResult(Action.WAIT, "order already placed")

        spent = self.store.spent_today(pid, day)
        area = self.p.address.get("text", "")
        candidates = self.concierge.candidates(area)
        self._trace(day, window, self.concierge.name,
                    f"{len(candidates)} candidates ranked",
                    {"top": [c.item for c in candidates[:3]]})

        verdict = self.guardian.review(candidates, spent)
        for cand, dec in verdict.vetoed:
            self._trace(day, window, self.guardian.name,
                        f"VETO {cand.item}", {"reasons": dec.reasons})

        if not verdict.approved:
            reason = "all candidates vetoed by Guardian (diet/budget)"
            self.store.set_window(pid, day, window, NOT_EATEN, 4)
            self.care_ch.send(self.p.caregiver_name,
                              self.notify.no_order_summary(window, reason))
            self._trace(day, window, self.notify.name, f"closed no-order: {reason}")
            return TickResult(Action.CLOSE_NO_ORDER, reason)

        cand = verdict.approved
        self._trace(day, window, self.guardian.name, "APPROVED " + cand.item,
                    {"explain": verdict.decision.explain()})

        dish = Dish(cand.restaurant, cand.item, cand.price, cand.tags,
                    cand.calories, cand.spice, cand.vegetarian)
        order = self.food.place_order(cand.restaurant, dish, area)

        # Idempotent insert guards against a race placing two orders.
        if not self.store.record_order(pid, day, window, order.restaurant, order.item,
                                        order.total, order.eta_min, order.order_ref):
            return TickResult(Action.WAIT, "order raced; already recorded")

        self.store.set_window(pid, day, window, ORDERED, 4)
        summary = self.notify.order_summary(order, verdict.decision)
        self.care_ch.send(self.p.caregiver_name, summary)
        self._trace(day, window, self.notify.name, "ORDER placed", {
            "ref": order.order_ref, "item": order.item, "total": order.total,
            "eta_min": order.eta_min, "summary": summary,
        })
        return TickResult(Action.PLACE_ORDER, summary)
