"""Escalation ladder — the heart of "a forgotten reply must never auto-order."

Pure logic: given how far into the meal window we are, the latest reply, and
which step we already sent, decide the next Action. Silence advances through
check-in -> nudge -> soft countdown, and only an *elapsed countdown with no
opt-out* (and autonomy on) yields PLACE_ORDER.

Kept free of datetime/DB so it unit-tests with plain numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import LadderTiming

# Replies, normalized by the Messenger agent from free text.
REPLY_ATE = "ate"
REPLY_ORDER = "order"
REPLY_SKIP = "skip"

# ladder_step persisted in window_state: how far we've escalated.
STEP_NONE = 0
STEP_CHECK_IN = 1
STEP_NUDGE = 2
STEP_LAST_CALL = 3
STEP_CLOSED = 4


class Action(str, Enum):
    WAIT = "wait"                    # nothing to do yet
    SEND_CHECK_IN = "send_check_in"
    SEND_NUDGE = "send_nudge"
    SEND_LAST_CALL = "send_last_call"
    PLACE_ORDER = "place_order"
    MARK_EATEN = "mark_eaten"
    MARK_SKIPPED = "mark_skipped"
    CLOSE_NO_ORDER = "close_no_order"  # window ended, no meal, no order (autonomy off / cap)


@dataclass
class LadderResult:
    action: Action
    step: int          # ladder_step to persist after acting


def decide(
    elapsed_min: float,
    window_len_min: float,
    timing: LadderTiming,
    last_reply: str | None,
    current_step: int,
    full_auto: bool,
) -> LadderResult:
    """Return the single next Action for this window evaluation."""
    # 1) Explicit replies win immediately, at any step.
    if last_reply == REPLY_ATE:
        return LadderResult(Action.MARK_EATEN, STEP_CLOSED)
    if last_reply == REPLY_SKIP:
        return LadderResult(Action.MARK_SKIPPED, STEP_CLOSED)
    if last_reply == REPLY_ORDER:
        # cared-for asked us to order — still subject to Guardian/caps downstream.
        return LadderResult(Action.PLACE_ORDER, STEP_CLOSED)

    if current_step >= STEP_CLOSED:
        return LadderResult(Action.WAIT, STEP_CLOSED)

    # Time thresholds (minutes from window start).
    nudge_at = timing.nudge_after_min
    last_call_at = max(nudge_at, window_len_min - timing.last_call_before_end_min)
    order_at = last_call_at + timing.countdown_min

    # 2) Before the window opens.
    if elapsed_min < 0:
        return LadderResult(Action.WAIT, current_step)

    # 3) Countdown elapsed -> order (only path that spends money on silence).
    if elapsed_min >= order_at and current_step >= STEP_LAST_CALL:
        if full_auto:
            return LadderResult(Action.PLACE_ORDER, STEP_CLOSED)
        # confirm-first: we proposed at last-call; without a tap we do NOT order.
        return LadderResult(Action.CLOSE_NO_ORDER, STEP_CLOSED)

    # 4) Walk the escalation steps, emitting each message exactly once.
    if elapsed_min >= last_call_at and current_step < STEP_LAST_CALL:
        return LadderResult(Action.SEND_LAST_CALL, STEP_LAST_CALL)
    if elapsed_min >= nudge_at and current_step < STEP_NUDGE:
        return LadderResult(Action.SEND_NUDGE, STEP_NUDGE)
    if current_step < STEP_CHECK_IN:
        return LadderResult(Action.SEND_CHECK_IN, STEP_CHECK_IN)

    # 5) Between steps — wait for the next timer or a reply.
    return LadderResult(Action.WAIT, current_step)
