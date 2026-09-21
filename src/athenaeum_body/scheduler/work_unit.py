"""Work-unit / round-handler interfaces (Section 7)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any, Dict


@dataclass
class RoundResult:
    proposed_writes: Dict[str, Any] = field(default_factory=dict)
    done: bool = False


# A round handler: (shared_state, round_index) -> RoundResult.
# The scheduler does not know or care what a round "does" -- only that
# it's atomic (Section 7's contract).
RoundHandler = Callable[[dict, int], RoundResult]


@dataclass
class WorkUnit:
    id: str
    priority: int = 0
    status: str = "queued"  # queued|active|suspended|completed|archived
    round_index: int = 0
    round_handler: RoundHandler = None
