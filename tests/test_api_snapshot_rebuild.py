"""Batch 14: what readers see between rounds. The worker leaves a snapshot
after every round, and reads answer from it while a round holds the lock
(§82). Whatever the snapshot's refresh does to save work, after every round
it must equal a view built fresh from the stores: a reader must never see
stale data because a rebuild was skipped."""
import heapq
import json

import pytest

from athenaeum_body.api import build_app
from athenaeum_body.reviewers import Identity
from athenaeum_brain import model_backed_reasoning

QUESTIONS = ["what force holds the moon in orbit?", "is 17 prime?", "how should we round 2.5?",
             "which came first, the printing press or the telescope?", "what is the capital of Italy?"]


def canon(view: dict) -> str:
    return json.dumps(view, sort_keys=True, default=repr)


@pytest.fixture
def app(tmp_path, monkeypatch):
    def ask_model(question, *a, **k):
        return "gravity holds the moon in orbit" if "moon" in question else None
    monkeypatch.setattr(model_backed_reasoning, "ask_model", ask_model)
    app = build_app(tmp_path)
    yield app
    app.stop_worker()


def submit(app, qid, question):
    with app.lock:
        app.maintainer.submit_question(qid, question)


def rounds_until_idle(app, check, limit=2000):
    for n in range(limit):
        busy = app.run_round()
        check()
        if not busy:
            return n + 1
    raise AssertionError(f"still busy after {limit} rounds")


def test_the_snapshot_equals_a_fresh_view_after_every_round(app):
    """Questions (model-backed and deterministic), the idle cycle their
    answers trigger, and its follow-ups: after each round the snapshot is
    what a fresh build of every read gives."""
    checked = []

    def check():
        assert canon(app.snapshot_view()) == canon(app.fresh_view()), f"stale snapshot after round {len(checked) + 1}"
        checked.append(1)

    for i, q in enumerate(QUESTIONS, 1):
        submit(app, f"q-{i}", q)
    rounds_until_idle(app, check)
    assert all(e["status"] == "completed" for e in app.fresh_view()["questions"])
    assert app.maintainer.cycles >= 1                    # an idle cycle ran, with its own rounds
    # Human input changes what readers see outside a round; the next rounds must still agree.
    app.submit_input(Identity("mo", "member"), "q-2",
                     {"statement": "17 is not prime", "justification": "a feeling", "declared_scope": "17"})
    submit(app, "q-6", "how many legs does a spider have?")
    rounds_until_idle(app, check)
    assert len(checked) > 20


def test_a_round_that_fails_is_visible_at_once(app, monkeypatch):
    """A unit given up after repeated failures shows as failed, with its
    question suspended, in the snapshot left by that very round."""
    calls = {"n": 0}
    real = app.maintainer.scheduler.process_one_round

    def failing():
        upcoming = app.maintainer.scheduler._heap[0][2]
        if upcoming.id == "q-1":
            calls["n"] += 1
            heapq.heappop(app.maintainer.scheduler._heap)   # as the real round does, before it runs
            raise RuntimeError("the model server went away")
        return real()
    monkeypatch.setattr(app.maintainer.scheduler, "process_one_round", failing)
    submit(app, "q-1", QUESTIONS[0])

    def check():
        assert canon(app.snapshot_view()) == canon(app.fresh_view())
    rounds_until_idle(app, check)
    view = app.snapshot_view()
    assert calls["n"] == app.maintainer.policy.max_round_failures
    assert view["maintenance"]["failed_units"] == ["q-1"] and view["by_id"]["q-1"]["status"] == "suspended"


def test_rounds_that_change_nothing_readers_see_skip_the_rebuild(app):
    """A deliberation's middle rounds write only its own unit state. They
    leave the snapshot as it is; the round that answers rebuilds it."""
    submit(app, "q-1", QUESTIONS[0])
    stats = app.snapshot_stats
    before = dict(stats)
    rounds = rounds_until_idle(app, lambda: None)
    rebuilt, skipped = stats["rebuilt"] - before["rebuilt"], stats["skipped"] - before["skipped"]
    assert rebuilt + skipped == rounds                # every round refreshes (the inbox was empty)
    assert skipped > 0 and rebuilt > 0
    assert app.snapshot_view()["by_id"]["q-1"]["status"] == "completed"


def test_a_write_from_another_process_is_seen(app, tmp_path):
    """The judging benchmark script records a result through its own store
    on the same files; the next read shows it, with nothing else changed."""
    from athenaeum_body.model_fitness_store import ModelFitnessStore
    from athenaeum_body.storage.checkpoint import CheckpointLog
    from athenaeum_body.storage.content_addressed import ContentAddressedStore
    from athenaeum_brain import judging_benchmark as jb
    from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL
    before = app.maintenance_status()["challengers"][DEFAULT_MODEL]
    other = ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                            index_path=tmp_path / "model-fitness.txt"))
    other.record_judging(DEFAULT_MODEL, {"benchmark_version": jb.BENCHMARK_VERSION,
                                         "prompt_version": jb.PROMPT_VERSION, **jb.score(97, 120), "misses": []})
    after = app.maintenance_status()["challengers"][DEFAULT_MODEL]
    assert before["why"] == "never run on the judging benchmark" and after["why"] != before["why"]
    assert canon(app.snapshot_view()) == canon(app.fresh_view())
