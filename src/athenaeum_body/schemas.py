"""Core data schemas (Section 5.1) -- shape only, no interpretation."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List
import time


def _dict_roundtrip(cls):
    def to_dict(self) -> dict:
        return asdict(self)
    def from_dict(d: dict):
        return cls(**d)
    cls.to_dict = to_dict
    cls.from_dict = staticmethod(from_dict)
    return cls


@_dict_roundtrip
@dataclass
class BeliefGraphNode:
    id: str
    node_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@_dict_roundtrip
@dataclass
class BeliefGraphEdge:
    id: str
    source_id: str
    target_id: str
    edge_type: str
    data: Dict[str, Any] = field(default_factory=dict)


@_dict_roundtrip
@dataclass
class ProvenanceEntry:
    id: str
    content_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@_dict_roundtrip
@dataclass
class ReputabilityGrade:
    subject_id: str
    subject_type: str  # "source" | "human" | "model"
    grade: str
    rationale: str = ""
    version: int = 0


@_dict_roundtrip
@dataclass
class QuestionLedgerEntry:
    id: str
    status: str = "queued"  # queued|active|suspended|completed|archived
    importance: float = 0.0
    created_at: float = field(default_factory=time.time)
    versions: List[Dict[str, Any]] = field(default_factory=list)
