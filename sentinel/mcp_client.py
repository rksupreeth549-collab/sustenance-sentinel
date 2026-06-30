"""Swiggy Food MCP client.

Two backends behind one interface:
  * SwiggyFoodMCP  — talks to the real Swiggy Food MCP server (localhost dev per
    https://mcp.swiggy.com/builders/). Tool names are config-driven because the
    exact schema is confirmed in Phase 1 against the live server.
  * MockSwiggyFood — offline sample restaurants/menus so the whole pilot (and
    the demo + tests) runs with zero network and zero spend.

`get_food_client()` picks the backend from env (SWIGGY_MCP_URL).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Dish:
    restaurant: str
    item: str
    price: int
    tags: list[str] = field(default_factory=list)
    calories: int | None = None
    spice: int = 0
    vegetarian: bool = True


@dataclass
class OrderResult:
    order_ref: str
    total: int
    eta_min: int
    restaurant: str
    item: str


class FoodClient(Protocol):
    def search_restaurants(self, query: str, area: str) -> list[str]: ...
    def get_menu(self, restaurant: str) -> list[Dish]: ...
    def place_order(self, restaurant: str, dish: Dish, address: str) -> OrderResult: ...


# --- Mock backend ---------------------------------------------------------
_MOCK_MENUS: dict[str, list[Dish]] = {
    "Punjabi By Nature": [
        Dish("Punjabi By Nature", "Dal Makhani + 2 Roti", 320,
             ["north-indian", "comfort"], calories=620, spice=1, vegetarian=True),
        Dish("Punjabi By Nature", "Paneer Butter Masala + Rice", 380,
             ["north-indian", "comfort"], calories=720, spice=2, vegetarian=True),
        Dish("Punjabi By Nature", "Butter Chicken + Naan", 450,
             ["north-indian", "non-veg"], calories=820, spice=2, vegetarian=False),
        Dish("Punjabi By Nature", "Gulab Jamun (2 pc)", 140,
             ["dessert", "sugary-drink"], calories=380, spice=0, vegetarian=True),
    ],
    "FreshMenu": [
        Dish("FreshMenu", "Grilled Paneer Power Bowl", 330,
             ["healthy-bowls", "comfort"], calories=560, spice=1, vegetarian=True),
        Dish("FreshMenu", "Khichdi Comfort Bowl", 260,
             ["healthy-bowls", "comfort"], calories=480, spice=0, vegetarian=True),
        Dish("FreshMenu", "Crispy Fried Chicken Bowl", 360,
             ["fried", "non-veg"], calories=780, spice=2, vegetarian=False),
        Dish("FreshMenu", "Cold Coffee", 180,
             ["sugary-drink"], calories=320, spice=0, vegetarian=True),
    ],
}


class MockSwiggyFood:
    def search_restaurants(self, query: str, area: str) -> list[str]:
        q = query.lower()
        hits = [name for name in _MOCK_MENUS if q in name.lower()]
        return hits or list(_MOCK_MENUS.keys())

    def get_menu(self, restaurant: str) -> list[Dish]:
        return list(_MOCK_MENUS.get(restaurant, []))

    def place_order(self, restaurant: str, dish: Dish, address: str) -> OrderResult:
        return OrderResult(
            order_ref="MOCK-" + uuid.uuid4().hex[:8].upper(),
            total=dish.price,
            eta_min=32,
            restaurant=restaurant,
            item=dish.item,
        )


# --- Real backend ---------------------------------------------------------
# Confirmed from https://mcp.swiggy.com/builders/docs/ :
#   * Endpoint   : POST https://mcp.swiggy.com/food  (streamable HTTP, JSON-RPC)
#   * Auth       : OAuth 2.1 + PKCE; http://localhost redirect allowed for dev.
#   * Food server: 14 tools. The ones we use, and the real cart-based order flow:
#       search_restaurants -> get_restaurant_menu / search_menu
#         -> update_food_cart (add items) -> place_food_order -> track_food_order
#       (also: get_addresses, get_food_cart, flush_food_cart, *_coupon, report_error)
#
# SECURITY: order placement stays in OUR code path, behind the Guardian. We do NOT
# hand `place_food_order` to Claude's native MCP connector — letting the model call
# it directly would bypass the code-enforced spend caps in policy.py.
FOOD_ENDPOINT_DEFAULT = "https://mcp.swiggy.com/food"

TOOL_SEARCH = "search_restaurants"
TOOL_MENU = "get_restaurant_menu"
TOOL_CART_UPDATE = "update_food_cart"
TOOL_ORDER = "place_food_order"
TOOL_TRACK = "track_food_order"


class SwiggyFoodMCP:
    """Streamable-HTTP MCP client for the live Swiggy Food server.

    Sync wrapper over the async `mcp` SDK (one asyncio.run per call — fine at
    pilot scale). Needs a bearer token from the OAuth 2.1 + PKCE flow; see
    `sentinel/oauth.py` for acquiring one (browser phone+OTP, localhost redirect).
    """

    def __init__(self, url: str, token: str | None = None):
        self.url = url or FOOD_ENDPOINT_DEFAULT
        self.token = token

    # -- async core: open a session, call one tool, return its structured result --
    async def _call(self, tool: str, args: dict):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        async with streamablehttp_client(self.url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                return result.structuredContent or result.content

    def _run(self, tool: str, args: dict):
        import asyncio
        return asyncio.run(self._call(tool, args))

    # -- FoodClient interface (shapes normalized from live responses) --
    def search_restaurants(self, query: str, area: str) -> list[str]:
        res = self._run(TOOL_SEARCH, {"query": query, "location": area})
        return [r["name"] for r in res.get("restaurants", res)]

    def get_menu(self, restaurant: str) -> list[Dish]:
        res = self._run(TOOL_MENU, {"restaurant_id": restaurant})
        out: list[Dish] = []
        for it in res.get("items", res):
            out.append(Dish(
                restaurant=restaurant, item=it["name"], price=int(it["price"]),
                tags=it.get("tags", []), calories=it.get("calories"),
                spice=it.get("spice", 0), vegetarian=it.get("is_veg", True),
            ))
        return out

    def place_order(self, restaurant: str, dish: Dish, address: str) -> OrderResult:
        # Real flow is cart-based: add to cart, then confirm the order.
        self._run(TOOL_CART_UPDATE, {
            "restaurant_id": restaurant,
            "items": [{"name": dish.item, "quantity": 1}],
        })
        res = self._run(TOOL_ORDER, {"address": address})
        return OrderResult(
            order_ref=res["order_id"],
            total=int(res.get("total", dish.price)),
            eta_min=int(res.get("eta_min", 0)),
            restaurant=restaurant, item=dish.item,
        )


def get_food_client() -> FoodClient:
    url = os.getenv("SWIGGY_MCP_URL", "").strip()
    if url:
        return SwiggyFoodMCP(url, os.getenv("SWIGGY_MCP_TOKEN"))
    return MockSwiggyFood()
