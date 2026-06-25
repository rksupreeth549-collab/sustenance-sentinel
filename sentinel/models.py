"""Profile config + SQLite persistence for state, orders, and per-agent traces.

Pure data layer — no LLM or MCP here. Everything the dashboard replays comes
from these tables.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Optional

import yaml

# --- Window status values (state machine output) --------------------------
PENDING = "pending"      # window open, no signal yet
EATEN = "eaten"          # cared-for confirmed they ate
ORDERED = "ordered"      # Sentinel placed an order
SKIPPED = "skipped"      # cared-for opted out
NOT_EATEN = "not_eaten"  # window closed with no meal and no order (e.g. autonomy off)


@dataclass
class DietRules:
    vegetarian: bool = False
    exclude_tags: list[str] = field(default_factory=list)
    max_spice: int = 3
    max_calories: Optional[int] = None


@dataclass
class LadderTiming:
    nudge_after_min: int = 40
    last_call_before_end_min: int = 20
    countdown_min: int = 15


@dataclass
class Profile:
    person_id: str
    name: str
    relationship: str
    tone: str
    favorite_restaurants: list[str]
    cuisines: list[str]
    comfort_foods: list[str]
    diet: DietRules
    spend_cap_per_meal: int
    spend_cap_per_day: int
    meal_windows: dict[str, tuple[time, time]]
    ladder: LadderTiming
    address: dict[str, str]
    channels: dict[str, str]
    caregiver_name: str
    autonomy: str  # "confirm-first" | "full-auto"

    @property
    def full_auto(self) -> bool:
        return self.autonomy == "full-auto"

    @staticmethod
    def _parse_hhmm(s: str) -> time:
        h, m = s.split(":")
        return time(int(h), int(m))

    @classmethod
    def from_yaml(cls, path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        windows = {
            name: (cls._parse_hhmm(span[0]), cls._parse_hhmm(span[1]))
            for name, span in raw["meal_windows"].items()
        }
        d = raw.get("diet", {})
        l = raw.get("ladder", {})
        return cls(
            person_id=raw["person_id"],
            name=raw["name"],
            relationship=raw.get("relationship", "friend"),
            tone=raw.get("tone", "warm-playful"),
            favorite_restaurants=raw.get("favorite_restaurants", []),
            cuisines=raw.get("cuisines", []),
            comfort_foods=raw.get("comfort_foods", []),
            diet=DietRules(
                vegetarian=d.get("vegetarian", False),
                exclude_tags=d.get("exclude_tags", []),
                max_spice=d.get("max_spice", 3),
                max_calories=d.get("max_calories"),
            ),
            spend_cap_per_meal=raw["spend_cap_per_meal"],
            spend_cap_per_day=raw["spend_cap_per_day"],
            meal_windows=windows,
            ladder=LadderTiming(
                nudge_after_min=l.get("nudge_after_min", 40),
                last_call_before_end_min=l.get("last_call_before_end_min", 20),
                countdown_min=l.get("countdown_min", 15),
            ),
            address=raw.get("address", {}),
            channels=raw.get("channels", {"cared_for": "console", "caregiver": "console"}),
            caregiver_name=raw.get("caregiver_name", "Caregiver"),
            autonomy=raw.get("autonomy", "confirm-first"),
        )


# --- SQLite store ----------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS window_state (
    person_id   TEXT NOT NULL,
    day         TEXT NOT NULL,   -- ISO date
    window      TEXT NOT NULL,   -- breakfast/lunch/dinner
    status      TEXT NOT NULL,
    ladder_step INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (person_id, day, window)
);
CREATE TABLE IF NOT EXISTS order_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  TEXT NOT NULL,
    day        TEXT NOT NULL,
    window     TEXT NOT NULL,
    restaurant TEXT,
    item       TEXT,
    price      INTEGER,
    eta_min    INTEGER,
    order_ref  TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (person_id, day, window)   -- idempotency: one order per window
);
CREATE TABLE IF NOT EXISTS agent_trace (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    day       TEXT NOT NULL,
    window    TEXT NOT NULL,
    agent     TEXT NOT NULL,
    message   TEXT NOT NULL,
    data      TEXT,
    ts        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flags (
    person_id TEXT PRIMARY KEY,
    killed    INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, db_path: str = "app.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- window state --
    def get_window(self, person_id: str, day: str, window: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            "SELECT * FROM window_state WHERE person_id=? AND day=? AND window=?",
            (person_id, day, window),
        )
        return cur.fetchone()

    def set_window(self, person_id: str, day: str, window: str, status: str,
                   ladder_step: int) -> None:
        self.conn.execute(
            """INSERT INTO window_state (person_id, day, window, status, ladder_step, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(person_id, day, window)
               DO UPDATE SET status=excluded.status,
                             ladder_step=excluded.ladder_step,
                             updated_at=excluded.updated_at""",
            (person_id, day, window, status, ladder_step, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    # -- orders (idempotent) --
    def order_exists(self, person_id: str, day: str, window: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM order_log WHERE person_id=? AND day=? AND window=?",
            (person_id, day, window),
        )
        return cur.fetchone() is not None

    def record_order(self, person_id: str, day: str, window: str, restaurant: str,
                     item: str, price: int, eta_min: int, order_ref: str) -> bool:
        """Returns False if an order already exists for this window (idempotency)."""
        try:
            self.conn.execute(
                """INSERT INTO order_log
                   (person_id, day, window, restaurant, item, price, eta_min, order_ref, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (person_id, day, window, restaurant, item, price, eta_min, order_ref,
                 datetime.utcnow().isoformat()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def spent_today(self, person_id: str, day: str) -> int:
        cur = self.conn.execute(
            "SELECT COALESCE(SUM(price),0) AS s FROM order_log WHERE person_id=? AND day=?",
            (person_id, day),
        )
        return int(cur.fetchone()["s"])

    # -- trace --
    def trace(self, person_id: str, day: str, window: str, agent: str,
              message: str, data: Any = None) -> None:
        self.conn.execute(
            "INSERT INTO agent_trace (person_id, day, window, agent, message, data, ts) "
            "VALUES (?,?,?,?,?,?,?)",
            (person_id, day, window, agent, message,
             json.dumps(data) if data is not None else None,
             datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    def traces_for(self, person_id: str, day: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM agent_trace WHERE person_id=? AND day=? ORDER BY id",
            (person_id, day),
        )
        return cur.fetchall()

    # -- kill switch --
    def is_killed(self, person_id: str) -> bool:
        cur = self.conn.execute("SELECT killed FROM flags WHERE person_id=?", (person_id,))
        row = cur.fetchone()
        return bool(row and row["killed"])

    def set_killed(self, person_id: str, killed: bool) -> None:
        self.conn.execute(
            "INSERT INTO flags (person_id, killed) VALUES (?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET killed=excluded.killed",
            (person_id, 1 if killed else 0),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
