# Sustenance Sentinel 🍱

An **autonomous food-care agent** built on the [Swiggy MCP servers](https://mcp.swiggy.com/builders/).

Not another "order me a pizza" bot. Sentinel looks after a **busy loved one** — a
partner, friend, or family member buried in work who skips meals. On a schedule it
sends a warm check-in, and **only if they genuinely haven't eaten** (after a careful
escalation ladder, so a *forgotten reply never triggers a wrong order*) it autonomously
orders a diet-safe meal from their favorite restaurant via Swiggy Food MCP, then pings
the caregiver.

A small **multi-agent crew** under one Orchestrator divides the work.

## The crew

| Agent | Job | Brain |
|-------|-----|-------|
| **Orchestrator** | Runs the meal-window workflow, enforces kill-switch + idempotency, routes to the crew | `claude-opus-4-8` |
| **Messenger** | Warm personalized check-ins/nudges/last-call in the caregiver's voice; parses free-text replies | `claude-sonnet-4-6` |
| **Concierge** | Searches favorite restaurants on Swiggy Food MCP, ranks a comfort-food candidate | `claude-opus-4-8` |
| **Guardian** | Deterministic diet + budget gate (`policy.py`); allow/deny is **code, never the model** | `claude-sonnet-4-6` |
| **Notify** | Composes the caregiver order summary + reasoning, persists the trace | `claude-sonnet-4-6` |

## The escalation ladder (the key idea)

A missed reply must **never** blind-order. Inside each meal window:

1. **T+0** — warm check-in with buttons: *Ate ✅ / Order for me 🍱 / Skip 🙅*
2. **+40m** — gentle nudge
3. **near window end** — soft-countdown last-call: *"ordering your usual in 15 min unless you tap Skip"*
4. **countdown elapses** — order only if **full-auto**; in **confirm-first** (pilot default) silence = **no order**

So "I forgot to reply" is safe by design.

## Run the offline demo (no API key, no network, no spend)

```bash
python -m pip install pyyaml pytest          # demo + tests need only these
python run_demo.py                           # 4 scenarios end-to-end on the MOCK Swiggy server
python -m pytest -q                          # 15 tests: policy + ladder
```

The demo shows: ate→no order, confirm-first silence→**safe no order**, full-auto
silence→autonomous order, daily-cap-blown→Guardian veto — each with the agent trace.

## Going live

Confirmed against https://mcp.swiggy.com/builders/docs/ :
- **Endpoint** `https://mcp.swiggy.com/food` — streamable HTTP, JSON-RPC.
- **Auth** OAuth 2.1 + PKCE; `http://localhost` redirect allowed for dev (phone + OTP).
- **Food tools (14)** — we use `search_restaurants`, `get_restaurant_menu`,
  `update_food_cart`, `place_food_order`, `track_food_order`. Order flow is cart-based.

Steps:
1. `cp .env.example .env`, set `ANTHROPIC_API_KEY` (agents use Claude vs templates).
2. Mint a token: `python -m sentinel.oauth` → paste into `SWIGGY_MCP_TOKEN`. Keep
   `SWIGGY_MCP_URL=https://mcp.swiggy.com/food`. (Confirm OAuth URLs at
   `/builders/docs/start/authenticate/`.)
3. `cp config.example.yaml config.yaml`, edit the cared-for profile.
4. Keep `autonomy: confirm-first` until trusted. Production access needs Swiggy's
   use-case + security review (apply at `/builders/access/` with a demo video).

> **Security:** `place_food_order` runs only inside our code path, behind the
> Guardian. We deliberately do **not** expose it to Claude's native MCP connector —
> letting the model place orders directly would bypass the code-enforced spend caps.

## Safety rails

- **Spend caps in code** (`policy.py`), per-meal + per-day — never the model's call.
- **One order per window** — DB unique key `person_id+day+window`.
- **No-blind-order** — silence routes to the opt-out countdown, not an instant order.
- **Kill switch** checked before every order (toggle from the dashboard).
- **Mock-first** — runs fully offline so you never spend real money while building.

## Optional dashboard

```bash
python -m pip install fastapi uvicorn
uvicorn sentinel.dashboard:app --reload      # today's windows, order log, reasoning replay, kill switch
```

## Layout

```
sentinel/
  models.py        profile config + SQLite (state, orders, agent trace)
  policy.py        Guardian's deterministic diet/budget core (pure)
  ladder.py        escalation-ladder state machine (pure)
  mcp_client.py    Swiggy Food MCP client + offline MOCK backend
  notify.py        console / telegram / twilio transport + quick-reply buttons
  llm.py           Anthropic wrapper (offline fallback)
  scheduler.py     meal-window + ladder timers (APScheduler)
  dashboard.py     optional FastAPI caregiver view
  agents/          orchestrator, messenger, concierge, guardian, notify_agent
tests/             test_policy.py, test_ladder.py
run_demo.py        end-to-end offline demo
config.example.yaml
```

## Stretch

Multi-server orchestration — after lunch, Instamart auto-restocks staples; Dineout
books a weekend table when the caregiver visits. Richer "did they eat" signals
(smart-plug kettle, wearable, door sensor).
