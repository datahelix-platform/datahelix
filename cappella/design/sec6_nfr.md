# Section 6: Non-Functional Requirements

**Status:** Draft v0.1  
**Last updated:** 2026-03-25

---

## 6.1 Performance

| Metric | Target | Notes |
|--------|--------|-------|
| Sync throughput | ≥ 500 records/minute | For batch adapter syncs against a local SQLite Hippo |
| Resolution latency (≤10 samples, all REUSE) | ≤ 2 seconds | Hippo queries only; no Canon BUILD triggered |
| Resolution latency (≤10 samples, BUILD) | ≤ Canon execution time + 500ms | Canon dominates; Cappella overhead ≤ 500ms |
| Async resolution startup | ≤ 200ms to return 202 | Return run_id immediately; processing starts async |
| Health endpoint | ≤ 100ms | Cached adapter health; not a live connectivity check every call |

---

## 6.2 Reliability

- **Partial success over abort.** Adapter sync runs and collection resolutions never abort on partial failure. Failed items are logged and counted.
- **Idempotent upserts.** Running the same sync twice produces the same Hippo state. ExternalID lookup ensures no duplicate entities.
- **Deterministic selection.** For a given cohort criteria + selection strategy, the same datasets are chosen every time (until Hippo state changes). Resolution runs are reproducible.
- **No data loss on Cappella failure.** All writes are to Hippo (durable). If Cappella crashes mid-sync, restarting and re-running the sync is safe — upsert idempotency prevents duplicates.

---

## 6.3 Scalability

Cappella's scalability tier model mirrors Hippo's:

| Tier | Cohort size | Hippo backend | Notes |
|------|-------------|--------------|-------|
| 1 (laptop/workstation) | ≤ 500 samples | SQLite | Single process, synchronous |
| 2 (lab server) | ≤ 5,000 samples | SQLite or PostgreSQL | Async resolution, concurrent Canon calls |
| 3 (cloud/HPC) | ≤ 50,000 samples | PostgreSQL | Distributed Canon, parallel adapter syncs |

**Opinion (mark for review):** For v0.1, Cappella targets Tier 1 only. Tier 2/3 requires connection pooling, a task queue (Celery, RQ, or similar), and Canon running as a separate service. These are deferred to v0.2/v0.3. The architecture is designed to be stateless so horizontal scaling is straightforward when needed.

---

## 6.4 Correctness

- **Conflict detection is never silent.** Every field conflict produces a `HarmonizationConflict` provenance event. No data is silently overwritten without an audit trail.
- **Unresolved items are always surfaced.** The `HarmonizedCollection.unresolved` list is never empty-by-default — every unresolved sample has a structured reason.
- **Schema conformance.** Every adapter transform is validated against the Hippo schema for the declared entity type before upsert. Mismatched fields raise `AdapterTransformError`, not silent truncation.
- **Provenance on every write.** No entity is created or updated by Cappella without a structured provenance context. The audit trail is always complete.

---

## 6.5 Extensibility

- **All adapters are plugins.** `cappella.adapters` entry point group. Adding a new external system requires zero changes to Cappella core.
- **All selection strategies are plugins.** `cappella.selection_strategies` entry point group.
- **Trigger actions are open.** New action types can be registered without modifying the trigger engine.
- **Cappella can run embedded.** As a Python library (no REST service required). Composer can import Cappella directly.

---

## 6.6 Security

- **Credentials in environment variables.** Adapter credentials (`STARLIMS_API_TOKEN`, etc.) are never stored in `cappella.yaml`; they are referenced via `${ENV_VAR}` substitution.
- **Hippo auth passthrough.** Cappella passes a configurable API token to HippoClient. Multi-user auth and RBAC is Hippo's responsibility.
- **No execution of external code.** Cappella does not execute CWL, shell scripts, or arbitrary code. Canon handles all execution.
- **Audit trail is append-only.** `HarmonizationConflict` and `AdapterRun` log entries are write-once. No Cappella operation can retroactively modify provenance.

---

## 6.7 Deployment

Cappella is distributed as a Python package on PyPI (`cappella`). It runs as:

- **CLI tool** — `cappella resolve`, `cappella ingest`, `cappella status`
- **REST service** — `cappella serve` (starts a FastAPI application)
- **Python library** — `from cappella import CappellaClient` (for Composer)

**Dependencies:**
- `hippo` (HippoClient)
- `canon` (CanonClient, optional — can be disabled if Canon is not deployed)
- `httpx` (external adapter HTTP calls)
- `pydantic` (config validation)
- `typer` (CLI)
- `fastapi` + `uvicorn` (optional, for REST service mode)

**No mandatory external services beyond Hippo.** Canon and external adapters are all optional — Cappella runs in "metadata-only" mode without them.

---

## 6.8 Configuration

Full `cappella.yaml` reference:

```yaml
# Cappella configuration

mosaic:
  url: "http://localhost:8000"
  token: "${MOSAIC_API_TOKEN}"

canon:
  enabled: true
  url: "http://localhost:8001"      # HTTP mode
  # OR:
  # mode: in_process               # Import canon directly (v0.1 default)

server:
  host: "0.0.0.0"
  port: 8002
  workers: 1

resolution:
  max_concurrent_canon_calls: 5    # Parallel Canon resolve() calls per run
  sync_threshold: 10               # Runs <= this are synchronous; > are async
  canon_timeout_seconds: 300       # Per-sample Canon timeout

adapters:
  # See sec3_adapters.md for full adapter config reference

triggers:
  # See sec2_architecture.md for trigger config reference

logging:
  level: INFO
  format: json                     # "json" or "text"
  output: stdout                   # "stdout" or file path
```
