"""
What the Belief Graph records, and what it's used for (brain-design.md
Sections 3.5, 7.1, 7.2). Storage: athenaeum_body/belief_graph_store.py.

Nodes (ids are deterministic, so re-recording is a no-op):
  question:<question_id>
  answer:<question_id>:v<version>      one per ledger version
  claim:<claim_key>                    the SAME node whenever the same agent
                                       reaches the same statement, from any
                                       question -- which is what makes shared
                                       claims, and therefore dependency, visible
  source:<source_id>
Edges:
  question -has_version-> answer
  answer   -relies_on->   claim        (committed)
  answer   -dissents->    claim        (challenged, recorded as dissent)
  claim    -cites->       source

Uses:
  dependents()             -- 7.1: other questions whose latest answer relies
                              on a claim this question's latest answer relies on
  questions_relying_on_source()
                           -- 7.2's first trigger at full reach: every question
                              whose latest answer rests on a source, so a grade
                              change isn't limited to what idle evolution sampled
  newly_relevant_claims()  -- 7.2's second trigger, read narrowly and
                              mechanically: after this question's latest
                              answer, some OTHER question committed a claim
                              about the same subject (synthesis's normalized
                              subject, so '2.5' and '2.50' match) that this
                              answer doesn't rely on. Semantic "same question"
                              detection beyond shared subjects needs a model,
                              as rounds._normalize_subject already notes.
"""
from __future__ import annotations
from athenaeum_body.belief_graph_store import BeliefGraphStore
from .consolidation import claim_key
from .rounds import _normalize_subject


def _subject_key(subject: str | None) -> str | None:
    if not subject:
        return None
    kind, value = _normalize_subject(subject)
    return f"{kind}:{value}"


def answer_node_id(question_id: str, version: int) -> str:
    return f"answer:{question_id}:v{version}"


def record_answer(graph: BeliefGraphStore, question_id: str, answer: dict, version: int) -> str:
    q = f"question:{question_id}"
    a = answer_node_id(question_id, version)
    graph.add_node(q, "question", {"question": answer.get("question")})
    graph.add_node(a, "answer", {"question_id": question_id, "version": version})
    graph.add_edge(q, a, "has_version")

    def claim_node(c: dict) -> str:
        cid = f"claim:{claim_key(c)}"
        graph.add_node(cid, "claim", {"statement": c["statement"], "issuing_agent": c["issuing_agent"],
                                      "claim_type": c.get("claim_type"), "subject": _subject_key(c.get("subject"))})
        for src in c.get("supporting_provenance", []):
            graph.add_node(f"source:{src}", "source", {})
            graph.add_edge(cid, f"source:{src}", "cites")
        return cid

    for c in answer.get("committed", []):
        graph.add_edge(a, claim_node(c), "relies_on")
    for d in answer.get("dissent", []):
        graph.add_edge(a, claim_node(d["claim"]), "dissents")
    return a


def latest_answer(graph: BeliefGraphStore, question_id: str):
    versions = [graph.node(e.target_id) for e in graph.edges(source_id=f"question:{question_id}",
                                                            edge_type="has_version")]
    return max(versions, key=lambda n: n.data["version"], default=None)


def _relied_on(graph: BeliefGraphStore, answer_id: str) -> set[str]:
    return {e.target_id for e in graph.edges(source_id=answer_id, edge_type="relies_on")}


def dependents(graph: BeliefGraphStore, question_id: str) -> list[str]:
    """Other questions whose latest answer relies on at least one claim this
    question's latest answer relies on."""
    mine = latest_answer(graph, question_id)
    if mine is None:
        return []
    my_claims = _relied_on(graph, mine.id)
    found = set()
    for q in graph.nodes("question"):
        other = q.id.split(":", 1)[1]
        if other == question_id:
            continue
        theirs = latest_answer(graph, other)
        if theirs is not None and my_claims & _relied_on(graph, theirs.id):
            found.add(other)
    return sorted(found)


def newly_relevant_claims(graph: BeliefGraphStore, question_id: str) -> list[dict]:
    mine = latest_answer(graph, question_id)
    if mine is None:
        return []
    my_claims = _relied_on(graph, mine.id)
    subjects = {graph.node(c).data.get("subject") for c in my_claims} - {None}
    if not subjects:
        return []
    found = {}
    for e in graph.edges(edge_type="relies_on"):
        if e.data["seq"] <= mine.data["seq"] or e.target_id in my_claims or e.target_id in found:
            continue
        answer = graph.node(e.source_id)
        if answer.data["question_id"] == question_id:
            continue
        claim = graph.node(e.target_id)
        if claim.data.get("subject") in subjects:
            found[e.target_id] = {"claim": e.target_id.split(":", 1)[1], "subject": claim.data["subject"],
                                  "from_question": answer.data["question_id"]}
    return list(found.values())


def questions_relying_on_source(graph: BeliefGraphStore, source_id: str) -> list[str]:
    """Questions whose LATEST answer relies on (commits) a claim citing this
    source -- source <-cites- claim <-relies_on- answer. Superseded versions
    don't count: a reopened answer already reflects what it was reopened for."""
    found = set()
    for cite in graph.edges(target_id=f"source:{source_id}", edge_type="cites"):
        if not cite.source_id.startswith("claim:"):
            continue  # a source citing a source is not reliance
        for rel in graph.edges(target_id=cite.source_id, edge_type="relies_on"):
            qid = graph.node(rel.source_id).data["question_id"]
            latest = latest_answer(graph, qid)
            if latest is not None and latest.id == rel.source_id:
                found.add(qid)
    return sorted(found)


def citations(graph: BeliefGraphStore) -> dict[str, list[str]]:
    """The citation map ingestion recorded (source -cites-> source), in the
    `{source_id: [cited ids]}` shape dispute_resolution.check_independence
    and consolidation's independence count read. claim -cites-> source
    edges are provenance, not citation between sources, and are excluded."""
    found: dict[str, list[str]] = {}
    for e in graph.edges(edge_type="cites"):
        if e.source_id.startswith("source:") and e.target_id.startswith("source:"):
            found.setdefault(e.source_id.split(":", 1)[1], []).append(e.target_id.split(":", 1)[1])
    return found
