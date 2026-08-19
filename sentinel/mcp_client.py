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

import json
import os
import time
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
    """Client for the live Swiggy Food MCP server.

    The server speaks plain JSON-RPC over POST: it replies `application/json`
    and issues no `mcp-session-id`, so the SDK's streamable-HTTP transport
    (which expects an SSE session) fails against it. A direct JSON-RPC client
    is both simpler and what actually works here.

    Needs a bearer token from the OAuth 2.1 + PKCE flow — see `sentinel/oauth.py`.
    """

    def __init__(self, url: str = "", token: str | None = None,
                 address_id: str | None = None):
        self.url = url or FOOD_ENDPOINT_DEFAULT
        if not token:
            # Falls back to the cached OAuth token; won't pop a browser here.
            from .oauth import get_token
            token = get_token(interactive=False)
        self.token = token
        self._addr_id = address_id or os.getenv("SWIGGY_ADDRESS_ID", "").strip() or None
        self._names: dict[str, str] = {}
        self._http = None  # one long-lived session; re-handshaking per call gets us rate-limited

    # -- transport ---------------------------------------------------------
    def _client(self):
        import httpx2
        return httpx2.Client(timeout=60, headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        })

    def _rpc(self, http, method: str, params: dict | None = None, rid: int = 1):
        body = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            body["params"] = params
        # The live server rate-limits; back off rather than failing the run.
        for attempt in range(4):
            resp = http.post(self.url, json=body)
            if resp.status_code != 429:
                break
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            time.sleep(min(wait, 15))
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"{method} failed: {err.get('code')} {err.get('message')}")
        return data.get("result", {})

    def _handshake(self, http):
        self._rpc(http, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "sustenance-sentinel", "version": "0.1.0"},
        })
        http.post(self.url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    @staticmethod
    def _unwrap(result: dict):
        """tools/call returns structuredContent, or JSON inside a text block."""
        if result.get("structuredContent"):
            return result["structuredContent"]
        for block in result.get("content", []) or []:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (ValueError, KeyError):
                    return block.get("text")
        return result

    def _session(self):
        """Open the connection and handshake once, then reuse it. A fresh
        handshake per tool call doubles the request count and trips the
        server's rate limiter."""
        if self._http is None:
            http = self._client()
            self._handshake(http)
            self._http = http
        return self._http

    def close(self):
        if self._http is not None:
            self._http.close()
            self._http = None

    def _run(self, tool: str, args: dict):
        res = self._rpc(self._session(), "tools/call",
                        {"name": tool, "arguments": args}, rid=2)
        if res.get("isError"):
            raise RuntimeError(f"{tool} returned an error: {self._unwrap(res)}")
        return self._unwrap(res)

    def list_tools(self) -> list[str]:
        """Names the live server actually advertises — used to verify wiring."""
        res = self._rpc(self._session(), "tools/list", {}, rid=2)
        return [t["name"] for t in res.get("tools", [])]

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _rows(res, *keys):
        """Live responses wrap their list under one of several keys."""
        if isinstance(res, dict):
            for k in keys:
                if isinstance(res.get(k), list):
                    return res[k]
        return res if isinstance(res, list) else []

    def _address_id(self) -> str:
        """Discovery calls are address-scoped. Resolve once and cache."""
        if self._addr_id:
            return self._addr_id
        addrs = self.get_addresses()
        if not addrs:
            raise RuntimeError("No saved Swiggy addresses on this account.")
        self._addr_id = addrs[0]["id"]
        return self._addr_id

    def autoselect_address(self, probes: str | list[str] = "pizza") -> dict | None:
        """Not every saved address is serviceable — a hometown address may have no
        delivery coverage, and a favourite chain may not operate there. Swiggy search
        is fuzzy, so "got any result" is a weak signal: score each address by how many
        of the probes it actually serves and pin the best one."""
        if isinstance(probes, str):
            probes = [probes]
        best, best_score = None, 0
        for addr in self.get_addresses():
            self._addr_id = addr["id"]
            score = 0
            for q in probes:
                try:
                    score += len(self.search_restaurants(q))
                except Exception:
                    continue
            if score > best_score:
                best, best_score = addr, score
        self._addr_id = best["id"] if best else None
        return best

    # -- FoodClient interface (shapes normalized from live responses) ------
    def get_addresses(self) -> list[dict]:
        return self._rows(self._run(TOOL_ADDRESSES, {}), "addresses", "data")

    def search_restaurants(self, query: str, area: str = "") -> list[str]:
        """Returns restaurant IDs; names are cached for friendly display."""
        res = self._run(TOOL_SEARCH, {"query": query, "addressId": self._address_id()})
        out = []
        for r in self._rows(res, "restaurants", "results", "data"):
            rid = str(r.get("id"))
            if r.get("name"):
                self._names[rid] = r["name"]
            # Skip anything we cannot order from right now.
            if str(r.get("availabilityStatus", "OPEN")).upper() == "OPEN":
                out.append(rid)
        return out

    # The live menu carries no tags/calories/spice, so derive coarse tags from
    # the category title plus the name and description. Anything we cannot infer
    # is left unset and the Guardian simply skips that rule.
    _TAG_HINTS = {
        "fried": ("fried", "crispy", "fries", "nugget", "pakora", "samosa"),
        "dessert": ("dessert", "cake", "brownie", "ice cream", "gulab", "sweet"),
        "sugary-drink": ("shake", "cola", "soda", "juice", "smoothie", "frappe"),
        "beverage": ("coffee", "tea", "latte", "drink", "water"),
    }

    @classmethod
    def _derive_tags(cls, name: str, desc: str, category: str) -> list[str]:
        blob = f"{name} {desc} {category}".lower()
        tags = [t for t, words in cls._TAG_HINTS.items() if any(w in blob for w in words)]
        if category:
            tags.append(category.strip().lower())
        return tags

    def get_menu(self, restaurant: str) -> list[Dish]:
        res = self._run(TOOL_MENU, {"restaurantId": str(restaurant),
                                    "addressId": self._address_id()})
        info = res.get("restaurant", {}) if isinstance(res, dict) else {}
        name = info.get("name") or self._names.get(str(restaurant), str(restaurant))

        out: list[Dish] = []
        for cat in self._rows(res, "categories"):
            title = cat.get("title", "")
            for it in cat.get("items", []) or []:
                if not it.get("inStock", 1):
                    continue  # never propose something the kitchen cannot make
                out.append(Dish(
                    restaurant=name,
                    item=it.get("name", "?"),
                    price=int(float(it.get("price", 0) or 0)),
                    tags=self._derive_tags(it.get("name", ""),
                                           it.get("description", ""), title),
                    calories=it.get("calories"),   # not exposed by the live API
                    spice=it.get("spice", 0),      # not exposed by the live API
                    vegetarian=bool(it.get("isVeg", False)),
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
            "restaurantId": str(restaurant),
            "items": [{"name": dish.item, "quantity": 1}],
        })
        placed = self._run(TOOL_ORDER, {"addressId": self._address_id()})
        order_id = placed.get("order_id") or placed.get("orderId") or placed.get("id")

        # v1 payment surface: cash goes straight through, UPI needs polling.
        if placed.get("requires_payment") or placed.get("status") == "payment_pending":
            opts = self._rows(self._run(TOOL_PAYMENT_OPTIONS, {"orderId": order_id}),
                              "options", "payment_options", "data")
            cash = next((o for o in opts
                         if "cash" in str(o.get("type", o.get("name", ""))).lower()), None)
            if not cash:
                raise RuntimeError(
                    f"Order {order_id} needs an online payment; Sentinel only "
                    f"auto-completes cash-on-delivery. Options: {opts}"
                )
            self._run(TOOL_CONFIRM, {"orderId": order_id,
                                     "paymentMethod": cash.get("type", "cash")})

        return OrderResult(
            order_ref=str(order_id),
            total=int(float(placed.get("total", dish.price) or dish.price)),
            eta_min=int(placed.get("eta_min", placed.get("eta", 0)) or 0),
            restaurant=self._names.get(str(restaurant), str(restaurant)),
            item=dish.item,
        )

    def track(self, order_id: str) -> dict:
        return self._run(TOOL_TRACK, {"orderId": order_id})


def get_food_client() -> FoodClient:
    url = os.getenv("SWIGGY_MCP_URL", "").strip()
    if url:
        return SwiggyFoodMCP(url, os.getenv("SWIGGY_MCP_TOKEN"))
    return MockSwiggyFood()
