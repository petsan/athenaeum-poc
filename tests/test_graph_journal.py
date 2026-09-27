"""Owner decision 12 (batch 11, Phase AS): the Belief Graph as an append-only
journal. Each checkpoint holds only what it adds; old full-snapshot logs keep
working without a rewrite."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.belief_graph_store import BeliefGraphStore, JOURNAL
from athenaeum_brain.belief_graph import record_answer


@pytest.fixture
def mk(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return lambda: CheckpointLog(cas=cas, index_path=tmp_path / "graph.txt")


def answer(i, shared="shared-source"):
    return {"question": f"q{i}?", "dissent": [],
            "committed": [{"statement": f"claim {i}", "issuing_agent": "Mathematics", "claim_type": "formal",
                           "supporting_provenance": [f"source-{i}", shared]}]}


def last_payload(log):
    return log.read_state(log._read_index()[-1])


def test_each_checkpoint_holds_only_what_it_adds(mk):
    g = BeliefGraphStore(mk())
    record_answer(g, "q1", answer(1), version=0)
    first = last_payload(g.log)
    assert first["journal"] == JOURNAL
    assert sorted(i["record"]["id"] for i in first["items"] if i["kind"] == "node") == [
        "answer:q1:v0", "claim:Mathematics::claim 1", "question:q1", "source:shared-source", "source:source-1"]
    record_answer(g, "q2", answer(2), version=0)
    second = last_payload(g.log)
    new_nodes = sorted(i["record"]["id"] for i in second["items"] if i["kind"] == "node")
    assert "source:shared-source" not in new_nodes                  # already there: not written again
    assert len(g.log._read_index()) == 2                            # one checkpoint per recorded answer


def test_a_write_costs_the_same_however_big_the_graph_is(mk):
    g = BeliefGraphStore(mk())
    sizes = []
    for i in range(40):
        record_answer(g, f"q{i}", answer(i), version=0)
        entry = g.log.all_entries()[-1]
        sizes.append(g.log.cas._path_for(entry.payload_ref).stat().st_size)
    assert max(sizes[1:]) - min(sizes[1:]) < 40                     # flat, give or take id lengths
    assert len(g.nodes()) == 1 + 40 * 4                             # nothing lost: shared source + 4 per answer


def test_queries_and_seq_behave_as_before(mk):
    g = BeliefGraphStore(mk())
    record_answer(g, "q1", answer(1), version=0)
    record_answer(g, "q2", answer(2), version=0)
    assert g.current_seq() == len(g.nodes()) + len(g.edges())       # one seq per node and edge, no gaps
    seqs = [n.data["seq"] for n in g.nodes()] + [e.data["seq"] for e in g.edges()]
    assert sorted(seqs) == list(range(1, g.current_seq() + 1))
    assert g.add_node("question:q1", "question").data["seq"] == g.node("question:q1").data["seq"]  # write-once


def test_an_old_full_snapshot_log_keeps_working(mk):
    log = mk()
    old = {"nodes": {"source:a": {"id": "source:a", "node_type": "source", "data": {"seq": 1}}},
           "edges": {}, "seq": 1}
    log.write_checkpoint({"nodes": {}, "edges": {}, "seq": 0}, label="belief_graph")
    log.write_checkpoint(old, label="belief_graph")                 # the layout before decision 12
    g = BeliefGraphStore(mk())
    assert g.node("source:a").data["seq"] == 1 and g.current_seq() == 1
    b = g.add_node("source:b", "source")
    assert b.data["seq"] == 2                                       # continues the old numbering
    assert last_payload(g.log)["journal"] == JOURNAL and len(g.log._read_index()) == 3
    assert [n.id for n in BeliefGraphStore(mk()).nodes()] == ["source:a", "source:b"]


def test_two_stores_over_one_log_stay_consistent_and_read_incrementally(mk):
    a, b = BeliefGraphStore(mk()), BeliefGraphStore(mk())
    record_answer(a, "q1", answer(1), version=0)
    record_answer(a, "q2", answer(2, shared="source-1"), version=0)
    assert sorted(n.id for n in b.nodes("question")) == ["question:q1", "question:q2"]   # b sees a's writes
    assert len(b.edges()) == len(a.edges())
    assert b._applied == 2
    record_answer(b, "q3", answer(3), version=0)
    assert a.node("question:q3") is not None and a._applied == 3    # folded incrementally, not reread


def test_a_failed_batch_writes_nothing_and_batches_nest(mk):
    g = BeliefGraphStore(mk())
    with pytest.raises(RuntimeError):
        with g.batch():
            g.add_node("source:x", "source")
            assert g.node("source:x") is not None                   # visible inside the batch
            raise RuntimeError("half-way")
    assert g.node("source:x") is None and g.log._read_index() == []
    with g.batch():
        g.add_node("source:y", "source")
        with g.batch():
            g.add_edge("source:y", "source:z", "cites")
        assert g.log._read_index() == []                            # the inner block doesn't write
    assert len(g.log._read_index()) == 1 and len(last_payload(g.log)["items"]) == 2


def test_what_the_store_hands_out_is_a_copy(mk):
    g = BeliefGraphStore(mk())
    g.add_node("source:a", "source", {"license": "cc-by"})
    g.node("source:a").data["license"] = "tampered"
    g.nodes()[0].data["seq"] = 999
    assert g.node("source:a").data == {"license": "cc-by", "seq": 1}
