"""Live proof against the real Swiggy Food MCP — READ ONLY.

Runs the whole Sentinel pipeline on live data without spending anything:
  1. OAuth 2.1 + PKCE token (self-registered via Dynamic Client Registration)
  2. JSON-RPC handshake, then tools/list
  3. get_addresses, and pick one that is actually serviceable
  4. search_restaurants for the profile's favourites
  5. get_restaurant_menu on a real restaurant
  6. Concierge ranking + Guardian gate over that LIVE menu, printing what
     Sentinel *would* order

It never calls place_food_order. Ordering additionally requires
SWIGGY_ALLOW_REAL_ORDERS=1, which this script does not set.

Addresses and phone numbers are redacted by default so the output is safe to
screen-record. Pass --show-pii to see them in full.

Run:  python verify_live.py
"""
from __future__ import annotations

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sentinel.agents.concierge import Concierge
from sentinel.agents.guardian import Guardian
from sentinel.mcp_client import FOOD_ENDPOINT_DEFAULT, SwiggyFoodMCP
from sentinel.models import Profile
from sentinel.oauth import get_token

SHOW_PII = "--show-pii" in sys.argv
W = 76


def redact(text: str) -> str:
    """Keep the locality, drop the street address — safe for a public video."""
    if SHOW_PII:
        return text
    text = re.sub(r"\b\d{6}\b", "######", text)          # PIN codes
    text = re.sub(r"\b\d{7,}\b", "*******", text)         # long digit runs
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 3:                                    # keep the tail only
        return "[redacted], " + ", ".join(parts[-3:])
    return "[redacted]"


def step(n: int, msg: str):
    print(f"\n[{n}] {msg}")


def main() -> int:
    cfg = "config.yaml" if os.path.exists("config.yaml") else "config.example.yaml"
    profile = Profile.from_yaml(cfg)
    url = os.getenv("SWIGGY_MCP_URL", FOOD_ENDPOINT_DEFAULT)

    print("=" * W)
    print(" SUSTENANCE SENTINEL — LIVE against the real Swiggy Food MCP")
    print(f" {url}")
    print(" READ ONLY. This script never places an order.")
    print("=" * W)

    step(1, "OAuth 2.1 + PKCE (client self-registered via DCR)")
    token = get_token(interactive=True)
    if not token:
        print("    FAIL: no token. Run `python -m sentinel.oauth` first.")
        return 1
    print(f"    ok: bearer token ({len(token)} chars)")

    client = SwiggyFoodMCP(url, token)

    step(2, "JSON-RPC handshake + tools/list")
    try:
        tools = client.list_tools()
    except Exception as e:
        print(f"    FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"    ok: server advertises {len(tools)} tools")
    for i in range(0, len(tools), 3):
        print("      " + "  ".join(f"{t:<26}" for t in tools[i:i + 3]).rstrip())

    step(3, "get_addresses -> pick a serviceable one")
    try:
        addrs = client.get_addresses()
        print(f"    {len(addrs)} saved address(es) on the account")
        chosen = client.autoselect_address(profile.favorite_restaurants)
    except Exception as e:
        print(f"    FAIL: {type(e).__name__}: {e}")
        return 1
    if not chosen:
        print("    FAIL: none of the saved addresses serve the profile's favourites.")
        return 1
    print(f"    using: {redact(chosen['addressLine'])}")
    print("    (a hometown address had no delivery coverage — Sentinel scores each")
    print("     saved address by how many favourites it actually serves)")

    step(4, f"search_restaurants for {profile.favorite_restaurants}")
    for fav in profile.favorite_restaurants:
        try:
            hits = client.search_restaurants(fav)
            print(f"    {fav!r:<24} -> {len(hits)} open now")
        except Exception as e:
            print(f"    WARN {fav!r}: {type(e).__name__}: {e}")

    step(5, "get_restaurant_menu (live)")
    ids = client.search_restaurants(profile.favorite_restaurants[-1])
    if not ids:
        print("    FAIL: no open restaurant to read a menu from.")
        return 1
    menu = client.get_menu(ids[0])
    print(f"    ok: {len(menu)} in-stock item(s) from {menu[0].restaurant}")
    for d in menu[:6]:
        print(f"      {d.item[:36]:<36} ₹{d.price:<5} veg={str(d.vegetarian):<5}")

    step(6, "Concierge ranking + Guardian gate over the LIVE menu (dry run)")
    concierge = Concierge(client, profile)
    candidates = concierge.candidates("")
    print(f"    Concierge ranked {len(candidates)} live candidate(s)")
    verdict = Guardian(profile).review(candidates, spent_today=0)
    for cand, dec in verdict.vetoed:
        print(f"      VETO  {cand.item[:34]:<34} — {dec.reasons[0]}")
    if verdict.approved:
        c = verdict.approved
        print(f"\n    WOULD ORDER: {c.item} from {c.restaurant} — ₹{c.price}")
        print("    NOT PLACED — this script is read only, and live ordering also")
        print("    requires SWIGGY_ALLOW_REAL_ORDERS=1.")
    else:
        print("\n    Guardian approved nothing on this menu under the current profile.")

    print("\n" + "=" * W)
    print(" Live check complete. Real data, real tools, no order placed.")
    print("=" * W)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
