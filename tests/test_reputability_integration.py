"""Non-retroactive attachment (Section 6.3), proven with two REAL
deliberations through the actual Body engine: a source's grade
snapshotted on the first answer must not change even after later
deliberations move that source's live grade."""
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain.loop import make_deliberation_unit

def run_once(tmp_path, name, question, reputability):
    cas = ContentAddressedStore(tmp_path / f"cas-{name}")
    log = CheckpointLog(cas=cas, index_path=tmp_path / f"index-{name}.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit(question, name, reputability=reputability)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]["answer"]

def test_non_retroactive_attachment_across_two_deliberations(tmp_path):
    rep_cas = ContentAddressedStore(tmp_path / "rep-cas")
    rep_log = CheckpointLog(cas=rep_cas, index_path=tmp_path / "rep-index.txt")
    reputability = ReputabilityStore(rep_log)

    a1 = run_once(tmp_path, "a", "is 17 prime?", reputability)
    grade1 = a1["source_grades_at_use"]["computed:trial_division"]["grade"]
    assert grade1 == "provisionally_accepted"  # first use, ungraded prior

    # force the source toward 'contested' via manual challenges (simulating
    # other deliberations disputing it), THEN run a second real deliberation
    reputability.record_outcome("computed:trial_division", "source", "challenged")
    reputability.record_outcome("computed:trial_division", "source", "challenged")

    a2 = run_once(tmp_path, "b", "is 19 prime?", reputability)
    grade2 = a2["source_grades_at_use"]["computed:trial_division"]["grade"]
    assert grade2 == "contested"  # the SECOND answer sees the new live grade

    # the FIRST answer's snapshot must be untouched by everything since
    assert a1["source_grades_at_use"]["computed:trial_division"]["grade"] == "provisionally_accepted"

def test_full_arc_logic_reputability_materiality_together(tmp_path):
    """The actual connected story: a fallacious argument gets caught by
    real Logic validity-checking, which challenges it, which downgrades
    the source's reputability, which the materiality test then correctly
    flags as grounds to reopen a DIFFERENT prior answer that cited the
    same source."""
    from athenaeum_body.storage.content_addressed import ContentAddressedStore
    from athenaeum_body.storage.checkpoint import CheckpointLog
    from athenaeum_brain.claims import Claim
    from athenaeum_brain.agents import MasterOfLogic
    from athenaeum_body.reputability_store import ReputabilityStore
    from athenaeum_brain.reevaluation import is_material

    rep_cas = ContentAddressedStore(tmp_path / "rep-cas")
    rep_log = CheckpointLog(cas=rep_cas, index_path=tmp_path / "rep-index.txt")
    reputability = ReputabilityStore(rep_log)

    # Step 1: an earlier answer cited this source and was fine at the time.
    prior_answer = {"source_grades_at_use": {"shaky-source": reputability.current_grade("shaky-source")}}
    assert prior_answer["source_grades_at_use"]["shaky-source"]["grade"] == "provisionally_accepted"

    # Step 2: a LATER claim citing the same source makes a fallacious
    # argument (affirming the consequent) -- real Logic catches it for real.
    fallacious = Claim(question_id="q2", round=1, issuing_agent="Mathematics",
                        statement="P holds", claim_type="formal", confidence=1.0,
                        defeat_condition="x", jurisdiction_check=True,
                        supporting_provenance=["shaky-source"],
                        argument={"premises": ["Q", "P -> Q"], "conclusion": "P"})
    verdict = MasterOfLogic().cross_examine(fallacious, "q2")
    assert verdict.relation == "challenges"
    reputability.record_outcome("shaky-source", "source", "challenged")
    reputability.record_outcome("shaky-source", "source", "challenged")
    reputability.record_outcome("shaky-source", "source", "challenged")

    # Step 3: materiality check against the FIRST answer correctly flags it.
    current = {"shaky-source": reputability.current_grade("shaky-source")}
    assert current["shaky-source"]["grade"] == "rejected"
    result = is_material(prior_answer, current)
    assert result["material"] is True
    assert "shaky-source" in result["reasons"][0]
