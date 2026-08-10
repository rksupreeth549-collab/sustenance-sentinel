"""Phase 1 live check against the real Swiggy Food MCP — READ ONLY.

Proves the whole pipeline works on live data without spending anything:
  1. OAuth token present (runs the PKCE flow if needed)
  2. Connect and list the tools the server actually advertises
  3. get_addresses
  4. search_restaurants for the profile's favourites
  5. get_restaurant_menu on the first hit
  6. Run the Concierge ranking + Guardian gate over that LIVE menu, and print
     what Sentinel *would* have ordered.

It never calls place_food_order. Ordering additionally requires
SWIGGY_ALLOW_REAL_ORDERS=1, which this script does not set.

Run:  python verify_live.py
"""
from __future__ import annotations

import os
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

EXPECTED = [
    "get_addresses", "search_restaurants", "get_restaurant_menu", "search_menu",
    "get_food_cart", "update_food_cart", "flush_food_cart",
    "fetch_food_coupons", "apply_food_coupon",
    "place_food_order", "get_payment_options", "check_payment_status",
    "confirm_order", "get_food_orders", "get_food_order_details",
    "track_food_order", "report_error",
]


def step(n: int, msg: str):
    print(f"\n[{n}] {msg}")


def main() -> int:
    cfg = "config.yaml" if os.path.exists("config.yaml") else "config.example.yaml"
    profile = Profile.from_yaml(cfg)
    url = os.getenv("SWIGGY_MCP_URL", FOOD_ENDPOINT_DEFAULT)
    print(f"Swiggy Food MCP live check -> {url}")
    print("READ ONLY. This script never places an order.")

    step(1, "OAuth token")
    token = get_token(interactive=True)
    if not token:
        print("    FAIL: no token. Run `python -m sentinel.oauth` first.")
        return 1
    print(f"    ok: bearer token present ({len(token)} chars)")

    client = SwiggyFoodMCP(url, token)

    step(2, "Connect + list tools")
    try:
        tools = client.list_tools()
    except Exception as e:
        print(f"    FAIL: could not connect: {type(e).__name__}: {e}")
        return 1
    print(f"    ok: server advertises {len(tools)} tools")
    missing = [t for t in EXPECTED if t not in tools]
    extra = [t for t in tools if t not in EXPECTED]
    if missing:
        print(f"    WARN: expected but absent: {missing}")
    if extra:
        print(f"    note: additional tools available: {extra}")

    step(3, "get_addresses")
    try:
        addrs = client.get_addresses()
        print(f"    ok: {len(addrs)} saved address(es)")
        for a in addrs[:3]:
            print(f"      - {a}")
    except Exception as e:
        print(f"    WARN: {type(e).__name__}: {e}")
        addrs = []

    area = profile.address.get("text", "")
    if addrs and isinstance(addrs[0], dict):
        area = addrs[0].get("address", addrs[0].get("text", area))

    step(4, f"search_restaurants for {profile.favorite_restaurants}")
    found: list[str] = []
    for fav in profile.favorite_restaurants:
        try:
            hits = client.search_restaurants(fav, area)
            print(f"    '{fav}' -> {len(hits)} hit(s): {hits[:3]}")
            found.extend(hits)
        except Exception as e:
            print(f"    WARN '{fav}': {type(e).__name__}: {e}")
    if not found:
        print("    No restaurants resolved; cannot continue to the menu step.")
        return 1

    step(5, f"get_restaurant_menu for {found[0]}")
    try:
        menu = client.get_menu(found[0])
        print(f"    ok: {len(menu)} item(s). Sample:")
        for d in menu[:5]:
            print(f"      - {d.item:<40} ₹{d.price:<5} veg={d.vegetarian} tags={d.tags}")
    except Exception as e:
        print(f"    FAIL: {type(e).__name__}: {e}")
        return 1

    step(6, "Concierge ranking + Guardian gate over the LIVE menu (dry run)")
    concierge = Concierge(client, profile)
    candidates = concierge.candidates(area)
    print(f"    Concierge ranked {len(candidates)} candidate(s)")
    verdict = Guardian(profile).review(candidates, spent_today=0)
    for cand, dec in verdict.vetoed:
        print(f"      VETO  {cand.item} — {'; '.join(dec.reasons)}")
    if verdict.approved:
        c = verdict.approved
        print(f"\n    WOULD ORDER: {c.item} from {c.restaurant} — ₹{c.price}")
        print("    (not placed — this script is read only)")
    else:
        print("\n    Guardian approved nothing on this menu under the current profile.")

    print("\nLive check complete. No order was placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
