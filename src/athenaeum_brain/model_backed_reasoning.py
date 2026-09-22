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
from athenaeum_body.model_lab_registry import MODEL_LAB_ENDPOINTS
from athenaeum_body.model_serving import LlamaCppBackend, ModelSpec, BackendUnavailable
from athenaeum_body.elastic_workers import build_elastic_gpu_backend
from .claims import Claim

DEFAULT_MODEL = "olmo3-7b"  # was olmo2-1b until 2026-09-23 -- OLMo 2 1B
# turned out not to be AI2's newest or biggest public model (OLMo 3/3.1
# exist, up to 32B); swapped once that was verified live against
# Hugging Face, same resource footprint as the existing mistral-7b guest.
FALLBACK_CONFIDENCE = 0.6


def ask_model(question: str, model_name: str = DEFAULT_MODEL, n_predict: int = 96,
              timeout_seconds: float = 120.0, max_attempts: int = 3) -> str | None:
    """Returns the model's raw completion, or None if the backend is
    unreachable. None is treated by every caller as 'no claim produced'
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
        if response and response.strip():
            return response
    return None


def model_backed_claim(*, agent_name: str, question: str, question_id: str,
                        claim_type: str = "empirical", model_name: str = DEFAULT_MODEL,
                        confidence: float = FALLBACK_CONFIDENCE) -> Claim | None:
    """Builds a Claim from a real model completion, or None if the
    backend couldn't be reached -- callers append this to their own
    deterministic claims list only when it's not None, exactly like any
    other 'nothing to add' outcome (Section 3.2)."""
    response = ask_model(question, model_name)
    if not response or not response.strip():
        return None
    return Claim(
        question_id=question_id, round=1, issuing_agent=agent_name,
        statement=response.strip(),
        claim_type=claim_type, confidence=confidence,
        defeat_condition="a cross-examination challenge, or a conflicting mechanically-verified claim from another agent",
        jurisdiction_check=True,
        supporting_provenance=[f"llm:{model_name}"],
        serving_model=model_name,
    )
