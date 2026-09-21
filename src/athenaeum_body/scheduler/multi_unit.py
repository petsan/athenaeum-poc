"""Time-sliced priority scheduler across many work units (Section 7.2 -- Task 18/19)."""
from __future__ import annotations
import heapq
from itertools import count
from .work_unit import WorkUnit
from .runner import SingleUnitRunner


class MultiUnitScheduler:
    """Round-robin/priority scheduling: process one round of one unit at a
    time, then yield to the next-highest-priority queued unit. This is what
    lets even a single core make progress on many concurrent questions."""

    def __init__(self, runner: SingleUnitRunner):
        self.runner = runner
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
        _, _, unit = heapq.heappop(self._heap)
        unit.status = "active"
        done = self.runner.run_round(unit)
        if not done:
            heapq.heappush(self._heap, (-unit.priority, next(self._counter), unit))
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
