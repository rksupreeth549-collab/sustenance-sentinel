"""Guardian policy — diet + budget allow/deny."""
from sentinel.models import DietRules, LadderTiming, Profile
from sentinel.policy import Candidate, evaluate
from datetime import time


def _profile(**over):
    base = dict(
        person_id="p", name="Riya", relationship="partner", tone="warm",
        favorite_restaurants=[], cuisines=[], comfort_foods=[],
        diet=DietRules(vegetarian=True, exclude_tags=["fried", "sugary-drink"],
                       max_spice=2, max_calories=750),
        spend_cap_per_meal=400, spend_cap_per_day=900,
        meal_windows={"lunch": (time(12, 30), time(14, 30))},
        ladder=LadderTiming(), address={}, channels={}, caregiver_name="A",
        autonomy="confirm-first",
    )
    base.update(over)
    return Profile(**base)


def test_compliant_dish_allowed():
    p = _profile()
    c = Candidate("R", "Dal Makhani", 320, ["north-indian"], 620, 1, True)
    d = evaluate(c, p, spent_today=0)
    assert d.allow, d.explain()


def test_nonveg_vetoed():
    p = _profile()
    c = Candidate("R", "Butter Chicken", 350, ["non-veg"], 700, 2, False)
    d = evaluate(c, p, 0)
    assert not d.allow
    assert any("non-veg" in r for r in d.reasons)


def test_excluded_tag_vetoed():
    p = _profile()
    c = Candidate("R", "Fried Bowl", 300, ["fried"], 700, 1, True)
    d = evaluate(c, p, 0)
    assert not d.allow
    assert any("excluded tag" in r for r in d.reasons)


def test_per_meal_cap_vetoed():
    p = _profile()
    c = Candidate("R", "Feast", 450, ["north-indian"], 700, 1, True)
    d = evaluate(c, p, 0)
    assert not d.allow
    assert any("per-meal cap" in r for r in d.reasons)


def test_daily_cap_vetoed():
    p = _profile()
    c = Candidate("R", "Bowl", 300, ["healthy-bowls"], 500, 1, True)
    d = evaluate(c, p, spent_today=700)  # 700+300 > 900
    assert not d.allow
    assert any("daily cap" in r for r in d.reasons)


def test_calories_and_spice_vetoed():
    p = _profile()
    c = Candidate("R", "Spicy Heavy", 200, ["north-indian"], 900, 3, True)
    d = evaluate(c, p, 0)
    assert not d.allow
    assert any("kcal" in r for r in d.reasons)
    assert any("spice" in r for r in d.reasons)
