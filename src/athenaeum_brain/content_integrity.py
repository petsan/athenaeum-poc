"""
Content Integrity (Section 12): nothing the system reads -- an ingested
source, a retrieved passage, a human submission -- is ever executed as an
instruction. Section 12.1's core rule is enforced BY CONSTRUCTION (no code
path exists for claim content to reach anything other than the claim
pipeline -- see tests/test_content_integrity.py's structural scan), not by
this module. This module implements the one piece that IS runtime logic:
Section 12.3's advisory instruction-like-content heuristic, feeding into
reputability the same way any other cross-examination signal does.
"""
from __future__ import annotations
import re
from athenaeum_body.reputability_store import ReputabilityStore

# Deliberately a flat, readable list rather than one dense regex -- easy to
# extend, and each pattern's intent is legible on its own. Advisory only
# (Section 12.3 / Open Question 8's resolution below), never a gate.
_INSTRUCTION_LIKE_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) instructions",
    r"disregard (the |all )?(previous|prior|above|rules|instructions)",
    r"you (must|should|will) now",
    r"as (the|an) (system|ai|assistant)\b",
    r"new instructions?\s*:",
    r"system\s*:",
    r"override (the )?(previous|system|prior)",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INSTRUCTION_LIKE_PATTERNS]


def detect_instruction_like_content(text: str) -> dict:
    """Section 12.3: a heuristic, necessarily imperfect (Open Question 8)
    detector for content that READS as an attempt to instruct rather than
    inform. Purely informational -- matching this never itself rejects or
    alters anything; see record_instruction_like_signal for how it's
    actually used."""
    matched = [p.pattern for p in _COMPILED if p.search(text)]
    return {"suspicious": len(matched) > 0, "matched_patterns": matched}


def record_instruction_like_signal(reputability: ReputabilityStore, subject_id: str,
                                    subject_type: str, text: str) -> dict:
    """Section 12.3 + Open Question 8's resolution: a detected instruction-
    like pattern contributes exactly ONE ordinary 'challenged' outcome to
    the subject's existing reputability tally -- the same weight any other
    cross-examination challenge carries, not a separate override channel
    and not an automatic rejection. This is the concrete answer to Open
    Question 8 ("how much weight should the heuristic carry"): the same
    weight as one challenge, because the heuristic's false-positive rate
    isn't well enough characterized (Section 12.3 calls it "necessarily
    imperfect") to justify giving it more leverage than an ordinary
    cross-examination outcome already has. A source/submitter genuinely
    engaging in a PATTERN of this still accumulates toward rejection
    exactly the way repeated challenges from any other cause would
    (Section 6.2's ordinary tally mechanism), which is what Section 12.3
    actually asks for -- "a pattern... is grounds for a low grade" -- not
    single-instance rejection."""
    detection = detect_instruction_like_content(text)
    if detection["suspicious"]:
        reputability.record_outcome(subject_id, subject_type, "challenged")
    return detection
