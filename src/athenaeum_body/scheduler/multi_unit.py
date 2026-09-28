"""Time-sliced priority scheduler across many work units (Section 7.2 -- Task 18/19)."""
from __future__ import annotations
import heapq
from itertools import count
from typing import Protocol
from .work_unit import WorkUnit
from .runner import SingleUnitRunner


class YieldPolicy(Protocol):
    """Decides, round by round, whether an unfinished unit gives way."""
    def before_round(self, unit: WorkUnit) -> None: ...
    def after_round(self, unit: WorkUnit) -> bool: ...   # True: go to the back of its priority


class MultiUnitScheduler:
    """Priority scheduling, one round at a time. Without a `yield_policy`,
    every unfinished unit goes to the back of its priority after each round
    (round-robin), which is what lets even a single core make progress on
    many concurrent questions. With one, a unit keeps its place, and so runs
    again next, unless the policy says it should give way (the Maintainer
    yields after a round that called a model, owner decision 2026-09-27:
    quick questions finish at once, slow ones still take turns). A higher
    priority always goes first either way."""

    def __init__(self, runner: SingleUnitRunner, yield_policy: YieldPolicy | None = None):
        self.runner = runner
        self.yield_policy = yield_policy
        self._counter = count()
        self._heap = []  # (-priority, insertion_order, unit)

    def submit(self, unit: WorkUnit) -> None:
        unit.status = "queued"
        heapq.heappush(self._heap, (-unit.priority, next(self._counter), unit))

    def process_one_round(self) -> WorkUnit | None:
        """Pop the highest-priority queued unit, run exactly one round,
        and requeue it if not yet done. Returns the unit that ran, or None
        if the queue is empty."""
        if not self._heap:
            return None
        _, order, unit = heapq.heappop(self._heap)
        unit.status = "active"
        if self.yield_policy is not None:
            self.yield_policy.before_round(unit)
        done = self.runner.run_round(unit)
        if not done:
            gives_way = self.yield_policy is None or self.yield_policy.after_round(unit)
            heapq.heappush(self._heap, (-unit.priority, next(self._counter) if gives_way else order, unit))
        return unit

    def run_to_completion(self, max_rounds: int = 1000) -> list[str]:
        """Drain the queue, returning unit ids in the order they completed."""
        completed = []
        for _ in range(max_rounds):
            if not self._heap:
                break
            unit = self.process_one_round()
            if unit and unit.status == "completed":
                completed.append(unit.id)
        return completed
