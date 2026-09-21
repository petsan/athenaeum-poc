"""Resource monitor + pure scale-down reaction rules (Section 6)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ResourceState:
    cores_available: int = 40
    gpu_available: bool = True
    tier2_reachable: bool = True
    dram_headroom_gb: float = 512.0


@dataclass
class ResourceMonitor:
    """Settable stub standing in for real hardware polling (Section 6.2)."""
    state: ResourceState = None

    def __post_init__(self):
        if self.state is None:
            self.state = ResourceState()

    def get_state(self) -> ResourceState:
        return self.state

    def set_state(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self.state, k, v)


def target_concurrency(state: ResourceState) -> int:
    """Pure function (Section 6.3, testable against synthetic inputs)."""
    return max(1, state.cores_available)


def should_suspend(state: ResourceState, working_set_floor_gb: float) -> bool:
    """Pure function: DRAM below floor triggers checkpoint-and-suspend."""
    return state.dram_headroom_gb < working_set_floor_gb
