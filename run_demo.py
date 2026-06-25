"""End-to-end offline demo of Sustenance Sentinel.

Runs the full agent crew against the MOCK Swiggy Food server (no network, no
spend, no API key needed). Simulates four lunch scenarios by feeding the
Orchestrator compressed `elapsed_min` ticks + replies:

  A. Cared-for replies "had a sandwich"          -> EATEN, no order
  B. Silence, confirm-first, countdown elapses    -> NO order (forgot-to-reply is SAFE)
  C. Silence, full-auto, countdown elapses        -> autonomous order placed
  D. Explicit "order for me" but daily cap blown  -> Guardian VETO, no order

Run:  python run_demo.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# Windows consoles default to cp1252 and choke on emoji in the warm messages.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sentinel.llm import LLM
from sentinel.mcp_client import get_food_client
from sentinel.models import Profile, Store
from sentinel.notify import ConsoleChannel
from sentinel.agents.orchestrator import Orchestrator

WINDOW = "lunch"
WINDOW_LEN = 120.0  # minutes (12:30-14:30)


def fresh_orchestrator(profile: Profile, store: Store) -> Orchestrator:
    return Orchestrator(
        profile, store, get_food_client(), LLM(),
        cared_for_channel=ConsoleChannel(), caregiver_channel=ConsoleChannel(),
    )


def banner(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def run_scenario(name: str, profile: Profile, ticks: list[tuple[float, str | None]],
                 day: str):
    banner(name)
    store = Store(db_path=tempfile.mktemp(suffix=".db"))
    orch = fresh_orchestrator(profile, store)
    for elapsed, reply in ticks:
        r = orch.tick(day, WINDOW, elapsed, WINDOW_LEN, reply)
        tag = f"reply={reply!r}" if reply else "silence"
        print(f"  [t+{elapsed:>4.0f}m {tag:<22}] -> {r.action.value}: {r.detail}")
    print("\n  --- agent trace (who decided what) ---")
    for t in store.traces_for(profile.person_id, day):
        print(f"    {t['agent']:<12} {t['message']}")
    store.close()


def main():
    cfg = "config.yaml" if os.path.exists("config.yaml") else "config.example.yaml"
    profile = Profile.from_yaml(cfg)
    online = "ONLINE (Claude)" if LLM().online else "OFFLINE (template fallback)"
    mcp = "REAL Swiggy MCP" if os.getenv("SWIGGY_MCP_URL") else "MOCK Swiggy Food"
    print(f"Sentinel demo — LLM: {online} | Food: {mcp} | autonomy: {profile.autonomy}")

    # A: confirms eating early.
    run_scenario("A. Cared-for ate (free-text reply)", profile,
                 [(0, None), (35, "had a sandwich at my desk")], "2026-06-25")

    # B: confirm-first + silence -> safe, no order.
    run_scenario("B. Silence + confirm-first -> NO order (forgot-to-reply is safe)",
                 profile, [(0, None), (45, None), (105, None), (125, None)], "2026-06-26")

    # C: full-auto + silence -> autonomous order.
    auto = Profile.from_yaml(cfg)
    auto.autonomy = "full-auto"
    run_scenario("C. Silence + full-auto -> autonomous order placed",
                 auto, [(0, None), (45, None), (105, None), (125, None)], "2026-06-27")

    # D: explicit order but day cap already blown -> Guardian veto.
    run_scenario_capblown(profile)


def run_scenario_capblown(profile: Profile):
    banner("D. Explicit 'order for me' but daily cap already spent -> Guardian VETO")
    day = "2026-06-28"
    store = Store(db_path=tempfile.mktemp(suffix=".db"))
    # Pre-load a breakfast order that eats the daily budget.
    store.record_order(profile.person_id, day, "breakfast", "Big Brunch",
                       "Big Brunch", profile.spend_cap_per_day, 30, "PRELOAD-1")
    orch = fresh_orchestrator(profile, store)
    r = orch.tick(day, WINDOW, 10, WINDOW_LEN, "order for me please")
    print(f"  [t+10m reply='order...'] -> {r.action.value}: {r.detail}")
    print("\n  --- agent trace ---")
    for t in store.traces_for(profile.person_id, day):
        print(f"    {t['agent']:<12} {t['message']}")
    store.close()


if __name__ == "__main__":
    main()
