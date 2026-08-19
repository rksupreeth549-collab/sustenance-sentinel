# Voiceover narration — Sustenance Sentinel demo (v2, live build)

Two recorded segments, concatenated:

| Segment | Command | Length |
|---|---|---|
| **A — Live** | `verify_live.py --dwell 13 --timings live_marks.json` | ~84 s |
| **B — Safety** | `run_demo.py --speed 2 --timings mock_marks.json` | ~106 s |

Total ≈ **3 min 10 s**.

**Hard rule: every clip must be SHORTER than its budget.** Measure each generated
file and regenerate anything that runs over. Clips must never overlap.

> Segment A talks to the real Swiggy server, so its step timings shift with
> network latency. **Always place segment A's audio using the `live_marks.json`
> written by the take you actually recorded**, not the numbers below.
> Segment B is deterministic and scales linearly with `--speed`.

Voice: male, Indian English if available, calm and conversational — a builder
walking someone through their work, not an advertisement.

---

## Segment A — live against the real Swiggy Food MCP

| # | Section id | Starts | Budget |
|---|---|---|---|
| A1 | `live_01` | 0:00 | 13.0 s |
| A2 | `live_02` | 0:13 | 13.0 s |
| A3 | `live_03` | 0:26 | 19.1 s* |
| A4 | `live_04` | 0:45 | 13.0 s |
| A5 | `live_05` | 0:58 | 13.0 s |
| A6 | `live_06` | 1:11 | 13.0 s |

\* varies with network; trust the recorded manifest.

### A1 — `live_01` (13.0 s)

This is Sustenance Sentinel, running against the real Swiggy Food MCP. It authenticates with OAuth 2.1 and PKCE, registering itself dynamically, so there's no client ID to request from anyone.

### A2 — `live_02` (13.0 s)

Handshake, then tools list. Eighteen live tools come back — one more than the docs describe. Discovery, cart, coupons, payment, and order tracking.

### A3 — `live_03` (13.0 s — do not exceed, slot may be longer)

Now my real saved addresses. One of them is my hometown, which has no delivery coverage at all, so Sentinel scores each address by how many of your favourites it actually serves, and pins the best one.

### A4 — `live_04` (13.0 s)

Searching my actual favourite restaurants through the live server. Ten open near that address for each. Everything closed right now is filtered out.

### A5 — `live_05` (13.0 s)

A real menu, live. Twenty-one in-stock items with real prices and real veg flags. The API exposes no calories or spice, so those rules simply stand down rather than guessing.

### A6 — `live_06` (13.0 s)

And the whole pipeline on live data. The Concierge ranked over a hundred real dishes, the Guardian cleared one on diet and budget. Nothing was ordered — this path is read only.

---

## Segment B — the safety behaviour (deterministic, offline)

Offsets are from `run_demo.py --speed 2`. Add segment A's total length when
placing these on the concatenated timeline.

| # | Section id | Starts (in B) | Budget |
|---|---|---|---|
| B1 | `01_opening` | 0:00 | 20.4 s |
| B2 | `02_ladder` | 0:20 | 11.7 s |
| B3 | `03_scenario_a` | 0:32 | 11.6 s |
| B4 | `04_scenario_b` | 0:44 | 16.8 s |
| B5 | `05_scenario_c` | 1:00 | 17.9 s |
| B6 | `06_scenario_d` | 1:18 | 14.3 s |
| B7 | `07_close` | 1:33 | 13.4 s |

### B1 — `01_opening` (20.4 s)

That's the plumbing. This is the point of it. People buried in work skip meals, and whoever loves them finds out too late. Five agents do the work: an orchestrator, a messenger, the concierge that talks to Swiggy, a guardian, and notify.

### B2 — `02_ladder` (11.7 s)

Here's what I care about most. If she doesn't reply, we never assume she's hungry. Silence walks through a check-in, a nudge, then a countdown.

### B3 — `03_scenario_a` (11.6 s)

She types "had a sandwich at my desk" — free text, not a button. The messenger understands it, the window closes, nothing is ordered.

### B4 — `04_scenario_b` (16.8 s)

This is the one everybody gets wrong. She simply forgets to reply. Check-in, nudge, last call, countdown expires — and nothing is ordered. Silence is never treated as consent.

### B5 — `05_scenario_c` (17.9 s)

Same silence, but here she's opted into full autonomy. The concierge picks her comfort food, the guardian clears it on diet and budget, the order goes through, and her partner gets the confirmation with an ETA.

### B6 — `06_scenario_d` (14.3 s)

Now she asks for food, but breakfast already spent the daily cap. The guardian vetoes every candidate. That gate is plain Python, not a prompt, so the model cannot talk its way around it.

### B7 — `07_close` (13.4 s)

Order placement sits behind that gate and is never handed to the model directly. Fifteen tests cover the policy and the ladder. The code is public. Thanks for taking a look.
