"""Round-trip serialization for all five core schemas (backlog Task 2)."""
from athenaeum_body.schemas import (
    BeliefGraphNode, BeliefGraphEdge, ProvenanceEntry, ReputabilityGrade, QuestionLedgerEntry,
)

def test_belief_graph_node_roundtrip():
    n = BeliefGraphNode(id="n1", node_type="claim", data={"x": 1})
    assert BeliefGraphNode.from_dict(n.to_dict()) == n

def test_belief_graph_edge_roundtrip():
    e = BeliefGraphEdge(id="e1", source_id="n1", target_id="n2", edge_type="corroborates")
    assert BeliefGraphEdge.from_dict(e.to_dict()) == e

def test_provenance_entry_roundtrip():
    p = ProvenanceEntry(id="p1", content_hash="sha256:abc", metadata={"license": "public-domain"})
    assert ProvenanceEntry.from_dict(p.to_dict()) == p

def test_reputability_grade_roundtrip():
    g = ReputabilityGrade(subject_id="src1", subject_type="source", grade="contested", version=2)
    assert ReputabilityGrade.from_dict(g.to_dict()) == g

def test_question_ledger_entry_roundtrip():
    q = QuestionLedgerEntry(id="q1", status="active", importance=0.7, versions=[{"answer": "v1"}])
    assert QuestionLedgerEntry.from_dict(q.to_dict()) == q
