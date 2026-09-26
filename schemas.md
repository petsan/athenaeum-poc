# Field-Level Schemas

Concrete shapes for `body-design.md` Section 5.1's five stores and `brain-design.md` Section 3.5's claim structure. The POC's `schemas.py`/`claims.py` implement these; this doc is the canonical reference so future sessions don't redefine fields inconsistently.

## Belief Graph Node
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | unique |
| `node_type` | str | yes | e.g. "claim", "question_frame", "source" |
| `data` | dict | yes | type-specific payload |
| `created_at` | float (unix ts) | yes | |

## Belief Graph Edge
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | |
| `source_id` | str | yes | node id |
| `target_id` | str | yes | node id |
| `edge_type` | str | yes | e.g. "corroborates", "supersedes" |
| `data` | dict | no | |

**As implemented (2026-09-26, `belief_graph_store.py` + `athenaeum_brain/belief_graph.py`):** nodes and edges are write-once (re-writing an id returns the original); both carry a store-wide monotonically increasing `seq` in `data`, so "added after X" never depends on wall-clock time. Node ids: `question:<id>`, `answer:<question_id>:v<version>`, `claim:<agent>::<statement>` (the canonical `claim_key`, so the same claim reached from two questions is one node; `data` holds `statement`, `issuing_agent`, `claim_type`, normalized `subject`), `source:<source_id>`. Edge ids are `<source>|<type>|<target>`; types used: `has_version` (question→answer), `relies_on` (answer→committed claim), `dissents` (answer→challenged claim), `cites` (claim→source).

## Provenance Entry
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | |
| `content_hash` | str | yes | content-address (`sha256:...`) of the source |
| `metadata` | dict | no | `license`; optional `cites` (list of source ids this one cites or derives from, curator-supplied — read by `dispute_resolution.check_independence`, Section 6.4.2). `cites` is present only when non-empty. |

## Reputability Grade
| Field | Type | Required | Notes |
|---|---|---|---|
| `subject_id` | str | yes | source id, human submitter id, or model name |
| `subject_type` | str | yes | `"source"` \| `"human"` \| `"model"` |
| `grade` | str | yes | e.g. "foundational", "contested", "rejected" |
| `rationale` | str | no | |
| `version` | int | yes | index of this decision in the subject's own grade history (increments only when the grade actually changes) |

As implemented in `reputability_store.py` (Section 6.5, 2026-09-26): each stored grade entry also carries `decided_under` (int — the standard version in force when it was decided) and `cause` (`"evidence"` \| `"standard_amendment"`); entries written before versioning existed read back as `decided_under: 0, cause: "evidence"`. `current_grade()` returns the projection `{grade, version, standard_version}`, where `standard_version` is the standard in force now — this is what answers snapshot as `source_grades_at_use`.

## Consolidation Entry (Section 10) — `consolidation_store.py`, keyed by `consolidation.claim_key` (`agent::statement`)
| Field | Type | Tier | Notes |
|---|---|---|---|
| `tier` | str | both | `"B"` (validated, tracked) or `"C"` (compacted canon) |
| `statement` | str | both | |
| `cycles` | int | both | survival cycles up to compaction; on a C node it must equal the archived trace's (§9.5 audit) |
| `sources` | list[str] | both | distinct supporting sources seen |
| `cycle_ids` | list[str] | both | idle cycles already counted — makes `record_survival` idempotent, preserved across compaction |
| `confidence_history` | list[float] | B | evidence weight per survival (idle cycles record *current weighted* confidence, so erosion blocks promotion) |
| `archive_ref` | str | both | `None` on B until compacted; on C, the content-addressed pointer to the full archived trace |
| `confidence` | float | C | the last confidence at compaction — must equal the archive's final value |
| `cycles_since_compaction`, `current_confidence` | int, float | C | survival *after* compaction, kept separate so the node keeps matching its archive |
| `decompacted_from`, `decompaction_reason` | str, str | B | present when a C node was expanded back (§10.5) because it was challenged or lost its support |

## Reputability Standard (Section 6.5)
| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | int | yes | 0 is the seed standard (Section 6.1); strictly increasing; the list never shrinks |
| `params` | dict | yes | exactly `rejected_min_challenges`, `foundational_min_corroborations` (positive ints) |
| `rationale` | str | yes | non-empty; why this version was adopted |

## Question Ledger Entry
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | |
| `status` | str | yes | `queued\|active\|suspended\|completed\|archived` |
| `importance` | float | yes | 0–1, computed per Section 7.1 by `reopening.importance_rating` (breadth of non-Logic domains, multiple output types, dependents, requester priority); revisable via `QuestionLedger.update_importance` |
| `created_at` | float | yes | |
| `versions` | list[dict] | yes | append-only, never overwritten; each is a Deliberation Answer (below) |

## Deliberation Answer (one ledger version) — produced by `athenaeum_brain/loop.py`
| Field | Type | Required | Notes |
|---|---|---|---|
| `question` | str | yes | the question text, so a reopen never depends on the caller remembering it (answers written before 2026-09-26 lack it and cannot be reopened) |
| `frame` | dict | yes | the framing round's output: `question`, `routed_agents`, `output_types` |
| `committed` | list[Claim] | yes | claims that survived cross-examination (Section 4.4) |
| `dissent` | list[dict] | yes | `{claim, challenges}` for each challenged claim |
| `plural_answers` | list[dict] | yes | jurisdictional conflicts, never collapsed (Section 4.2) |
| `output_answer` | dict | yes | `{output_types, sections}` — one section per classified type; Forecast/Recommendation sections are `{available: false, reason}` when no committed claim supports them |
| `source_grades_at_use` | dict | no | present when a ReputabilityStore was used: `{source_id: {grade, version, standard_version}}` snapshot (Section 6.3) |
| `reopen_context` | dict | no | on a reopened version: `prior_version`, `reasons`, `prior_answer` (without its own `reopen_context`), `expanded_traces`, optional `forecast_resolution` |
| `diff` | dict | no | on a reopened version (Section 7.3): `added`, `removed`, `weight_changes`, `leading_conclusion`, `plural_answers`, `cause` |
| `fitness_at_use`, `unadmitted_models` | dict, list | no | present when a ModelFitnessStore was used (Section 6.7): `{"agent::model": factor}` snapshot, and models that backed a committed claim without being admitted |
| `regrounding_agents` | list[str] | no | agents whose model fallback was suppressed for this deliberation (Section 2.4.3 re-grounding or escalation) |
| `verification` | dict | no | task 44 routing report: `{routed, skipped_reason}` — `skipped_reason` names how many verifiable claims went unverified because `execution_sandbox.enabled` is false |

## Claim (Brain, Section 3.5) — implemented in `athenaeum_brain/claims.py`
| Field | Type | Required | Notes |
|---|---|---|---|
| `claim_id` | str | yes | auto-generated `claim-<16 hex>` from a uuid4 — globally unique across processes (known-bugs.md #23); ids in answers written before 2026-09-26 are per-process counters |
| `question_id` | str | yes | |
| `round` | int | yes | which deliberation round produced this |
| `issuing_agent` | str | yes | |
| `statement` | str | yes | |
| `claim_type` | str | yes | `empirical\|formal\|executable\|normative\|traditional\|human_input\|procedural` |
| `confidence` | float | yes | 0–1, calibrated per Section 5.1 |
| `defeat_condition` | str | yes | |
| `jurisdiction_check` | bool | yes | |
| `relation` | str | yes | `asserts\|corroborates\|challenges\|abstains\|clarifies` |
| `target_claim_id` | str | no | required if `relation != "asserts"` |
| `supporting_provenance` | list[str] | no | |
| `status` | str | yes | `proposed\|committed` (Section 4.4) |
| `subject` | str | no | conflict-grouping key (see `rounds.py`; still a simplification, Section 4.2) |
| `argument` | dict | no | `{premises: [...], conclusion: str}` for Logic's validity check (Section 2.2) |
| `output_type_relevance` | list[str] | no | which of `research\|forecast\|recommendation` the claim bears on |
| `serving_model` | str | no | which local model produced this (Section 6.7); set on Engineering's sandbox-verified claims and on every model-backed fallback claim, `None` for purely deterministic claims |
| `reputability_factor` | float | no | set only by `synthesis_round` (Section 4.1): weakest-link grade weight across `supporting_provenance`, grades at time of use |
| `fitness_factor` | float | no | set only by `synthesis_round` (Section 6.7): (agent, serving_model) fitness at time of use; 1.0 deterministic, 0.0 unadmitted model |
| `weighted_confidence` | float | no | `confidence × reputability_factor × fitness_factor` (each only when its lookup was given); `confidence` itself is never modified |
| `forecast` | dict | no | Section 5.4: keyword args for `output_types.build_forecast_answer` (`statement, probability, resolution_criterion, resolution_source, deadline, sensitivity, assumptions`) when the claim *is* a forecast. The probability lives only here, never in `confidence`. |
| `recommendation_option` | dict | no | Section 5.4: `{option, serves_objective, reversibility}` when the claim's conclusion is one course of action a Recommendation can weigh |

**Not yet specified:** the Model Registry entry shape beyond what `model_serving.py` implements (name, vram_gb, capabilities, weights_ref) — fine for now, revisit once a real backend is integrated.
