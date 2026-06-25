"""Escalation ladder — silence is safe, replies win immediately."""
from sentinel.ladder import (Action, STEP_CHECK_IN, STEP_NUDGE, STEP_LAST_CALL,
                             decide)
from sentinel.models import LadderTiming

T = LadderTiming(nudge_after_min=40, last_call_before_end_min=20, countdown_min=15)
LEN = 120.0
# derived: last_call_at = max(40, 120-20) = 100 ; order_at = 115


def test_check_in_at_start():
    r = decide(0, LEN, T, None, 0, full_auto=False)
    assert r.action == Action.SEND_CHECK_IN and r.step == STEP_CHECK_IN


def test_nudge_after_threshold():
    r = decide(45, LEN, T, None, STEP_CHECK_IN, False)
    assert r.action == Action.SEND_NUDGE and r.step == STEP_NUDGE


def test_last_call_near_end():
    r = decide(105, LEN, T, None, STEP_NUDGE, False)
    assert r.action == Action.SEND_LAST_CALL and r.step == STEP_LAST_CALL


def test_confirm_first_silence_never_orders():
    # Countdown elapsed, no reply, autonomy off -> close WITHOUT ordering.
    r = decide(116, LEN, T, None, STEP_LAST_CALL, full_auto=False)
    assert r.action == Action.CLOSE_NO_ORDER


def test_full_auto_silence_orders():
    r = decide(116, LEN, T, None, STEP_LAST_CALL, full_auto=True)
    assert r.action == Action.PLACE_ORDER


def test_late_ate_during_countdown_cancels_order():
    # The forgot-to-update protection: a reply at the last moment wins.
    r = decide(116, LEN, T, "ate", STEP_LAST_CALL, full_auto=True)
    assert r.action == Action.MARK_EATEN


def test_skip_reply_marks_skipped():
    r = decide(50, LEN, T, "skip", STEP_NUDGE, False)
    assert r.action == Action.MARK_SKIPPED


def test_order_reply_places_order_even_early():
    r = decide(10, LEN, T, "order", STEP_CHECK_IN, False)
    assert r.action == Action.PLACE_ORDER


def test_before_window_waits():
    r = decide(-5, LEN, T, None, 0, False)
    assert r.action == Action.WAIT
