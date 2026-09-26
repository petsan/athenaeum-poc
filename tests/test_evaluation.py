import pathlib
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.calibration_store import CalibrationStore, confidence_bucket
from athenaeum_brain.evaluation import (
    run_ground_truth_benchmark, run_adversarial_suite, ADVERSARIAL_CASES,
    record_claim_calibration, calibration_report, b0_retrieval_only, a1_full_workflow,
    ablation_no_cross_examination, ablation_naive_majority_vote, check_integrity_gates,
    b1_single_agent_baseline,
)
from athenaeum_brain.claims import Claim


def make_calibration(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return CalibrationStore(log)


# --- 9.1 ground-truth benchmark ---

def test_ground_truth_benchmark_passes_on_correct_primality_case():
    cases = [{"question_id": "gt1", "question": "is 17 prime?", "expect_substring": "17 is prime"}]
    result = run_ground_truth_benchmark(cases)
    assert result["passed"] == 1 and result["total"] == 1


def test_ground_truth_benchmark_fails_on_wrong_expectation():
    cases = [{"question_id": "gt2", "question": "is 17 prime?", "expect_substring": "17 is not prime"}]
    result = run_ground_truth_benchmark(cases)
    assert result["passed"] == 0


# --- 9.2 adversarial suite ---

def test_adversarial_suite_all_pass():
    result = run_adversarial_suite()
    assert result["passed"] == result["total"] == len(ADVERSARIAL_CASES)


def test_adversarial_suite_covers_named_failure_modes():
    expected = {"false_consensus", "category_error_is_ought", "unverified_execution_claims",
                "prompt_content_injection", "category_error_traditional_confidence",
                "silent_model_substitution", "circular_corroboration"}
    assert set(ADVERSARIAL_CASES.keys()) == expected


# --- 9.3 calibration ---

def test_confidence_bucket_deciles():
    assert confidence_bucket(1.0) == "1.0"
    assert confidence_bucket(0.95) == "0.9-1.0"
    assert confidence_bucket(0.0) == "0.0-0.1"


def test_calibration_report_reflects_recorded_outcomes(tmp_path):
    store = make_calibration(tmp_path)
    claim = Claim(question_id="q1", round=1, issuing_agent="Mathematics", statement="x",
                   claim_type="formal", confidence=0.9, defeat_condition="x", jurisdiction_check=True)
    record_claim_calibration(store, claim, verified=True)
    record_claim_calibration(store, claim, verified=True)
    record_claim_calibration(store, claim, verified=False)
    report = calibration_report(store, "Mathematics")
    bucket = report["0.9-1.0"]
    assert bucket["n"] == 3
    assert abs(bucket["observed_verified_fraction"] - (2 / 3)) < 1e-9


# --- 9.7 baselines and ablations ---

def test_b0_has_no_synthesis_or_dissent():
    result = b0_retrieval_only("is 17 prime?", "b0-1")
    assert "committed" not in result
    assert result["baseline"] == "B0"
    assert len(result["claims"]) >= 1


def test_b1_single_agent_baseline_gets_a_real_generalist_response():
    """Section 9.7's B1, real for the first time (2026-09-23) via the
    model-lab guests -- no longer B1_UNAVAILABLE."""
    result = b1_single_agent_baseline("Q: What is the capital of Japan?\nA:")
    assert result["baseline"] == "B1"
    assert "tokyo" in result["response"].lower()


def test_a1_full_workflow_commits_claims():
    result = a1_full_workflow("is 17 prime?", "a1-1")
    assert result["baseline"] == "A1"
    assert any("17 is prime" in c["statement"] for c in result["committed"])


def test_ablation_no_cross_examination_never_produces_dissent():
    result = ablation_no_cross_examination("is 17 prime?", "abl1-1")
    assert result["dissent"] == []


def test_ablation_naive_majority_vote_picks_one_winner_and_discards_rest():
    result = ablation_naive_majority_vote("how should we round 2.5?", "abl2-1")
    assert result["winner"] is not None
    assert len(result["discarded"]) == 1  # the other jurisdictionally-valid conclusion, silently dropped
    # this IS the false-consensus failure mode -- the point of building this ablation
    a1 = a1_full_workflow("how should we round 2.5?", "abl2-2")
    assert len(a1["plural_answers"]) == 1  # A1 does NOT drop it


def test_ablation_naive_majority_vote_no_conflict_case():
    result = ablation_naive_majority_vote("is 17 prime?", "abl2-3")
    assert result["winner"] is None


# --- 9.8 non-compensatory integrity gates ---

def test_integrity_gates_pass_on_clean_answer():
    answer = a1_full_workflow("is 17 prime?", "gate-1")
    result = check_integrity_gates(answer)
    assert result["passed"] is True
    assert result["violations"] == []


def test_integrity_gates_catch_missing_provenance():
    answer = {"committed": [{"claim_id": "c1", "status": "committed", "claim_type": "formal",
                              "statement": "x", "supporting_provenance": []}]}
    result = check_integrity_gates(answer)
    assert result["passed"] is False
    assert any("supporting_provenance" in v for v in result["violations"])


def test_integrity_gates_catch_uncorrected_category_error():
    answer = {"committed": [{"claim_id": "c1", "status": "committed", "claim_type": "empirical",
                              "statement": "the data shows we should ban this",
                              "supporting_provenance": ["src:1"]}]}
    result = check_integrity_gates(answer)
    assert result["passed"] is False
    assert any("category error" in v for v in result["violations"])


def test_integrity_gates_catch_commit_boundary_violation():
    answer = {"committed": [{"claim_id": "c1", "status": "proposed", "claim_type": "formal",
                              "statement": "x", "supporting_provenance": ["src:1"]}]}
    result = check_integrity_gates(answer)
    assert result["passed"] is False
    assert any("commit-boundary" in v for v in result["violations"])


# --- 9.9 contamination-resistant isolation, verified by construction ---

def test_ingestion_module_does_not_import_evaluation_fixtures():
    ingestion_file = pathlib.Path(__file__).resolve().parent.parent / "src" / "athenaeum_body" / "ingestion.py"
    text = ingestion_file.read_text()
    assert "evaluation" not in text  # the Body's one real ingestion entry point can't reach the answer key
