# Tech Stack Decision

The design docs deliberately left implementation choices abstract for elasticity. This is the concrete decision, made now so future sessions don't each pick differently.

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.10+ | Matches the proof-of-work slices already built; broad library support for the ingestion/model-serving layers. |
| Storage engine (Tier 2/3) | Flat-file content-addressed store (as implemented in `content_addressed.py`) | Simple, dependency-free, already proven. Revisit only if throughput at real scale demands a real KV store (e.g. RocksDB) — not needed yet. |
| Serialization | JSON (canonical, sorted-keys) for checkpoints/schemas | Human-inspectable, hashes deterministically. Revisit for binary formats only if checkpoint size becomes a measured problem. |
| Hashing (content-addressing) | SHA-256, prefixed `sha256:` | Standard, collision-resistant, already implemented. |
| Config format | YAML | Matches the `body-design.md` config examples directly. |
| GPU-backed model serving | vLLM | Continuous batching, multi-GPU, matches elastic pool design (see chat decision on local model tooling). |
| CPU-fallback model serving | llama.cpp (server mode) | Only realistic dependency-light CPU path; matches the single-core-floor requirement. |
| Testing | pytest | Already used in all delivered test suites. |
| Packaging | `pyproject.toml`, `src/` layout | Already in place in `athenaeum-body-poc`. |

**Not yet decided:** distributed-worker transport (how the ~200-core pool receives work units), and whether the Question Ledger's index needs a real database once question volume is high. Both deferred until the relevant backlog phase (7 and 3, respectively) is reached for real.
