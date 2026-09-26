"""
Re-evaluation materiality (Section 7.2): a pure function over synthetic
Belief Graph deltas, exactly as the design specifies -- no backend needed.
Decides whether a change to a cited source's reputability grade is
material enough to warrant reopening a dormant answer.
"""
from __future__ import annotations
from athenaeum_body.reputability_store import GRADE_ORDER

SEVERE_GRADES = {"contested", "rejected"}

# Section 7.1/11.5: the one importance threshold (a placeholder). Questions
# rated below it are not reopened for material changes (7.3), and human
# input on them does not wait at a checkpoint (11.5, owner decision 5).
IMPORTANCE_THRESHOLD = 0.3


def frame_staleness(answer: dict) -> dict:
    """Section 7.2's third trigger (and Section 8's "stale framing" row): the
    question's own frame is outdated when framing the same question TODAY
    would route it to a different set of agents or classify it as asking
    for different output types -- e.g. a new Master Agent now claims
    jurisdiction the original deliberation never consulted. Frames are
    compared, not answers: a stale frame is material even if nothing the
    answer cited has changed. Answers without a recorded question/frame
    (written before 2026-09-26) can't be checked and report not stale."""
    if "question" not in answer or "frame" not in answer:
        return {"stale": False, "reasons": []}
    from .rounds import framing_round
    now = framing_round(answer["question"], "frame-check")
    then = answer["frame"]
    reasons = []
    added = sorted(set(now["routed_agents"]) - set(then.get("routed_agents", [])))
    dropped = sorted(set(then.get("routed_agents", [])) - set(now["routed_agents"]))
    if added:
        reasons.append(f"frame outdated: now also routed to {', '.join(added)}")
    if dropped:
        reasons.append(f"frame outdated: no longer routed to {', '.join(dropped)}")
    if now["output_types"] != then.get("output_types", now["output_types"]):
        reasons.append(f"frame outdated: output types now {now['output_types']} (were {then.get('output_types')})")
    return {"stale": bool(reasons), "reasons": reasons}


def materiality_inputs(answer: dict, store) -> tuple[dict, dict]:
    """Reads, from a ReputabilityStore, the two live inputs is_material
    needs for every source the answer cited: its current grade, and the
    grade it would have today under the standard that was in force when
    the answer was produced (snapshots predating 6.5 were all v0)."""
    current, under_prior_standard = {}, {}
    for source_id, snapshot in answer.get("source_grades_at_use", {}).items():
        current[source_id] = store.current_grade(source_id)
        under_prior_standard[source_id] = store.grade_under(source_id, snapshot.get("standard_version", 0))
    return current, under_prior_standard


def is_material(answer: dict, current_grades: dict, threshold: int = 1,
                prior_standard_grades: dict | None = None) -> dict:
    """
    answer: a completed deliberation's answer dict, with 'source_grades_at_use'
        (the non-retroactively-attached snapshot from loop.py) -- i.e. what
        the answer's leading conclusion actually relied on, and at what
        grade, at the time it was produced.
    current_grades: {source_id: {'grade': ..., 'version': ...}} -- the
        CURRENT live grade for each source, e.g. from
        ReputabilityStore.current_grade() called per cited source.
    threshold: minimum ordinal grade-band distance (GRADE_ORDER) that
        counts as material on its own, even without hitting SEVERE_GRADES.
    prior_standard_grades: optional {source_id: grade the source would
        have NOW under the standard in force at time of use} (see
        materiality_inputs). When that differs from the current grade, the
        reputability standard itself (6.5) changed that source's grade --
        7.2's fourth trigger, material regardless of threshold, and named
        as such so a reopened answer's diff shows the real cause.

    Returns {'material': bool, 'reasons': [...]} -- reasons are always
    populated when material, so a reopened question's diff (Section 7.3)
    has something concrete to show, not just a boolean.
    """
    reasons = []
    grades_at_use = answer.get("source_grades_at_use", {})

    for source_id, snapshot in grades_at_use.items():
        current = current_grades.get(source_id)
        if current is None:
            continue  # no live grade available -- not evidence of change either way

        prior_grade, now_grade = snapshot["grade"], current["grade"]
        if prior_grade == now_grade:
            continue

        # Owner decision 9 (2026-09-26): only a DOWNGRADE is material. An
        # upgrade can strengthen a conclusion but can't make it wrong, and
        # routine use corroborates common sources upward, which used to
        # reopen every answer that ever used them (§81). The new weight is
        # picked up whenever the answer reopens for another reason. This
        # applies to evidence- and standard-driven changes alike.
        if (prior_grade in GRADE_ORDER and now_grade in GRADE_ORDER
                and GRADE_ORDER.index(now_grade) > GRADE_ORDER.index(prior_grade)):
            continue

        # Rule 4 (Section 7.2): the standard changed version in a way that
        # altered this source's grade -- the old standard, applied to the
        # same evidence, would NOT give today's grade.
        old_standard_grade = (prior_standard_grades or {}).get(source_id)
        if old_standard_grade is not None and old_standard_grade != now_grade:
            reasons.append(
                f"{source_id}: reputability standard amended "
                f"(v{snapshot.get('standard_version', 0)} -> v{current.get('standard_version', 0)}) "
                f"moved grade {prior_grade} -> {now_grade}")
            continue

        # Rule 1 (Section 7.2): newly contested/overturned is ALWAYS material,
        # regardless of ordinal distance.
        if now_grade in SEVERE_GRADES and prior_grade not in SEVERE_GRADES:
            reasons.append(f"{source_id}: grade newly {now_grade} (was {prior_grade})")
            continue

        # Rule 2: a downgrade whose ordinal distance meets the configured threshold.
        try:
            delta = abs(GRADE_ORDER.index(now_grade) - GRADE_ORDER.index(prior_grade))
        except ValueError:
            delta = 0
        if delta >= threshold:
            reasons.append(f"{source_id}: grade moved {prior_grade} -> {now_grade} (delta {delta})")

    return {"material": len(reasons) > 0, "reasons": reasons}


def forecast_is_material(forecast: dict) -> dict:
    """Section 5.4's last bullet: a Forecast's resolution is ALWAYS
    material, regardless of importance rating -- forecast accuracy is only
    ever knowable in hindsight, so this deliberately ignores the
    threshold/severity logic above and only asks whether the forecast has
    been resolved (output_types.resolve_forecast)."""
    if forecast.get("resolved") is not None:
        return {"material": True, "reasons": [f"forecast resolved: outcome={forecast['resolved']}"]}
    return {"material": False, "reasons": []}
