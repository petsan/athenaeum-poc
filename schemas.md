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

## Provenance Entry
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | |
| `content_hash` | str | yes | content-address (`sha256:...`) of the source |
| `metadata` | dict | no | fetch date, license, etc. |

## Reputability Grade
| Field | Type | Required | Notes |
|---|---|---|---|
| `subject_id` | str | yes | source id, human submitter id, or model name |
| `subject_type` | str | yes | `"source"` \| `"human"` \| `"model"` |
| `grade` | str | yes | e.g. "foundational", "contested", "rejected" |
| `rationale` | str | no | |
| `version` | int | yes | standard version this grade was issued under (Section 6.5) |

## Question Ledger Entry
| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | str | yes | |
| `status` | str | yes | `queued\|active\|suspended\|completed\|archived` |
| `importance` | float | yes | 0–1, computed per Section 7.1 |
| `created_at` | float | yes | |
| `versions` | list[dict] | yes | append-only, never overwritten |

## Claim (Brain, Section 3.5) — implemented in `athenaeum_brain/claims.py`
| Field | Type | Required | Notes |
|---|---|---|---|
| `claim_id` | str | yes | auto-generated |
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
| `serving_model` | str | no | which local model produced this (Section 6.7) — not yet wired into the POC's deterministic agents |

**Not yet specified:** the Model Registry entry shape beyond what `model_serving.py` implements (name, vram_gb, capabilities, weights_ref) — fine for now, revisit once a real backend is integrated.
