"""Batch 11, Phase AU: human input over HTTP. It enters as a claim, is
cross-examined, graded against the submitter, and then -- by the existing
rules (decision 5) -- recorded, checkpointed, or, once a reviewer approves,
the answer reopens with it as the reason."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body import api
from athenaeum_body.api import build_app, ApiError
from athenaeum_body.reviewers import Identity, add_reviewer
from athenaeum_brain import model_backed_reasoning

MEMBER, REVIEWER = Identity("mo", "member"), Identity("rita", "reviewer")


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def app(tmp_path):
    app = build_app(tmp_path)
    app[0]("is 17 prime?")                 # q-1: one claim, citing computed:trial_division, which leads
    app[0]("how should we round 2.5?")     # q-2: a plural answer, so no single leading conclusion
    return app


def set_importance(app, qid, value):
    with app.lock:
        app.maintainer.ledger.update_importance(qid, value)


def say(app, qid, scope, identity=MEMBER, statement="a point about this", justification="a primary source"):
    return app.submit_input(identity, qid, {"statement": statement, "justification": justification,
                                            "declared_scope": scope})


def test_input_about_nothing_the_answer_relies_on_is_recorded_as_not_material(app):
    out = say(app, "q-1", "Paris")
    assert out["outcome"] == "not_material" and out["id"] == "input-1"
    grade = app.maintainer.idle.reputability.current_grade("mo")
    assert grade["grade"] == "provisionally_accepted"              # graded like a source (11.3)
    assert app[2]("q-1")["human_inputs"][0]["status"] == "not_material"


def test_input_a_cross_examiner_challenges_goes_no_further(app, monkeypatch):
    from athenaeum_brain import rounds
    real = rounds.cross_examination_round

    def challenge_everything(claims, qid):
        out = real(claims, qid)
        c = claims[0]
        out.append(type(c)(question_id=qid, round=2, issuing_agent="Logic", statement="that does not follow",
                           claim_type="procedural", confidence=1.0, defeat_condition="d", jurisdiction_check=True,
                           relation="challenges", target_claim_id=c.claim_id))
        return out
    monkeypatch.setattr(rounds, "cross_examination_round", challenge_everything)
    out = say(app, "q-1", "17")
    assert out["outcome"] == "challenged" and out["challenges"] == ["that does not follow"]
    assert app.maintainer.idle.checkpoints.get("q-1") is None


def test_material_input_on_a_minor_question_stands_as_testimony(app):
    set_importance(app, "q-2", 0.1)
    out = say(app, "q-2", "computed:decimal.ROUND_HALF_UP")
    assert out["outcome"] == "recorded"
    assert app.maintainer.idle.checkpoints.get("q-2") is None
    assert len(app[2]("q-2")["versions"]) == 1                      # nothing reopened


def test_input_on_an_important_question_waits_for_a_reviewer(app):
    set_importance(app, "q-2", 0.9)
    assert say(app, "q-2", "computed:decimal.ROUND_HALF_UP")["outcome"] == "checkpointed"
    cp = app.maintainer.idle.checkpoints.get("q-2")
    assert cp["status"] == "pending_human_checkpoint" and "at or above" in cp["reason"]


def test_input_against_the_leading_conclusion_always_waits(app):
    set_importance(app, "q-1", 0.0)
    assert say(app, "q-1", "computed:trial_division")["outcome"] == "checkpointed"
    assert "would change the leading conclusion" in app.maintainer.idle.checkpoints.get("q-1")["reason"]


def test_an_approved_input_reopens_the_answer_with_it_as_the_reason(app):
    set_importance(app, "q-1", 0.0)
    say(app, "q-1", "computed:trial_division", statement="17 has a factor I found")
    with pytest.raises(ApiError) as own:
        app.decide_checkpoint(Identity("mo", "reviewer"), "q-1", {"decision": "approve"})
    assert own.value.status == 409                                  # the submitter can't approve their own input
    decided = app.decide_checkpoint(REVIEWER, "q-1", {"decision": "approve"})
    assert decided["status"] == "current" and decided["reopen_requested"] is True
    deadline = time.time() + 20
    while len(app[2]("q-1")["versions"]) < 2:
        assert time.time() < deadline, app.maintenance_status()
        time.sleep(0.05)
    reasons = app[2]("q-1")["versions"][1]["reopen_context"]["reasons"]
    assert any('human input from mo, approved by rita: "17 has a factor I found"' in r for r in reasons)
    assert app[2]("q-1")["human_inputs"][0]["status"] == "approved"


def test_a_rejected_input_keeps_its_note_and_reopens_nothing(app):
    set_importance(app, "q-1", 0.0)
    say(app, "q-1", "computed:trial_division")
    decided = app.decide_checkpoint(REVIEWER, "q-1", {"decision": "reject_with_note", "note": "no source"})
    assert decided["reopen_requested"] is False
    record = app[2]("q-1")["human_inputs"][0]
    assert record["status"] == "rejected" and record["note"] == "no source" and record["reviewer_id"] == "rita"
    assert app.maintainer._m.get("requested_reopens", {}) == {}


def test_a_rejection_note_re_enters_as_input_of_its_own(app):
    """Section 11.4: reject-with-note is not a unilateral override. The note
    is examined like any input, attributed to the reviewer who wrote it, so
    if it matters it waits for a different reviewer."""
    set_importance(app, "q-1", 0.0)
    say(app, "q-1", "computed:trial_division", statement="17 has a factor I found")
    decided = app.decide_checkpoint(REVIEWER, "q-1", {"decision": "reject_with_note",
                                                      "note": "trial division up to 4 finds no factor of 17"})
    assert decided["note_input"]["id"] == "input-2" and decided["note_input"]["outcome"] == "checkpointed"
    original, note = app[2]("q-1")["human_inputs"]
    assert original["status"] == "rejected"
    assert note["submitter_id"] == "rita" and note["role"] == "reviewer" and note["responds_to"] == "input-1"
    assert note["statement"] == "trial division up to 4 finds no factor of 17"
    assert note["justification"] == "rita's reason for rejecting input-1"
    assert note["declared_scope"] == "computed:trial_division"
    assert app.maintainer.idle.checkpoints.get("q-1")["submitter_id"] == "rita"
    with pytest.raises(ApiError) as own:                            # rita can't clear her own note
        app.decide_checkpoint(REVIEWER, "q-1", {"decision": "approve"})
    assert own.value.status == 409
    again = app.decide_checkpoint(Identity("ravi", "reviewer"), "q-1", {"decision": "approve"})
    assert again["reopen_requested"] is True and "note_input" not in again
    assert app[2]("q-1")["human_inputs"][1]["status"] == "approved"


def test_a_challenged_rejection_note_goes_no_further(app, monkeypatch):
    """The note gets no free pass: if a cross-examiner challenges it, it
    counts against the reviewer's record, and the original checkpoint stays
    as the rejection left it (still pending, still mo's)."""
    from athenaeum_brain import rounds
    real = rounds.cross_examination_round
    set_importance(app, "q-2", 0.9)
    say(app, "q-2", "computed:decimal.ROUND_HALF_UP")

    def challenge_everything(claims, qid):
        out = real(claims, qid)
        c = claims[0]
        out.append(type(c)(question_id=qid, round=2, issuing_agent="Logic", statement="that does not follow",
                           claim_type="procedural", confidence=1.0, defeat_condition="d", jurisdiction_check=True,
                           relation="challenges", target_claim_id=c.claim_id))
        return out
    monkeypatch.setattr(rounds, "cross_examination_round", challenge_everything)
    decided = app.decide_checkpoint(REVIEWER, "q-2", {"decision": "reject_with_note", "note": "see the standard"})
    assert decided["note_input"]["outcome"] == "challenged"
    assert app[2]("q-2")["human_inputs"][1]["responds_to"] == "input-1"
    cp = app.maintainer.idle.checkpoints.get("q-2")
    assert cp["status"] == "pending_human_checkpoint" and cp["submitter_id"] == "mo"
    assert app.maintainer.idle.reputability.current_grade("rita") is not None      # graded like any submitter


@pytest.mark.parametrize("qid, body, status", [
    ("q-404", {"statement": "x", "declared_scope": "17"}, 404),
    ("q-1", {"statement": "", "declared_scope": "17"}, 400),
    ("q-1", {"statement": "x", "declared_scope": 5}, 400),
    ("q-1", {"statement": "x", "declared_scope": "17", "justification": ["not", "a", "string"]}, 400),
])
def test_bad_submissions_are_refused(app, qid, body, status):
    with pytest.raises(ApiError) as e:
        app.submit_input(MEMBER, qid, body)
    assert e.value.status == status


def test_an_unanswered_question_takes_no_input_yet(app):
    with app.lock:
        app.maintainer.submit_question("q-3", "is 19 prime?")       # registered, never run
    with pytest.raises(ApiError) as e:
        app.submit_input(MEMBER, "q-3", {"statement": "x", "declared_scope": "19"})
    assert e.value.status == 409


def test_over_http_the_submitter_is_whoever_the_token_says(tmp_path):
    token = add_reviewer(tmp_path / "reviewers.json", "mo", "member")
    server = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(tmp_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, payload, auth=True):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if auth else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        post("/api/questions", {"question": "is 17 prime?"}, auth=False)
        body = {"statement": "a point", "justification": "", "declared_scope": "Paris", "submitter_id": "someone"}
        assert post("/api/questions/q-1/input", body, auth=False)[0] == 401
        status, out = post("/api/questions/q-1/input", body)
        assert status == 200 and out["outcome"] == "not_material"
        with urllib.request.urlopen(f"{base}/api/questions/q-1") as r:
            (record,) = json.loads(r.read())["human_inputs"]
        assert record["submitter_id"] == "mo" and record["role"] == "member"   # not what the body claimed
    finally:
        server.shutdown()
