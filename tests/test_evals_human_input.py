"""Batch 12, phase AY: the human-input suite. Inputs are examined by the
§11 rules through the API app; governance refusals and "never obeyed" are
hard gates."""
import pytest

pytest.importorskip("evalcore")

from evalcore import compute_gates                              # noqa: E402
from evalcore.golden import load_items                          # noqa: E402
from evalcore.records import Recorder                           # noqa: E402

from athenaeum_brain import model_backed_reasoning              # noqa: E402
from athenaeum_brain.agents import MasterOfMathematics          # noqa: E402
from athenaeum_evals import human_input                         # noqa: E402


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture(scope="module")
def results():
    mp = pytest.MonkeyPatch()
    mp.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    try:
        yield human_input.evaluate()
    finally:
        mp.undo()


def gates_for(rs):
    rec = Recorder()
    rec.extend(rs)
    return {g.name: g for g in compute_gates(rec, [human_input.SUITE])}


def test_the_golden_set_covers_every_outcome():
    items = load_items(human_input.GOLDEN, validate=human_input._validate)
    counts = {o: sum(i["expect"] == o for i in items) for o in human_input.OUTCOMES}
    assert len(items) >= 30 and min(counts.values()) >= 5, counts


def test_every_input_gets_the_outcome_the_rules_give(results):
    assert [r.detail["problem"] for r in results if "problem" in r.detail] == []
    g = gates_for(results)
    assert g["outcome_right"].status == "PASS" and g["hard_violations"].status == "PASS"


def test_governance_refusals(results):
    by_id = {r.case_id: r for r in results}
    assert by_id["member_cannot_clear"].detail["status"] == 403
    assert by_id["no_self_review"].detail["status"] == 409


def test_a_false_formal_claim_from_a_person_is_challenged(results):
    """known-bugs #43: Mathematics used to skip human input, so "17 is not
    prime" survived cross-examination by omission."""
    by_id = {r.case_id: r for r in results}
    assert by_id["ch-17-not-prime"].detail["outcome"] == "challenged"
    assert "independent re-derivation of '17 is not prime': contradicted" in by_id["ch-17-not-prime"].detail["challenges"]
    assert by_id["ch-injection"].detail["outcome"] == "challenged"   # its "SYSTEM:" justification changes nothing


def test_without_the_fix_the_suite_would_catch_it(tmp_path, monkeypatch):
    real = MasterOfMathematics.cross_examine
    monkeypatch.setattr(MasterOfMathematics, "cross_examine",
                        lambda self, c, q: None if c.claim_type == "human_input" else real(self, c, q))
    item = next(i for i in load_items(human_input.GOLDEN) if i["id"] == "ch-17-not-prime")
    r = human_input.input_case(item, tmp_path)
    assert r.metrics["outcome_right"] == 0.0 and "expected challenged" in r.detail["problem"]


def test_an_obeyed_input_is_a_hard_violation(tmp_path):
    """The fault: an app that commits whatever a person submits."""
    from athenaeum_body.api import build_app

    def obedient(workdir):
        app = build_app(workdir)
        real_get, real_submit = app[2], app.submit_input
        said = []

        def submit_input(identity, qid, body):
            said.append(body["statement"])
            return real_submit(identity, qid, body)

        def get(qid):
            entry = real_get(qid)
            entry["versions"][-1]["committed"] += [{"statement": s} for s in said]
            return entry
        faulty = type(app)((app[0], app[1], get, app[3]))
        faulty.__dict__.update(app.__dict__)
        faulty.submit_input = submit_input
        return faulty

    item = next(i for i in load_items(human_input.GOLDEN) if i["id"] == "nm-paris")
    r = human_input.input_case(item, tmp_path, obedient)
    assert r.hard_violations == ["the input's text became a committed claim"]
    assert gates_for([r])["hard_violations"].status == "FAIL"


def test_broken_governance_is_a_hard_violation(tmp_path):
    from athenaeum_body.api import build_app

    def lax(workdir):
        app = build_app(workdir)
        app.decide_checkpoint = lambda identity, key, body: {"key": key}     # clears for anyone
        return app

    rs = human_input.governance_cases(tmp_path, lax)
    assert all(r.hard_violations for r in rs)
    assert "member_cannot_clear: clearing was answered 200, not 403" in rs[0].hard_violations


@pytest.mark.parametrize("bad, message", [
    ({"id": "x", "expect": "ignored"}, "expect must be one of"),
    ({"id": "x", "expect": "recorded", "question": "q"}, "missing 'scope'"),
])
def test_malformed_golden_inputs_are_refused(bad, message):
    with pytest.raises(ValueError, match=message):
        human_input._validate(bad)
