"""Meal-window + ladder-tick scheduling.

In production APScheduler fires `tick` periodically inside each meal window; the
Orchestrator's ladder figures out which step is due, so the scheduler stays dumb
(just "evaluate this window now"). `elapsed_minutes` and `window_len_minutes`
are the only time math the rest of the system needs.
"""
from __future__ import annotations

from datetime import datetime, date, time
from typing import Callable

from .models import Profile


def window_bounds(profile: Profile, window: str, day: date) -> tuple[datetime, datetime]:
    start_t, end_t = profile.meal_windows[window]
    return (datetime.combine(day, start_t), datetime.combine(day, end_t))


def elapsed_minutes(start: datetime, now: datetime) -> float:
    return (now - start).total_seconds() / 60.0


def window_len_minutes(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60.0


def build_scheduler(profile: Profile, tick: Callable[[str], None], poll_seconds: int = 300):
    """Return a configured APScheduler firing `tick(window)` every poll inside
    each meal window. Caller starts it. Imported lazily so tests/demo don't need
    apscheduler installed."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler()
    for window, (start_t, end_t) in profile.meal_windows.items():
        # Fire across the window; ticks outside bounds are no-ops in the Orchestrator.
        sched.add_job(
            lambda w=window: tick(w),
            CronTrigger(minute=f"*/{max(1, poll_seconds // 60)}",
                        hour=f"{start_t.hour}-{end_t.hour}"),
            id=f"{profile.person_id}-{window}",
            replace_existing=True,
        )
    return sched
