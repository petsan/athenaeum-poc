"""
Re-evaluation materiality (Section 7.2): a pure function over synthetic
Belief Graph deltas, exactly as the design specifies -- no backend needed.
Decides whether a change to a cited source's reputability grade is
material enough to warrant reopening a dormant answer.
"""
from __future__ import annotations
from athenaeum_body.reputability_store import GRADE_ORDER

SEVERE_GRADES = {"contested", "rejected"}


def is_material(answer: dict, current_grades: dict, threshold: int = 1) -> dict:
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

        # Rule 1 (Section 7.2): newly contested/overturned is ALWAYS material,
        # regardless of ordinal distance.
        if now_grade in SEVERE_GRADES and prior_grade not in SEVERE_GRADES:
            reasons.append(f"{source_id}: grade newly {now_grade} (was {prior_grade})")
            continue

        # Rule 2: ordinal distance exceeds the configured threshold, either direction.
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
