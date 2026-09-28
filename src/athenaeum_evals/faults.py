"""How well does each of Athenaeum's evaluation tools work? The fault matrix.

Every tool is one of the suites' own checks (a gate, or the injection
heuristic), run by the suites' own grading code. Every fault makes the
system misbehave in a known way. `matrix()` runs each tool against each
fault, and against the healthy system, many times, with evalcore's
`run_matrix`: the catch rate on a tool's target faults is its sensitivity,
the rate on the healthy system its false-alarm rate.

How a trial works. The real system is run once (`record()`): every
deliberation golden wording, every unanswerable question, every injection
fixture through the API app, every human input and both governance checks.
A trial then applies a fault to those recorded outputs, hitting a fresh
random draw of cases (each fault hits each case with a stated
probability), and runs the tool on the result. The Brain is deterministic,
so re-running it would give identical trials and falsely narrow intervals;
the randomness that matters is which cases a fault touches. The rates
describe the tools at these case counts and fault intensities, not any real
system, and the dashboard says so.
"""
from __future__ import annotations

import contextvars
import dataclasses
import tempfile
from pathlib import Path

import numpy as np
from evalcore import Config, compute_gates
from evalcore.efficacy import Fault, Tool, run_matrix
from evalcore.golden import expand_variants, load_items
from evalcore.records import CaseResult, Recorder

from athenaeum_brain.claims import Claim
from athenaeum_brain.content_integrity import detect_instruction_like_content

from . import calibration, deliberation, human_input, provenance

MATRIX_CONFIG = Config(bootstrap_iterations=200)     # per trial; the nightly evaluation uses the full 2,000
INTENSITY = {                                         # the chance a fault hits each case it can touch
    "wrong_answer": 0.05, "missing_answers": 0.15, "paraphrase_blind": 0.4, "miscalibrated": 0.5,
    "fabricated_citation": 0.1, "confident_guess": 0.2, "echo_ingested": 0.25, "obeys_input": 0.1,
    "misrouted_input": 0.15, "lax_governance": 0.5,
}
HEURISTIC_SAMPLE = 1          # one ingested document per trial: per-document catch and false-alarm rates


# --- the recorded system ---------------------------------------------------

def record(workdir: Path | None = None) -> dict:
    """One run of the real system, kept for the trials."""
    golden = deliberation.items()
    wordings = [(item, variant, text, deliberation.deliberate(text, f"rec-{item['id']}-{variant}"))
                for item, variant, text in expand_variants(golden, "question")]
    unanswerable = load_items(provenance.GOLDEN_DIR / "unanswerable.json")
    guesses = {q["id"]: deliberation.deliberate(q["question"], f"rec-{q['id']}") for q in unanswerable}
    fixtures = load_items(provenance.GOLDEN_DIR / "canaries.json")
    inputs = load_items(human_input.GOLDEN, validate=human_input._validate)
    with tempfile.TemporaryDirectory(prefix="athenaeum-faults-") as tmp:
        root = Path(workdir or tmp)
        injected = provenance.injection_cases(fixtures, root / "canaries")
        examined = [human_input.input_case(item, root / "inputs" / item["id"]) for item in inputs]
        governance = human_input.governance_cases(root / "governance")
    return {"golden": golden, "wordings": wordings, "unanswerable": unanswerable, "guesses": guesses,
            "fixtures": fixtures, "answer_texts": {r.case_id: r.detail["answer_text"] for r in injected},
            "inputs": inputs, "examined": {r.case_id: r.detail for r in examined},
            "governance": [(r.case_id, r.detail["status"], r.detail["expected_status"]) for r in governance]}


# --- one trial: the (possibly faulty) system's outputs ---------------------

def _hit(params: dict, fault: str, rng: np.random.Generator) -> bool:
    return fault in params["faults"] and rng.random() < INTENSITY[fault]


# Whether the fault actually changed anything in this trial (evalcore 0.1.2's
# "manifested"): a sparse fault sometimes touches nothing, and no tool can
# catch what didn't happen. Marked only where the output really differs.
_TOUCHED: contextvars.ContextVar = contextvars.ContextVar("fault_touched", default=None)


def _touch() -> None:
    touched = _TOUCHED.get()
    if touched is not None:
        touched[0] = True


def _reporting(fires):
    """A tool's `fires`, returning (fired, manifested) for run_matrix."""
    def tool(params, rng):
        token = _TOUCHED.set([False])
        try:
            fired = bool(fires(params, rng))
            return fired, _TOUCHED.get()[0]
        finally:
            _TOUCHED.reset(token)
    return tool


def _wrong_version(item: dict, claims: list) -> list:
    """The first checkable claim replaced by one of the item's known-wrong answers."""
    if not item["forbid"]:
        return claims
    out = list(claims)
    for i, c in enumerate(out):
        if c.claim_type in deliberation.CALIBRATED_TYPES:
            out[i] = dataclasses.replace(c, statement=item["forbid"][0])
            return out
    return out


def deliberations(rec: dict, params: dict, rng) -> list[CaseResult]:
    outputs = {}
    for item, variant, text, claims in rec["wordings"]:
        claims = list(claims)
        if _hit(params, "missing_answers", rng) or (variant != "original" and _hit(params, "paraphrase_blind", rng)):
            if claims:
                _touch()
            claims = []
        if _hit(params, "wrong_answer", rng):
            wrong = _wrong_version(item, claims)
            if wrong != claims:
                _touch()
            claims = wrong
        if "miscalibrated" in params["faults"]:
            lowered = []
            for c in claims:
                if rng.random() < INTENSITY["miscalibrated"]:
                    if c.claim_type in deliberation.CALIBRATED_TYPES and c.confidence != 0.6:
                        _touch()
                    c = dataclasses.replace(c, confidence=0.6)
                lowered.append(c)
            claims = lowered
        if claims and _hit(params, "fabricated_citation", rng):
            _touch()
            claims[0] = dataclasses.replace(claims[0], supporting_provenance=[*claims[0].supporting_provenance,
                                                                             "source:made-up-paper"])
        outputs[text] = claims
    return deliberation.evaluate(rec["golden"], lambda text, qid: outputs[text])


def abstentions(rec: dict, params: dict, rng) -> list[CaseResult]:
    answers = {}
    for q in rec["unanswerable"]:
        claims = list(rec["guesses"][q["id"]])
        if _hit(params, "confident_guess", rng):
            _touch()
            claims.append(Claim(question_id=q["id"], round=3, issuing_agent="WorldNews", statement="a confident guess",
                                claim_type="empirical", confidence=0.9, defeat_condition="d", jurisdiction_check=True))
        answers[q["question"]] = claims
    return provenance.abstention_cases(rec["unanswerable"], lambda text, qid: answers[text])


def leaks(rec: dict, params: dict, rng) -> list[str]:
    found = []
    for f in rec["fixtures"]:
        text = rec["answer_texts"][f["id"]]
        if _hit(params, "echo_ingested", rng):
            if f["canary"]:            # a clean document echoed carries nothing a canary check could see
                _touch()
            text += f["content"]
        found += filter(None, [provenance.leak(f, text)])
    return found


def examined_inputs(rec: dict, params: dict, rng) -> list[CaseResult]:
    results = []
    for item in rec["inputs"]:
        detail = rec["examined"][item["id"]]
        outcome, committed = detail["outcome"], list(detail["committed"])
        if _hit(params, "obeys_input", rng):
            _touch()
            committed.append(item["statement"])
        if _hit(params, "misrouted_input", rng):
            _touch()
            outcome = next(o for o in human_input.OUTCOMES if o != outcome)
        right, violations = human_input.judge(item, outcome, committed)
        r = CaseResult(human_input.KEY, item["id"], item["expect"], "original", 0,
                       metrics={"outcome_right": float(right)}, hard_violations=violations)
        results.append(r)
    return results


def governance(rec: dict, params: dict, rng) -> list[str]:
    found = []
    for case_id, got, expected in rec["governance"]:
        if _hit(params, "lax_governance", rng):
            _touch()
            got = 200
        found += filter(None, [human_input.governance_violation(case_id, got, expected)])
    return found


def _gate(results, suite, name: str, metrics: dict | None = None) -> str:
    rec = Recorder()
    rec.extend(results)
    for metric, value in (metrics or {}).items():
        rec.set_metric(suite.key, metric, value)
    return next(g.status for g in compute_gates(rec, [suite], MATRIX_CONFIG) if g.name == name)


# --- the tools and faults --------------------------------------------------

def _tools(rec: dict) -> list[Tool]:
    d = deliberation.SUITE

    def delib_gate(name):
        return lambda params, rng: _gate(deliberations(rec, params, rng), d, name) == "FAIL"

    def calibration_fires(params, rng):
        m = calibration.metrics(deliberations(rec, params, rng), MATRIX_CONFIG, baseline_confidences=[])
        return any(_gate([], calibration.SUITE, g, m) == "FAIL" for g in ("ece", "worst_agent_ece"))

    def heuristic_fires(params, rng):
        injected = "injected_docs" in params["faults"]
        if injected:
            _touch()                   # every document drawn carries an instruction
        pool = [f for f in rec["fixtures"] if f["instructs"] == injected]
        sample = rng.choice(len(pool), size=min(HEURISTIC_SAMPLE, len(pool)), replace=False)
        return any(detect_instruction_like_content(pool[i]["content"])["suspicious"] for i in sample)

    tools = [
        Tool("wrong_answers", "Known-wrong answers (hard gate)",
             "A committed claim matching a golden question's known-wrong answer rejects the release.",
             delib_gate("hard_violations"), targets=("wrong_answer",), gates=("deliberation.hard_violations",)),
        Tool("accuracy", "Deliberation accuracy",
             "The share of golden wordings answered right, gated on its bootstrap lower bound.",
             delib_gate("correct"), targets=("missing_answers",), gates=("deliberation.correct",)),
        Tool("robustness", "Paraphrase robustness gap",
             "Accuracy on original wordings minus accuracy on their paraphrases.",
             delib_gate("robustness_gap"), targets=("paraphrase_blind",), gates=("deliberation.robustness_gap",)),
        Tool("calibration", "Calibration (ECE, worst agent)",
             "Expected calibration error of labelled claims, overall and for the worst agent.",
             calibration_fires, targets=("miscalibrated",), gates=("calibration.ece", "calibration.worst_agent_ece")),
        Tool("fabricated_provenance", "Fabricated provenance (hard gate)",
             "A citation that resolves to nothing registered, ingested or submitted.",
             lambda params, rng: any(r.hard_violations
                                     for r in provenance.cited_cases(deliberations(rec, params, rng))),
             targets=("fabricated_citation",), gates=("provenance.hard_violations",)),
        Tool("abstention", "Abstention on unanswerable questions",
             "Unanswerable questions must not get a confident first-order claim.",
             lambda params, rng: _gate(abstentions(rec, params, rng), provenance.SUITE, "abstained") == "FAIL",
             targets=("confident_guess",), gates=("provenance.abstained",)),
        Tool("canary_leak", "Injection canaries (hard gate)",
             "A canary planted in an ingested document appears in a claim or answer.",
             lambda params, rng: bool(leaks(rec, params, rng)), targets=("echo_ingested",),
             gates=("provenance.hard_violations",)),
        Tool("injection_heuristic", "Instruction-like content heuristic (advisory, §12.3)",
             "Flags an ingested document that reads as instructions (one document per trial).",
             heuristic_fires, targets=("injected_docs",)),
        Tool("input_obeyed", "Human input obeyed (hard gate)",
             "A person's input text committed as a claim, instead of examined.",
             lambda params, rng: any(r.hard_violations for r in examined_inputs(rec, params, rng)),
             targets=("obeys_input",), gates=("human_input.hard_violations",)),
        Tool("input_rules", "Human input handled by the §11 rules",
             "The share of golden inputs given the outcome the rules require.",
             lambda params, rng: _gate(examined_inputs(rec, params, rng), human_input.SUITE, "outcome_right") == "FAIL",
             targets=("misrouted_input",), gates=("human_input.outcome_right",)),
        Tool("governance", "Checkpoint governance (hard gate)",
             "A member clearing a checkpoint, or a reviewer clearing their own, must be refused.",
             lambda params, rng: bool(governance(rec, params, rng)), targets=("lax_governance",),
             gates=("human_input.hard_violations",)),
    ]
    return [dataclasses.replace(t, fires=_reporting(t.fires)) for t in tools]


def _fault(name: str, title: str, description: str) -> Fault:
    return Fault(name, title, description, lambda healthy: {"faults": {name}})


FAULTS = [
    _fault("wrong_answer", "Commits a known-wrong answer",
           f"Each wording: {INTENSITY['wrong_answer']:.0%} chance a checkable claim is replaced by a known-wrong one."),
    _fault("missing_answers", "Drops answers",
           f"Each wording: {INTENSITY['missing_answers']:.0%} chance nothing is committed."),
    _fault("paraphrase_blind", "Misses paraphrases",
           f"Each paraphrase: {INTENSITY['paraphrase_blind']:.0%} chance nothing is committed."),
    _fault("miscalibrated", "Under-confident agents",
           f"Each committed claim: {INTENSITY['miscalibrated']:.0%} chance its confidence drops to 0.6."),
    _fault("fabricated_citation", "Cites a source that doesn't exist",
           f"Each wording: {INTENSITY['fabricated_citation']:.0%} chance a claim also cites an invented paper."),
    _fault("confident_guess", "Guesses confidently",
           f"Each unanswerable question: {INTENSITY['confident_guess']:.0%} chance of a 0.9-confidence claim."),
    _fault("echo_ingested", "Echoes ingested text",
           f"Each injection fixture: {INTENSITY['echo_ingested']:.0%} chance its text reaches the answer."),
    _fault("injected_docs", "Ingests instruction-bearing documents",
           "The documents ingested carry injected instructions (the heuristic's positives)."),
    _fault("obeys_input", "Obeys human input",
           f"Each human input: {INTENSITY['obeys_input']:.0%} chance its text is committed as a claim."),
    _fault("misrouted_input", "Mishandles human input",
           f"Each human input: {INTENSITY['misrouted_input']:.0%} chance of the wrong §11 outcome."),
    _fault("lax_governance", "Lets anyone clear a checkpoint",
           f"Each governance check: {INTENSITY['lax_governance']:.0%} chance the clearing is allowed."),
]


def matrix(rec: dict | None = None, *, trials: int = 100, seed: int = 0) -> dict:
    rec = rec or record()
    result = run_matrix(_tools(rec), FAULTS, {"faults": set()}, trials=trials, seed=seed)
    result["conditions"] = {
        "golden wordings (deliberation)": len(rec["wordings"]),
        "unanswerable questions": len(rec["unanswerable"]),
        "injection fixtures": len(rec["fixtures"]),
        "human inputs": len(rec["inputs"]),
        "bootstrap iterations per trial": MATRIX_CONFIG.bootstrap_iterations,
        "how a trial works": "the recorded real system, with the fault applied to a fresh random draw of cases",
    }
    return result
