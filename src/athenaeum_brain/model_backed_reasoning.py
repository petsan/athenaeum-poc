"""
Generic real-model fallback for Master Agents (body-design.md Section 4.5,
brain-design.md Section 6.7's serving_model field). When a routed agent's
own narrow deterministic computation finds nothing to say about a
question, it may ask a real backend model instead of silently producing
no claim -- the first time any Master Agent's OWN claims (not just
Engineering's sandboxed execution) are backed by something other than
hand-written toy logic.

Default model: OLMo 3 7B Instruct (AllenAI/AI2) -- see infra/proxmox/model-lab/ and
brain-session-log.md for why. Deliberately NOT used by Logic: Section 2.2
is explicit that Logic never asserts first-order claims, only procedural
ones, and a model-backed fallback producing a first-order claim would
violate that by construction, not just by convention -- MasterOfLogic
has no call site for this module anywhere.

Confidence is deliberately capped well below the 1.0 used for
mechanically-verified claims elsewhere in this codebase (primality,
kinematics, sandboxed execution) -- a raw model completion is genuinely
unverified until it actually survives cross-examination, and Section 5.1
requires every confidence value to be traceable to something, not
asserted. 0.6 matches the same "plausible but not yet checked" weight
human_input.py already uses for justified-but-unverified testimony.
"""
from __future__ import annotations
import contextlib
import contextvars
import re
from athenaeum_body.model_lab_registry import MODEL_LAB_ENDPOINTS
from athenaeum_body.model_serving import LlamaCppBackend, ModelSpec, BackendUnavailable
from athenaeum_body.elastic_workers import build_elastic_gpu_backend
from .claims import Claim

DEFAULT_MODEL = "olmo3-7b"  # was olmo2-1b until 2026-09-23 -- OLMo 2 1B
# turned out not to be AI2's newest or biggest public model (OLMo 3/3.1
# exist, up to 32B); swapped once that was verified live against
# Hugging Face, same resource footprint as the existing mistral-7b guest.
FALLBACK_CONFIDENCE = 0.6
# A raw completion can't state what would falsify its own content, so every
# fallback claim carries this same procedural defeat condition. Domain
# Fidelity's Physics fingerprint (Section 2.4.1: "presence of an explicit
# defeat condition") treats it as NOT explicit.
GENERIC_DEFEAT_CONDITION = ("a cross-examination challenge, or a conflicting mechanically-verified "
                            "claim from another agent")

# Section 2.4.3 re-grounding: agents whose model fallback is switched off
# for now, so they can only assert what their own grounded, deterministic
# computation produces. A context variable, not a module-level set, so
# suppression applied around one deliberation's exploration round can't
# leak into another thread's deliberation (the HTTP API is threaded).
_SUPPRESSED_AGENTS: contextvars.ContextVar[frozenset] = contextvars.ContextVar(
    "suppressed_fallback_agents", default=frozenset())


@contextlib.contextmanager
def fallback_suppressed(agent_names):
    """Within this block, model_backed_claim returns None for these agents."""
    token = _SUPPRESSED_AGENTS.set(_SUPPRESSED_AGENTS.get() | frozenset(agent_names))
    try:
        yield
    finally:
        _SUPPRESSED_AGENTS.reset(token)


def ask_model(question: str, model_name: str = DEFAULT_MODEL, n_predict: int = 96,
              timeout_seconds: float = 120.0, max_attempts: int = 5) -> str | None:
    """Returns the model's answer -- its completion cut to the answer itself
    (answer_only) -- or None if the backend is unreachable or only ever
    answered with nothing.

    Five attempts, not three (batch 10): measured live, OLMo 3 7B skips the
    answer and goes straight to invented new "Q:" turns in about 1 of 4
    completions for some prompts (3/12 for "what force acts on a stationary
    object?"). Since known-bugs #35 those count as no answer and are retried,
    so three attempts left roughly 1.6% of calls with no claim (0.25^3), and
    five leave about 0.1%. None is treated by every caller as 'no claim produced'
    -- the same outcome as an agent's own deterministic check finding
    nothing -- never as an error that should break the deliberation loop
    (Section 4.2's stateless-lease-holder discipline: a remote call
    failing should degrade gracefully, not crash the caller).

    Three real findings, not guesses: a 60s timeout intermittently
    tripped when many real fallback calls landed on the same single-model
    guest back to back (these guests queue requests rather than reject
    them outright, so a generous timeout is the honest fix); OLMo 2's own
    sampling occasionally produces a near-empty completion (observed
    directly: a single space, for an otherwise ordinary prompt) -- real
    sampling variance, retried here rather than surfaced as 'no claim' on
    one unlucky draw; and, found switching to OLMo 3 (2026-09-23), a raw
    unframed question reliably (not occasionally) produces an EMPTY
    completion from that model specifically -- unlike OLMo 2, it needs
    explicit continuation framing to know a response is expected. Fixed
    by wrapping the question in a minimal 'Q: ...\\nA:' frame before it
    ever reaches the backend, confirmed live to fix it deterministically
    (4/4 real calls), not just theorized. Fixed centrally, once, rather
    than leaving every call site (agents.py's six fallback sites, and any
    future one) to remember to retry or frame prompts individually."""
    if model_name not in MODEL_LAB_ENDPOINTS:
        return None
    framed_question = f"Q: {question}\nA:"
    spec = ModelSpec(name=model_name, vram_gb=0)
    cpu_backend = LlamaCppBackend(endpoints={model_name: MODEL_LAB_ENDPOINTS[model_name]},
                                   n_predict=n_predict, timeout_seconds=timeout_seconds)
    # Section 4.3/6.1: an opportunistic GPU worker (elastic_workers.py) is
    # preferred when one is configured AND healthy for this model right
    # now -- checked fresh on every attempt, never assumed from earlier in
    # the process. Implemented directly here rather than via
    # ModelServingLayer: that class's registry/CAS/LRU-eviction machinery
    # exists for routing across MANY models sharing a VRAM budget, which
    # this single-fixed-model utility function doesn't need -- constructing
    # a throwaway ModelRegistry just to satisfy that API would be ceremony
    # without benefit. The actual "never crash, fall back to CPU"
    # discipline is the same either way.
    gpu_backend = build_elastic_gpu_backend()

    for _ in range(max_attempts):
        response = None
        try:
            response = gpu_backend.infer(spec, framed_question)
        except BackendUnavailable:
            try:
                response = cpu_backend.infer(spec, framed_question)
            except BackendUnavailable:
                # Real bug caught running this under the full test suite's
                # back-to-back load: this used to `return None` immediately
                # on ANY timeout, never using the remaining retry attempts
                # -- only an empty-string response was retried. A
                # transient timeout under load is exactly the kind of
                # recoverable failure max_attempts exists for; falling
                # through to the next loop iteration (instead of
                # returning) is the actual fix, not just a bigger timeout.
                continue
        answer = answer_only(response or "")
        if answer:
            return answer
    return None


def answer_only(completion: str) -> str:
    """The answer the Q:/A: frame asked for, and nothing after it: the text
    up to the first line break, stripped. A small model doesn't stop at the
    end of its answer. Live, OLMo 3 answered "Gravity" and then carried on
    with an invented instruction and a whole new "Q: how can i become more
    assertive at work?" turn, all of which became the claim's statement
    (known-bugs #35, found by the batch 9 live smoke). A claim is one
    assertion, so the first line is the answer; whatever follows was never
    asked for. A completion that skips straight to a new "Q:" turn has no
    answer at all, and is treated as empty (so it is retried)."""
    first = completion.strip().split("\n", 1)[0].strip()
    return "" if first.startswith("Q:") else first


def model_backed_claim(*, agent_name: str, question: str, question_id: str,
                        claim_type: str = "empirical", model_name: str = DEFAULT_MODEL,
                        confidence: float = FALLBACK_CONFIDENCE) -> Claim | None:
    """Builds a Claim from a real model completion, or None if the
    backend couldn't be reached -- callers append this to their own
    deterministic claims list only when it's not None, exactly like any
    other 'nothing to add' outcome (Section 3.2). Also None, without any
    model call, for an agent currently being re-grounded (Section 2.4.3,
    fallback_suppressed).

    The statement is the answer AND the question it answers (known-bugs
    #36). A bare answer like "Gravity" is not a proposition: it can't be
    judged true or false on its own (the live model rightly said "no" when
    asked), and it made the same claim out of answers to unrelated
    questions, since claims are keyed by agent and statement (#22's
    self-containment rule)."""
    if agent_name in _SUPPRESSED_AGENTS.get():
        return None
    response = ask_model(question, model_name)
    if not response or not response.strip():
        return None
    asked = " ".join(question.split())   # one line, whatever the question's own whitespace
    return Claim(
        question_id=question_id, round=1, issuing_agent=agent_name,
        statement=f"{response.strip()} (in answer to: {asked})",
        claim_type=claim_type, confidence=confidence,
        defeat_condition=GENERIC_DEFEAT_CONDITION,
        jurisdiction_check=True,
        supporting_provenance=[f"llm:{model_name}"],
        serving_model=model_name,
    )


CHALLENGE_PROMPT = "Is the following statement true? Answer yes or no. Statement: {statement}"
# For a model claim, which is an answer to a question (known-bugs #36):
# measured live on OLMo 3 7B (batch 10), this phrasing judged 13/16 labelled
# question-answer pairs correctly. Every miss was a "no" to a TRUE answer;
# every false answer was rejected. Asking about "A (in answer to: Q)" got
# "no" every time, and a "Question: / Proposed answer:" phrasing rejected
# even "Paris" for France's capital. Hence, among other reasons, an unproven
# model's challenges are dissent only.
ANSWER_CHALLENGE_PROMPT = CHALLENGE_PROMPT.format(statement='The answer to "{question}" is "{answer}".')
_ANSWERING = re.compile(r"^(?P<answer>.*) \(in answer to: (?P<question>.*)\)$")


def model_challenge(claim: Claim, question_id: str, model_name: str = DEFAULT_MODEL) -> Claim | None:
    """Owner decision 10 (2026-09-26): a model may challenge a model-backed
    claim during idle re-examination. It is asked a plain yes/no question
    about the claim; an answer starting "no" is a challenge, and anything
    else (yes, unsure, unparseable, unreachable) is none -- a model's
    silence or rambling is never read as disagreement. Whether the
    challenge COUNTS is the caller's call (idle_evolution.reexamine):
    only an established model's does."""
    answering = _ANSWERING.match(claim.statement)
    prompt = (ANSWER_CHALLENGE_PROMPT.format(**answering.groupdict()) if answering
              else CHALLENGE_PROMPT.format(statement=claim.statement))
    verdict = ask_model(prompt, model_name, n_predict=8)
    words = (verdict or "").strip().lower().split()
    if not words or words[0].strip(".,!:;\"'") != "no":
        return None
    return Claim(
        question_id=question_id, round=2, issuing_agent=f"model:{model_name}",
        statement=f"{model_name} answers 'no' to whether '{claim.statement}' is true",
        claim_type="empirical", confidence=FALLBACK_CONFIDENCE,
        defeat_condition=GENERIC_DEFEAT_CONDITION, jurisdiction_check=True,
        relation="challenges", target_claim_id=claim.claim_id,
        supporting_provenance=[f"llm:{model_name}"], serving_model=model_name,
    )
