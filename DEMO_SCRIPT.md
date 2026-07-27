# Demo recording script — Sustenance Sentinel

Target length: **~3 minutes**. Audience: Swiggy Builders Club engineering team.

## Before you hit record

```bash
cd "C:/Users/Admin/Desktop/Projects/Swiggy Pilot Project"
```

- Maximize the terminal, font size up (Ctrl+Scroll) so text is readable in the video.
- Dark theme, clear the screen first.
- Have the GitHub repo open in a second tab for the final shot.
- Use `python run_demo.py` (paced). Add `--fast` only if you want a shorter cut.

Windows: use the real interpreter —
`C:/Users/Admin/AppData/Local/Python/pythoncore-3.14-64/python.exe run_demo.py`

## Shot list

**1. Opening (~20s) — terminal, before running**

> "Hi, I'm Supreeth. This is Sustenance Sentinel, built on the Swiggy Food MCP.
> The idea is simple: people buried in work skip meals, and the person who loves
> them finds out too late. Sentinel checks in during each meal window, and only
> if they genuinely haven't eaten does it order them something safe to eat."

Run the demo. Let the title card and agent crew list render.

**2. Architecture (~30s) — while the crew + tools cards are on screen**

> "It's a multi-agent crew. An Orchestrator runs the meal window. A Messenger
> writes the check-ins and reads free-text replies. The Concierge is the one
> touching Swiggy — search_restaurants, get_restaurant_menu, update_food_cart,
> place_food_order. The Guardian is a code-enforced diet and budget gate, and
> Notify closes the loop with the caregiver."

**3. The escalation ladder (~25s) — on the ladder card**

> "This is the part I care most about. If she doesn't reply, we do not assume
> she's hungry. Silence walks through a check-in, a nudge, then a last call with
> a countdown — which turns silence into an explicit opt-out. In confirm-first
> mode, silence orders nothing at all."

**4. Scenarios A and B (~45s)**

> Scenario A: "She types 'had a sandwich at my desk' — free text, not a button.
> The Messenger understands it and the window closes. No order."

> Scenario B: "Now she just forgets to reply. Check-in, nudge, last call,
> countdown expires — and nothing is ordered. No food shows up uninvited, no
> money spent. This is the failure mode I designed around."

**5. Scenario C (~30s)**

> "Same silence, but she's explicitly opted into full autonomy. The Concierge
> pulls her favourites off the menu, ranks toward her comfort food, the Guardian
> clears it on diet and budget, and the order goes through — khichdi bowl, 260
> rupees. Her partner gets the confirmation with the ETA."

**6. Scenario D + safety (~30s)**

> "Last one. She asks for food, but breakfast already spent the daily cap. The
> Guardian vetoes every single candidate. That gate is plain Python, not a
> prompt — the model can't talk its way around it. place_food_order is only ever
> called from behind the Guardian; I deliberately don't expose it to the model's
> native MCP connector, because that would bypass the spend caps."

**7. Close (~20s) — cut to the repo**

> "It runs today against a mock Swiggy backend so no real orders fire while I
> build, with 15 tests over the policy gate and the ladder. The client is already
> wired to the documented spec — streamable HTTP, OAuth 2.1 with PKCE. The one
> thing I need is a development client_id to run the localhost OAuth flow against
> the live Food server. Code's all public. Thanks for taking a look."

## Recording tools

- **Windows built-in:** `Win + Alt + R` (Xbox Game Bar) records the active window.
- **Better:** OBS Studio, or ScreenPal / Loom for a quick share link.
- Upload to Google Drive / YouTube unlisted / Loom, then reply to their email
  with the link.
