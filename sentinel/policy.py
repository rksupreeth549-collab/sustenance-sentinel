"""Guardian's deterministic core. NO model in here — allow/deny is pure code so
money + diet limits are never at the mercy of an LLM.

A `Candidate` is one dish the Concierge proposes. `evaluate` returns a
`Decision` the Guardian agent only *explains*; it cannot override.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Profile


@dataclass
class Candidate:
    restaurant: str
    item: str
    price: int                      # INR
    tags: list[str] = field(default_factory=list)
    calories: int | None = None
    spice: int = 0                  # 0..3
    vegetarian: bool = True


@dataclass
class Decision:
    allow: bool
    reasons: list[str]              # human-readable, every check that fired

    def explain(self) -> str:
        verdict = "ALLOW" if self.allow else "VETO"
        return f"{verdict}: " + "; ".join(self.reasons)


def evaluate(c: Candidate, profile: Profile, spent_today: int) -> Decision:
    """Run every guardrail. Collects ALL failing reasons (not short-circuit) so
    the trace shows the full picture; allow only if none fired."""
    reasons: list[str] = []
    diet = profile.diet

    # --- diet: vegetarian ---
    if diet.vegetarian and not c.vegetarian:
        reasons.append(f"'{c.item}' is non-veg but profile is vegetarian")

    # --- diet: excluded tags ---
    bad = sorted(set(t.lower() for t in c.tags) & set(t.lower() for t in diet.exclude_tags))
    if bad:
        reasons.append(f"'{c.item}' has excluded tag(s): {', '.join(bad)}")

    # --- diet: spice ---
    if c.spice > diet.max_spice:
        reasons.append(f"spice {c.spice} exceeds max {diet.max_spice}")

    # --- diet: calories ---
    if diet.max_calories is not None and c.calories is not None and c.calories > diet.max_calories:
        reasons.append(f"{c.calories} kcal exceeds max {diet.max_calories}")

    # --- money: per-meal cap ---
    if c.price > profile.spend_cap_per_meal:
        reasons.append(f"₹{c.price} exceeds per-meal cap ₹{profile.spend_cap_per_meal}")

    # --- money: per-day cap (including this order) ---
    if spent_today + c.price > profile.spend_cap_per_day:
        reasons.append(
            f"₹{c.price} would push day total to ₹{spent_today + c.price}, "
            f"over daily cap ₹{profile.spend_cap_per_day}"
        )

    if reasons:
        return Decision(allow=False, reasons=reasons)
    return Decision(
        allow=True,
        reasons=[f"'{c.item}' from {c.restaurant} ₹{c.price} passes diet + budget"],
    )
