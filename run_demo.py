"""End-to-end demo of Sustenance Sentinel — built for screen recording.

Runs the full agent crew against the MOCK Swiggy Food server (no network, no
spend, no API key needed), driving four lunch scenarios through the Orchestrator:

  A. Cared-for replies "had a sandwich"           -> EATEN, no order
  B. Silence, confirm-first, countdown elapses    -> NO order (forgot-to-reply is SAFE)
  C. Silence, full-auto, countdown elapses        -> autonomous order placed
  D. Explicit "order for me" but daily cap blown  -> Guardian VETO, no order

Run:  python run_demo.py             # paced for recording (~52s)
      python run_demo.py --fast      # no delays
      python run_demo.py --speed 3   # stretch pauses 3x, to sit under a voiceover
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

# Windows consoles default to cp1252 and choke on emoji in the warm messages.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sentinel.llm import LLM
from sentinel.mcp_client import (FOOD_ENDPOINT_DEFAULT, TOOL_CART_UPDATE, TOOL_MENU,
                                 TOOL_ORDER, TOOL_SEARCH, TOOL_TRACK, get_food_client)
from sentinel.models import Profile, Store
from sentinel.notify import ConsoleChannel
from sentinel.agents.orchestrator import Orchestrator

WINDOW = "lunch"
WINDOW_LEN = 120.0  # minutes (12:30-14:30)
W = 76              # console width

FAST = "--fast" in sys.argv


def _speed_arg() -> float:
    """--speed N multiplies every pause, so the run can be stretched to sit
    under a fixed-length voiceover track."""
    if "--speed" in sys.argv:
        i = sys.argv.index("--speed")
        if i + 1 < len(sys.argv):
            return float(sys.argv[i + 1])
    return 1.0


SPEED = _speed_arg()


def pause(sec: float = 0.9):
    if not FAST:
        time.sleep(sec * SPEED)


# --- section timing manifest ------------------------------------------------
# `--timings marks.json` records the wall-clock offset of each narration
# section, so a voiceover clip can be muxed in at exactly the right moment.
_T0 = time.perf_counter()
_MARKS: list[dict] = []


def mark(section: str):
    _MARKS.append({"section": section, "at": round(time.perf_counter() - _T0, 2)})


def dump_marks():
    if "--timings" not in sys.argv:
        return
    i = sys.argv.index("--timings")
    if i + 1 >= len(sys.argv):
        return
    import json
    _MARKS.append({"section": "end", "at": round(time.perf_counter() - _T0, 2)})
    with open(sys.argv[i + 1], "w", encoding="utf-8") as fh:
        json.dump(_MARKS, fh, indent=2)


def rule(ch: str = "="):
    print(ch * W)


def card(title: str, subtitle: str = ""):
    print()
    rule()
    print(f" {title}")
    if subtitle:
        print(f" {subtitle}")
    rule()
    pause(1.2)


def fresh_orchestrator(profile: Profile, store: Store) -> Orchestrator:
    return Orchestrator(
        profile, store, get_food_client(), LLM(),
        cared_for_channel=ConsoleChannel(), caregiver_channel=ConsoleChannel(),
    )


def show_trace(store: Store, profile: Profile, day: str):
    print("\n  --- agent trace: who decided what ---")
    for t in store.traces_for(profile.person_id, day):
        print(f"    {t['agent']:<12} | {t['message']}")
        pause(0.25)


def verdict(text: str):
    print(f"\n  >> {text}")
    pause(1.4)


def run_scenario(title: str, point: str, profile: Profile,
                 ticks: list[tuple[float, str | None]], day: str, expect: str,
                 section: str = ""):
    if section:
        mark(section)
    card(title, point)
    store = Store(db_path=tempfile.mktemp(suffix=".db"))
    orch = fresh_orchestrator(profile, store)
    for elapsed, reply in ticks:
        tag = f"reply: {reply!r}" if reply else "(silence)"
        print(f"\n  [t+{elapsed:>3.0f}m] {tag}")
        pause(0.5)
        r = orch.tick(day, WINDOW, elapsed, WINDOW_LEN, reply)
        print(f"          -> {r.action.value}")
        pause(0.7)
    show_trace(store, profile, day)
    verdict(expect)
    store.close()


def intro(profile: Profile):
    mark("01_opening")
    online = "ONLINE (Claude)" if LLM().online else "OFFLINE (template fallback)"
    live = bool(os.getenv("SWIGGY_MCP_URL"))
    food = "LIVE Swiggy MCP" if live else "MOCK Swiggy Food server (no real orders)"

    card("SUSTENANCE SENTINEL",
         "An autonomous food-care agent crew on the Swiggy Food MCP")

    print(" The problem: people buried in work skip meals. Someone who loves them")
    print(" notices too late.")
    print()
    print(" Sentinel checks in during each meal window, and only if they genuinely")
    print(" have not eaten does it order a diet- and budget-safe meal for them.")
    pause(2.5)

    print("\n THE AGENT CREW")
    for line in [
        "  Orchestrator  runs the meal window, enforces caps + kill switch",
        "  Messenger     warm check-ins; parses free-text replies",
        "  Concierge     Swiggy Food MCP: search restaurants, read menus, build order",
        "  Guardian      code-enforced diet + budget gate (the model cannot override)",
        "  Notify        confirms back to the caregiver, writes the audit trace",
    ]:
        print(line)
        pause(0.4)

    print("\n SWIGGY FOOD MCP TOOLS WIRED")
    print(f"  endpoint: {FOOD_ENDPOINT_DEFAULT}  (streamable HTTP, OAuth 2.1 + PKCE)")
    print(f"  {TOOL_SEARCH} -> {TOOL_MENU} -> {TOOL_CART_UPDATE}")
    print(f"    -> {TOOL_ORDER} -> {TOOL_TRACK}")
    pause(2.0)

    print("\n THIS RUN")
    print(f"  Food backend : {food}")
    print(f"  Agent brains : {online}")
    print(f"  Cared-for    : {profile.name} ({profile.relationship}), veg, "
          f"caps ₹{profile.spend_cap_per_meal}/meal ₹{profile.spend_cap_per_day}/day")
    print(f"  Autonomy     : {profile.autonomy}")
    pause(2.5)

    mark("02_ladder")
    card("THE ESCALATION LADDER",
         "Why a forgotten reply can never trigger a wrong order")
    for line in [
        "  1. window opens      warm check-in     [Ate / Order for me / Skip]",
        "  2. +40 min silence   gentle nudge",
        "  3. near window end   last call + soft countdown",
        "  4. countdown ends    order ONLY if autonomy is full-auto",
        "",
        "  Silence is never read as 'they did not eat'. It becomes an explicit",
        "  opt-out window. In confirm-first mode, silence orders nothing.",
    ]:
        print(line)
        pause(0.45)
    pause(1.5)


def outro():
    mark("07_close")
    card("WHAT THE FOUR SCENARIOS SHOWED")
    for line in [
        "  A  replied 'had a sandwich'   -> understood, no order          SAFE",
        "  B  silence, confirm-first     -> nothing ordered               SAFE",
        "  C  silence, full-auto         -> comfort meal ordered, ₹260    WORKS",
        "  D  asked, but daily cap spent -> Guardian vetoed every dish    SAFE",
        "",
        "  Spend caps, one-order-per-window, and the kill switch live in code,",
        "  never in a prompt. place_food_order is called only from behind the",
        "  Guardian, never handed to the model directly.",
        "",
        "  15 tests cover the policy gate and the ladder transitions.",
        "  github.com/rksupreeth549-collab/sustenance-sentinel",
    ]:
        print(line)
        pause(0.5)
    print()
    rule()


def main():
    cfg = "config.yaml" if os.path.exists("config.yaml") else "config.example.yaml"
    profile = Profile.from_yaml(cfg)
    intro(profile)

    run_scenario(
        "SCENARIO A — she replies that she ate",
        "Free text, not a button. The Messenger has to understand it.",
        profile, [(0, None), (35, "had a sandwich at my desk")], "2026-07-20",
        "She ate. No order placed. The window closes quietly.", "03_scenario_a")

    run_scenario(
        "SCENARIO B — she never replies (confirm-first)",
        "The case everyone gets wrong: she simply forgot to answer.",
        profile, [(0, None), (45, None), (105, None), (125, None)], "2026-07-21",
        "Silence ordered NOTHING. No food arrives uninvited, no money spent.",
        "04_scenario_b")

    auto = Profile.from_yaml(cfg)
    auto.autonomy = "full-auto"
    run_scenario(
        "SCENARIO C — she never replies (full-auto, opted in)",
        "Same silence. She has explicitly opted into autonomy.",
        auto, [(0, None), (45, None), (105, None), (125, None)], "2026-07-22",
        "Concierge picked her comfort food, Guardian cleared it, order placed.",
        "05_scenario_c")

    scenario_cap_blown(profile)
    outro()
    dump_marks()


def scenario_cap_blown(profile: Profile):
    mark("06_scenario_d")
    card("SCENARIO D — she asks for food, but the day's budget is gone",
         "Guardian is code, not a prompt. It cannot be talked around.")
    day = "2026-07-23"
    store = Store(db_path=tempfile.mktemp(suffix=".db"))
    # Pre-load a breakfast order that eats the whole daily budget.
    store.record_order(profile.person_id, day, "breakfast", "Big Brunch",
                       "Big Brunch", profile.spend_cap_per_day, 30, "PRELOAD-1")
    print(f"\n  earlier today: breakfast already spent ₹{profile.spend_cap_per_day} "
          f"of the ₹{profile.spend_cap_per_day} daily cap")
    pause(1.2)
    orch = fresh_orchestrator(profile, store)
    print("\n  [t+ 10m] reply: 'order for me please'")
    pause(0.6)
    r = orch.tick(day, WINDOW, 10, WINDOW_LEN, "order for me please")
    print(f"          -> {r.action.value}")
    pause(0.7)
    show_trace(store, profile, day)
    verdict("Every candidate vetoed on budget. She was asked, not silently ignored.")
    store.close()


if __name__ == "__main__":
    main()
