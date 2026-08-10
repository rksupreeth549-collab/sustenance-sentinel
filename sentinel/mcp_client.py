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
from contextlib import asynccontextmanager
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
#         -> update_food_cart -> place_food_order -> get_payment_options
#         -> confirm_order / check_payment_status -> track_food_order
#   * Full Food surface is 17 tools; the rest we don't need yet are listed below.
#
# SECURITY: order placement stays in OUR code path, behind the Guardian. We do NOT
# hand `place_food_order` to Claude's native MCP connector — letting the model call
# it directly would bypass the code-enforced spend caps in policy.py.
FOOD_ENDPOINT_DEFAULT = "https://mcp.swiggy.com/food"

# Discover
TOOL_ADDRESSES = "get_addresses"
TOOL_SEARCH = "search_restaurants"
TOOL_MENU = "get_restaurant_menu"
TOOL_SEARCH_MENU = "search_menu"
# Cart
TOOL_CART_GET = "get_food_cart"
TOOL_CART_UPDATE = "update_food_cart"
TOOL_CART_FLUSH = "flush_food_cart"
# Order + payment
TOOL_ORDER = "place_food_order"
TOOL_PAYMENT_OPTIONS = "get_payment_options"
TOOL_PAYMENT_STATUS = "check_payment_status"
TOOL_CONFIRM = "confirm_order"
# Tracking
TOOL_TRACK = "track_food_order"

# Live ordering moves real money on a real Swiggy account. It stays off unless
# the operator explicitly turns it on for this process.
ALLOW_REAL_ORDERS = os.getenv("SWIGGY_ALLOW_REAL_ORDERS", "") == "1"


class SwiggyFoodMCP:
    """Streamable-HTTP MCP client for the live Swiggy Food server.

    Sync wrapper over the async `mcp` SDK (one asyncio.run per call — fine at
    pilot scale). Needs a bearer token from the OAuth 2.1 + PKCE flow; see
    `sentinel/oauth.py` for acquiring one (browser phone+OTP, localhost redirect).
    """

    def __init__(self, url: str, token: str | None = None):
        self.url = url or FOOD_ENDPOINT_DEFAULT
        if not token:
            # Falls back to the cached OAuth token; won't pop a browser here.
            from .oauth import get_token
            token = get_token(interactive=False)
        self.token = token

    # -- async core -------------------------------------------------------
    # MCP SDK 2.x: `streamable_http_client` takes a preconfigured httpx2 client
    # (there is no `headers=` kwarg) and yields a 2-tuple.
    @asynccontextmanager
    async def _session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import (create_mcp_http_client,
                                                streamable_http_client)

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with create_mcp_http_client(headers=headers) as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    async def _call(self, tool: str, args: dict):
        async with self._session() as session:
            result = await session.call_tool(tool, args)
            return result.structuredContent or result.content

    def _run(self, tool: str, args: dict):
        import asyncio
        return asyncio.run(self._call(tool, args))

    def list_tools(self) -> list[str]:
        """Names the live server actually advertises — used to verify wiring."""
        import asyncio

        async def _go():
            async with self._session() as session:
                return [t.name for t in (await session.list_tools()).tools]

        return asyncio.run(_go())

    @staticmethod
    def _rows(res, *keys):
        """Live responses wrap their list under one of several keys."""
        if isinstance(res, dict):
            for k in keys:
                if isinstance(res.get(k), list):
                    return res[k]
        return res if isinstance(res, list) else []

    # -- FoodClient interface (shapes normalized from live responses) --
    def get_addresses(self) -> list[dict]:
        return self._rows(self._run(TOOL_ADDRESSES, {}), "addresses", "data")

    def search_restaurants(self, query: str, area: str) -> list[str]:
        res = self._run(TOOL_SEARCH, {"query": query, "location": area})
        out = []
        for r in self._rows(res, "restaurants", "results", "data"):
            # Keep the id when present — get_restaurant_menu wants an id, not a name.
            out.append(str(r.get("id") or r.get("restaurant_id") or r.get("name")))
        return out

    def get_menu(self, restaurant: str) -> list[Dish]:
        res = self._run(TOOL_MENU, {"restaurant_id": restaurant})
        out: list[Dish] = []
        for it in self._rows(res, "items", "menu", "data"):
            price = it.get("price", it.get("final_price", 0))
            out.append(Dish(
                restaurant=restaurant, item=it.get("name", "?"),
                price=int(float(price)),
                tags=it.get("tags", []) or it.get("categories", []),
                calories=it.get("calories"),
                spice=it.get("spice", 0),
                vegetarian=bool(it.get("is_veg", it.get("veg", True))),
            ))
        return out

    def place_order(self, restaurant: str, dish: Dish, address: str) -> OrderResult:
        """Cart -> place -> pay. Refuses to run unless real ordering is enabled."""
        if not ALLOW_REAL_ORDERS:
            raise PermissionError(
                "Refusing to place a REAL Swiggy order: SWIGGY_ALLOW_REAL_ORDERS is not "
                "set to 1. This would spend real money on a real account."
            )
        self._run(TOOL_CART_FLUSH, {})  # start clean; stale carts corrupt the total
        self._run(TOOL_CART_UPDATE, {
            "restaurant_id": restaurant,
            "items": [{"name": dish.item, "quantity": 1}],
        })
        placed = self._run(TOOL_ORDER, {"address": address})
        order_id = placed.get("order_id") or placed.get("id")

        # v1 payment surface: cash goes straight through, UPI needs polling.
        if placed.get("requires_payment") or placed.get("status") == "payment_pending":
            opts = self._rows(self._run(TOOL_PAYMENT_OPTIONS, {"order_id": order_id}),
                              "options", "payment_options", "data")
            cash = next((o for o in opts
                         if "cash" in str(o.get("type", o.get("name", ""))).lower()), None)
            if not cash:
                raise RuntimeError(
                    f"Order {order_id} needs an online payment; Sentinel only "
                    f"auto-completes cash-on-delivery. Options: {opts}"
                )
            self._run(TOOL_CONFIRM, {"order_id": order_id,
                                     "payment_method": cash.get("type", "cash")})

        return OrderResult(
            order_ref=str(order_id),
            total=int(float(placed.get("total", dish.price))),
            eta_min=int(placed.get("eta_min", placed.get("eta", 0)) or 0),
            restaurant=restaurant, item=dish.item,
        )

    def track(self, order_id: str) -> dict:
        return self._run(TOOL_TRACK, {"order_id": order_id})


def get_food_client() -> FoodClient:
    url = os.getenv("SWIGGY_MCP_URL", "").strip()
    if url:
        return SwiggyFoodMCP(url, os.getenv("SWIGGY_MCP_TOKEN"))
    return MockSwiggyFood()
