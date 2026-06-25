"""Concierge agent — the food expert.

Searches the cared-for person's favorite restaurants via Swiggy Food MCP, reads
menus, and ranks a candidate dish toward comfort foods + cuisines while staying
cheap enough to clear the budget. Returns ordered candidates so the Guardian can
veto-and-repick.
"""
from __future__ import annotations

from ..mcp_client import Dish, FoodClient
from ..policy import Candidate
from ..models import Profile


class Concierge:
    name = "concierge"

    def __init__(self, food: FoodClient, profile: Profile):
        self.food = food
        self.p = profile

    def _score(self, d: Dish) -> float:
        """Higher is better: reward comfort-food/cuisine match, penalize price."""
        score = 0.0
        name = d.item.lower()
        for cf in self.p.comfort_foods:
            if cf.lower() in name:
                score += 5
        for tag in d.tags:
            if tag in self.p.cuisines:
                score += 2
        if self.p.diet.vegetarian and d.vegetarian:
            score += 1
        # Cheaper dishes preferred, but only as a tiebreaker.
        score -= d.price / 1000.0
        return score

    def candidates(self, area: str) -> list[Candidate]:
        """Ranked candidate dishes across favorite restaurants (best first)."""
        dishes: list[Dish] = []
        for fav in self.p.favorite_restaurants:
            for r in self.food.search_restaurants(fav, area):
                dishes.extend(self.food.get_menu(r))
        dishes.sort(key=self._score, reverse=True)
        return [
            Candidate(
                restaurant=d.restaurant, item=d.item, price=d.price, tags=d.tags,
                calories=d.calories, spice=d.spice, vegetarian=d.vegetarian,
            )
            for d in dishes
        ]
