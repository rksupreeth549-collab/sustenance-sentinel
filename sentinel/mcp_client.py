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


# --- Real backend (Phase 1 wiring) ----------------------------------------
class SwiggyFoodMCP:
    """Thin wrapper over an MCP session to the Swiggy Food server.

    Tool names default to placeholders; override via env once confirmed against
    the live server in Phase 1 (the builder docs list the exact 18+ tools).
    """

    def __init__(self, url: str, token: str | None = None):
        self.url = url
        self.token = token
        self.t_search = os.getenv("SWIGGY_TOOL_SEARCH", "search_restaurants")
        self.t_menu = os.getenv("SWIGGY_TOOL_MENU", "get_menu")
        self.t_order = os.getenv("SWIGGY_TOOL_ORDER", "place_order")
        self._session = None  # lazily opened MCP ClientSession

    def _ensure_session(self):
        if self._session is None:
            # Deferred import so the package loads without `mcp` installed.
            from mcp import ClientSession  # noqa: F401
            raise NotImplementedError(
                "Connect ClientSession to SWIGGY_MCP_URL here once Phase 1 confirms "
                "the live transport (stdio/HTTP) and auth from the builder docs."
            )
        return self._session

    def search_restaurants(self, query: str, area: str) -> list[str]:
        s = self._ensure_session()
        res = s.call_tool(self.t_search, {"query": query, "area": area})
        return [r["name"] for r in res]

    def get_menu(self, restaurant: str) -> list[Dish]:
        s = self._ensure_session()
        res = s.call_tool(self.t_menu, {"restaurant": restaurant})
        return [Dish(restaurant=restaurant, **r) for r in res]

    def place_order(self, restaurant: str, dish: Dish, address: str) -> OrderResult:
        s = self._ensure_session()
        res = s.call_tool(self.t_order, {
            "restaurant": restaurant,
            "items": [{"item": dish.item, "price": dish.price}],
            "address": address,
        })
        return OrderResult(
            order_ref=res["order_id"], total=res["total"], eta_min=res["eta_min"],
            restaurant=restaurant, item=dish.item,
        )


def get_food_client() -> FoodClient:
    url = os.getenv("SWIGGY_MCP_URL", "").strip()
    if url:
        return SwiggyFoodMCP(url, os.getenv("SWIGGY_MCP_TOKEN"))
    return MockSwiggyFood()
