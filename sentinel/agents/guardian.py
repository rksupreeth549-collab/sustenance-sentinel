"""Guardian agent — the safety gate.

Wraps the deterministic `policy.evaluate`. The model may *explain* a verdict for
the trace, but allow/deny comes only from code. Picks the first candidate that
passes; returns it plus the rejection reasons for everything it vetoed.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..policy import Candidate, Decision, evaluate
from ..models import Profile


@dataclass
class GuardianVerdict:
    approved: Candidate | None
    decision: Decision | None
    vetoed: list[tuple[Candidate, Decision]]  # (candidate, why) for the trace


class Guardian:
    name = "guardian"

    def __init__(self, profile: Profile):
        self.p = profile

    def review(self, candidates: list[Candidate], spent_today: int,
               max_repicks: int = 5) -> GuardianVerdict:
        vetoed: list[tuple[Candidate, Decision]] = []
        for c in candidates[:max_repicks]:
            d = evaluate(c, self.p, spent_today)
            if d.allow:
                return GuardianVerdict(approved=c, decision=d, vetoed=vetoed)
            vetoed.append((c, d))
        return GuardianVerdict(approved=None, decision=None, vetoed=vetoed)
