# Voiceover narration — Sustenance Sentinel demo

Seven clips, one per section. Each is written to fit inside its section's slot in
the paced demo run at `--speed 3` (total video ≈ 2 min 39 s).

**Hard rule: a clip must not be longer than its budget.** If a generated clip runs
over, regenerate it slightly faster or trim a sentence — do not let clips overlap.

Offsets below are from `marks.json`, produced by:

```
python run_demo.py --speed 3 --timings marks.json
```

Regenerate that file rather than trusting these numbers if anything changes.

| # | Section id | Starts at | Budget |
|---|------------|-----------|--------|
| 1 | `01_opening`    | 0:00.0 | 30.6 s |
| 2 | `02_ladder`     | 0:30.6 | 17.6 s |
| 3 | `03_scenario_a` | 0:48.2 | 17.3 s |
| 4 | `04_scenario_b` | 1:05.5 | 25.3 s |
| 5 | `05_scenario_c` | 1:30.8 | 26.8 s |
| 6 | `06_scenario_d` | 1:57.6 | 21.4 s |
| 7 | `07_close`      | 2:19.0 | 20.1 s |

Voice: male, Indian English if available, calm and conversational — a builder
walking someone through their project, not an advertisement.

---

### 1 — `01_opening` @ 0:00.0 (30.6 s)

Hi, I'm Supreeth. This is Sustenance Sentinel, built on the Swiggy Food MCP. The problem is simple: people buried in work skip meals, and the person who loves them finds out too late. Sentinel checks in during every meal window, and only if they genuinely haven't eaten does it order something safe. Five agents do the work. An Orchestrator runs the window, a Messenger writes the check-ins, the Concierge talks to Swiggy, a Guardian enforces diet and budget in code, and Notify closes the loop.

### 2 — `02_ladder` @ 0:30.6 (17.6 s)

This is the part I care most about. If she doesn't reply, we never assume she's hungry. Silence walks through a check-in, a nudge, then a last call with a countdown. That turns silence into an explicit opt-out.

### 3 — `03_scenario_a` @ 0:48.2 (17.3 s)

Scenario A. She types "had a sandwich at my desk" — free text, not a button. The Messenger understands it, the window closes, and nothing gets ordered. Every decision is written to an audit trace you can replay.

### 4 — `04_scenario_b` @ 1:05.5 (25.3 s)

Scenario B is the one everybody gets wrong. She simply forgets to reply. Check-in, nudge, last call, the countdown expires — and nothing is ordered. No food shows up uninvited, no money moves. In confirm-first mode, silence is never treated as consent. This is the failure mode I designed the whole system around.

### 5 — `05_scenario_c` @ 1:30.8 (26.8 s)

Same silence in Scenario C, but here she has explicitly opted into full autonomy. Now the Concierge searches her favourite restaurants through the Swiggy Food MCP, reads the menus, and ranks toward her comfort food. The Guardian clears it on diet and budget. The order goes through — a khichdi bowl, two hundred and sixty rupees — and her partner gets the confirmation with an ETA.

### 6 — `06_scenario_d` @ 1:57.6 (21.4 s)

Scenario D. She asks for food, but breakfast already spent the daily cap. The Guardian vetoes every single candidate. That gate is plain Python, not a prompt, so the model cannot talk its way around it. Order placement is only ever called from behind the Guardian.

### 7 — `07_close` @ 2:19.0 (20.1 s)

Today this runs against a mock Swiggy backend, so no real orders fire while I build, with fifteen tests over the policy gate and the ladder. The client is already wired to the documented spec — streamable HTTP, OAuth 2.1 with PKCE. The code is public. Thanks for taking a look.
