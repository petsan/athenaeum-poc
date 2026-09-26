"""
Reputability Engine STORAGE mechanics (brain-design.md Section 6):
versioned grading, evidence accumulation, non-retroactive attachment,
the dispute-resolution log, and the versioned standard itself (6.5). The
Body stores and serves this data; the grading *policy* below is a simple,
explicitly-labeled placeholder -- real judgment (brain-design.md 6.1-6.5)
is a Brain concern once a model is backing it, not implemented here.

Standard versioning (6.5): the grading rule is parameterized, and each
set of parameters is a numbered, rationale-bearing version of the
standard. Version 0 is the seed standard (6.1). Adopting version N+1
governs every decision from then on; nothing decided under an earlier
version is rewritten -- sources whose grade changes under the new version
get a NEW grade entry tagged with the amendment as its cause, appended
after the old ones, and every prior standard stays on record.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog

# Ordinal scale for materiality comparisons (athenaeum_brain/reevaluation.py).
GRADE_ORDER = ["rejected", "contested", "provisionally_accepted", "foundational"]

UNGRADED_DEFAULT = "provisionally_accepted"

# Version 0's parameters -- exactly the thresholds the placeholder policy
# has always used, so every grade decided before versioning existed is,
# correctly, a v0 decision.
SEED_STANDARD_PARAMS = {
    "rejected_min_challenges": 3,        # with zero corroborations
    "foundational_min_corroborations": 5,  # with zero challenges
}


def _grade_from_tally(corroborated: int, challenged: int, params: dict = SEED_STANDARD_PARAMS) -> str:
    """Explicitly a placeholder policy, not the real judgment (Section 6.1)."""
    if corroborated == 0 and challenged >= params["rejected_min_challenges"]:
        return "rejected"
    if challenged > 0 and challenged >= corroborated:
        return "contested"
    if corroborated >= params["foundational_min_corroborations"] and challenged == 0:
        return "foundational"
    return "provisionally_accepted"


def _validate_params(params: dict) -> dict:
    if set(params) != set(SEED_STANDARD_PARAMS):
        raise ValueError(f"standard params must be exactly {sorted(SEED_STANDARD_PARAMS)}, got {sorted(params)}")
    for k, v in params.items():
        if not isinstance(v, int) or v < 1:
            raise ValueError(f"standard param {k!r} must be a positive int, got {v!r}")
    return dict(params)


@dataclass
class ReputabilityStore:
    log: CheckpointLog

    def _state(self) -> dict:
        state = self.log.read_latest() or {"tallies": {}, "grade_versions": {}, "disputes": []}
        # Checkpoints written before 6.5 existed carry no standards list;
        # everything in them was decided under the seed standard.
        state.setdefault("standards", [{
            "version": 0, "params": dict(SEED_STANDARD_PARAMS),
            "rationale": "seed standard (Section 6.1) -- bootstrap heuristics, not permanent doctrine",
        }])
        return state

    @staticmethod
    def _in_force(state: dict) -> dict:
        return state["standards"][-1]

    def record_outcome(self, subject_id: str, subject_type: str, outcome: str) -> None:
        """Section 6.2: every use of a source records an outcome against it.
        outcome is 'corroborated' or 'challenged'. Graded under the
        standard currently in force."""
        assert outcome in ("corroborated", "challenged")
        state = self._state()
        standard = self._in_force(state)
        tally = state["tallies"].setdefault(subject_id, {"subject_type": subject_type, "corroborated": 0, "challenged": 0})
        tally[outcome] += 1
        new_grade = _grade_from_tally(tally["corroborated"], tally["challenged"], standard["params"])
        versions = state["grade_versions"].setdefault(subject_id, [])
        if not versions or versions[-1]["grade"] != new_grade:
            versions.append({"grade": new_grade, "version": len(versions),
                             "decided_under": standard["version"], "cause": "evidence"})
        self.log.write_checkpoint(state, label="reputability")

    def current_grade(self, subject_id: str) -> dict:
        """Returns {'grade', 'version', 'standard_version'} -- the LIVE
        current grade, which may differ from a grade snapshotted at an
        earlier time-of-use (Section 6.3's non-retroactive-attachment
        guarantee). standard_version is the standard in force now, under
        which this grade holds; a snapshot of it is what lets materiality
        (7.2) tell a standard-driven change from an evidence-driven one."""
        state = self._state()
        in_force = self._in_force(state)["version"]
        versions = state["grade_versions"].get(subject_id)
        if not versions:
            return {"grade": UNGRADED_DEFAULT, "version": 0, "standard_version": in_force}
        latest = versions[-1]
        return {"grade": latest["grade"], "version": latest["version"], "standard_version": in_force}

    def grade_history(self, subject_id: str) -> list[dict]:
        """Every grade decision ever made for this source, oldest first, each
        tagged with the standard it was decided under and its cause."""
        return [{"decided_under": 0, "cause": "evidence", **v}
                for v in self._state()["grade_versions"].get(subject_id, [])]

    # --- Section 6.5: the standard itself --------------------------------

    def standards(self) -> list[dict]:
        """Full history of the standard, oldest first. Never shrinks."""
        return self._state()["standards"]

    def current_standard(self) -> dict:
        return self._in_force(self._state())

    def grade_under(self, subject_id: str, standard_version: int) -> str:
        """What this source's grade WOULD be today -- its current evidence --
        under the given (possibly superseded) standard. Pure read: records
        nothing."""
        state = self._state()
        params = next(s["params"] for s in state["standards"] if s["version"] == standard_version)
        tally = state["tallies"].get(subject_id)
        if tally is None:
            return UNGRADED_DEFAULT
        return _grade_from_tally(tally["corroborated"], tally["challenged"], params)

    def adopt_standard(self, params: dict, rationale: str) -> dict:
        """Section 6.5: version N+1 supersedes N for new decisions. Every
        source whose grade differs under the new standard gets a new,
        appended grade entry (cause 'standard_amendment'); its earlier
        entries are untouched. Returns {'version', 'regraded': [...]} so a
        caller can see exactly which sources the amendment moved."""
        if not rationale or not rationale.strip():
            raise ValueError("a standard amendment requires a written rationale (Section 6.5)")
        state = self._state()
        version = self._in_force(state)["version"] + 1
        params = _validate_params(params)
        state["standards"].append({"version": version, "params": params, "rationale": rationale})

        regraded = []
        for subject_id, tally in state["tallies"].items():
            versions = state["grade_versions"].setdefault(subject_id, [])
            new_grade = _grade_from_tally(tally["corroborated"], tally["challenged"], params)
            old_grade = versions[-1]["grade"] if versions else UNGRADED_DEFAULT
            if new_grade != old_grade:
                versions.append({"grade": new_grade, "version": len(versions),
                                 "decided_under": version, "cause": "standard_amendment"})
                regraded.append({"subject_id": subject_id, "from": old_grade, "to": new_grade})
        self.log.write_checkpoint(state, label="reputability")
        return {"version": version, "regraded": regraded}

    # --- Section 6.4 -------------------------------------------------------

    def log_dispute(self, subject_id: str, claim_ids: list[str], rationale: str, ruling: str,
                    dispute_id: str | None = None) -> None:
        """Section 6.4: dispute resolution, logged permanently with rationale.
        A dispute_id makes the write idempotent -- logging the same id twice
        (e.g. a killed-and-resumed idle-evolution cycle) records it once."""
        state = self._state()
        if dispute_id is not None and any(d.get("dispute_id") == dispute_id for d in state["disputes"]):
            return
        entry = {"subject_id": subject_id, "claim_ids": claim_ids,
                 "rationale": rationale, "ruling": ruling}
        if dispute_id is not None:
            entry["dispute_id"] = dispute_id
        state["disputes"].append(entry)
        self.log.write_checkpoint(state, label="reputability")

    def disputes_for(self, subject_id: str) -> list[dict]:
        return [d for d in self._state()["disputes"] if d["subject_id"] == subject_id]
