"""
Belief Graph STORAGE (body-design.md Section 5.1, schemas.md): nodes and
typed edges, using the BeliefGraphNode / BeliefGraphEdge shapes from
schemas.py. What gets written, and what it means, is Brain judgment
(athenaeum_brain/belief_graph.py).

Append-only in the same sense as every other store here: a node or edge,
once written, is never modified or removed -- writing the same id again
is a no-op that returns the original. Every node and edge records a
monotonically increasing `seq` in its `data`, so "what was added after X"
is answerable without trusting wall-clock time.
"""
from __future__ import annotations
from dataclasses import dataclass
from .schemas import BeliefGraphNode, BeliefGraphEdge
from .storage.checkpoint import CheckpointLog


@dataclass
class BeliefGraphStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"nodes": {}, "edges": {}, "seq": 0}

    def batch(self):
        """Group the writes of one logical operation (recording an answer, a
        source) into one checkpoint: CheckpointLog.batch."""
        return self.log.batch()

    def add_node(self, node_id: str, node_type: str, data: dict | None = None) -> BeliefGraphNode:
        state = self._state()
        if node_id not in state["nodes"]:
            state["seq"] += 1
            node = BeliefGraphNode(id=node_id, node_type=node_type, data={**(data or {}), "seq": state["seq"]})
            state["nodes"][node_id] = node.to_dict()
            self.log.write_checkpoint(state, label="belief_graph")
        return BeliefGraphNode.from_dict(state["nodes"][node_id])

    def add_edge(self, source_id: str, target_id: str, edge_type: str,
                 data: dict | None = None) -> BeliefGraphEdge:
        edge_id = f"{source_id}|{edge_type}|{target_id}"
        state = self._state()
        if edge_id not in state["edges"]:
            state["seq"] += 1
            edge = BeliefGraphEdge(id=edge_id, source_id=source_id, target_id=target_id, edge_type=edge_type,
                                   data={**(data or {}), "seq": state["seq"]})
            state["edges"][edge_id] = edge.to_dict()
            self.log.write_checkpoint(state, label="belief_graph")
        return BeliefGraphEdge.from_dict(state["edges"][edge_id])

    def node(self, node_id: str) -> BeliefGraphNode | None:
        raw = self._state()["nodes"].get(node_id)
        return BeliefGraphNode.from_dict(raw) if raw else None

    def nodes(self, node_type: str | None = None) -> list[BeliefGraphNode]:
        return [BeliefGraphNode.from_dict(n) for n in self._state()["nodes"].values()
                if node_type is None or n["node_type"] == node_type]

    def edges(self, *, source_id: str | None = None, target_id: str | None = None,
              edge_type: str | None = None) -> list[BeliefGraphEdge]:
        return [BeliefGraphEdge.from_dict(e) for e in self._state()["edges"].values()
                if (source_id is None or e["source_id"] == source_id)
                and (target_id is None or e["target_id"] == target_id)
                and (edge_type is None or e["edge_type"] == edge_type)]

    def current_seq(self) -> int:
        return self._state()["seq"]
