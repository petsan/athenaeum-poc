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

Journal layout (owner decision 12, 2026-09-26): each checkpoint holds only
the nodes and edges it ADDS -- `{"journal": 1, "items": [...]}` -- instead of
the whole graph, which made storage grow quadratically (progress §95). The
graph is not split per question, as the ledger is (decision 8), because its
nodes are shared: a source or a claim belongs to many questions, and queries
run from a source back to every answer resting on it. Reads fold new
journal entries into an in-memory cache, so a read costs only what was added
since the last one. A log written before this change starts with full
snapshots; a snapshot simply resets the fold, so old logs keep working with
no rewrite.
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
from dataclasses import dataclass
from .schemas import BeliefGraphNode, BeliefGraphEdge
from .storage.checkpoint import CheckpointLog

JOURNAL = 1


def _empty() -> dict:
    return {"nodes": {}, "edges": {}, "seq": 0}


def _apply(state: dict, item: dict) -> None:
    """Folds one journal item into `state` (write-once, like the store)."""
    table = state["nodes"] if item["kind"] == "node" else state["edges"]
    record = item["record"]
    table.setdefault(record["id"], record)
    state["seq"] = max(state["seq"], record["data"]["seq"])


@dataclass
class BeliefGraphStore:
    log: CheckpointLog

    def __post_init__(self):
        self._folded = _empty()   # every committed checkpoint up to _applied, folded
        self._applied = 0
        self._pending: list[dict] | None = None   # items added inside batch()
        self._depth = 0

    # --- reading ----------------------------------------------------------------

    def _committed(self) -> dict:
        index = self.log._read_index()
        if len(index) < self._applied:        # never happens to an append-only log; rebuild if it does
            self._folded, self._applied = _empty(), 0
        for snapshot_id in index[self._applied:]:
            payload = self.log.read_state(snapshot_id)
            if payload.get("journal") == JOURNAL:
                for item in payload["items"]:
                    _apply(self._folded, item)
            else:                              # a full snapshot, from before the journal layout
                self._folded = {"nodes": dict(payload["nodes"]), "edges": dict(payload["edges"]),
                                "seq": payload["seq"]}
        self._applied = len(index)
        return self._folded

    def _state(self) -> dict:
        """The graph as it stands, including anything added in an open batch.
        Callers only read it; everything handed out is a copy."""
        state = self._committed()
        if not self._pending:
            return state
        view = {"nodes": dict(state["nodes"]), "edges": dict(state["edges"]), "seq": state["seq"]}
        for item in self._pending:
            _apply(view, item)
        return view

    # --- writing ----------------------------------------------------------------

    def _add(self, kind: str, record: dict) -> None:
        item = {"kind": kind, "record": record}
        if self._depth:
            self._pending.append(item)
        else:
            self.log.write_checkpoint({"journal": JOURNAL, "items": [item]}, label="belief_graph")

    @contextmanager
    def batch(self):
        """Group the writes of one logical operation (recording an answer, a
        source) into one journal checkpoint. Reads inside the block see its
        writes; if the block fails, nothing is written. Nests."""
        if self._depth == 0:
            self._pending = []
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._pending = None
            raise
        self._depth -= 1
        if self._depth == 0:
            items, self._pending = self._pending, None
            if items:
                self.log.write_checkpoint({"journal": JOURNAL, "items": items}, label="belief_graph")

    def add_node(self, node_id: str, node_type: str, data: dict | None = None) -> BeliefGraphNode:
        state = self._state()
        if node_id not in state["nodes"]:
            node = BeliefGraphNode(id=node_id, node_type=node_type, data={**(data or {}), "seq": state["seq"] + 1})
            self._add("node", node.to_dict())
            state = self._state()
        return BeliefGraphNode.from_dict(copy.deepcopy(state["nodes"][node_id]))

    def add_edge(self, source_id: str, target_id: str, edge_type: str,
                 data: dict | None = None) -> BeliefGraphEdge:
        edge_id = f"{source_id}|{edge_type}|{target_id}"
        state = self._state()
        if edge_id not in state["edges"]:
            edge = BeliefGraphEdge(id=edge_id, source_id=source_id, target_id=target_id, edge_type=edge_type,
                                   data={**(data or {}), "seq": state["seq"] + 1})
            self._add("edge", edge.to_dict())
            state = self._state()
        return BeliefGraphEdge.from_dict(copy.deepcopy(state["edges"][edge_id]))

    # --- queries (unchanged interface) ---------------------------------------------

    def node(self, node_id: str) -> BeliefGraphNode | None:
        raw = self._state()["nodes"].get(node_id)
        return BeliefGraphNode.from_dict(copy.deepcopy(raw)) if raw else None

    def nodes(self, node_type: str | None = None) -> list[BeliefGraphNode]:
        return [BeliefGraphNode.from_dict(copy.deepcopy(n)) for n in self._state()["nodes"].values()
                if node_type is None or n["node_type"] == node_type]

    def edges(self, *, source_id: str | None = None, target_id: str | None = None,
              edge_type: str | None = None) -> list[BeliefGraphEdge]:
        return [BeliefGraphEdge.from_dict(copy.deepcopy(e)) for e in self._state()["edges"].values()
                if (source_id is None or e["source_id"] == source_id)
                and (target_id is None or e["target_id"] == target_id)
                and (edge_type is None or e["edge_type"] == edge_type)]

    def current_seq(self) -> int:
        return self._state()["seq"]
