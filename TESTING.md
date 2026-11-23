# TESTING.md — DataHelix Platform Test Strategy

## Overview

The DataHelix platform uses a three-tier testing model. Each tier has a distinct purpose and failure protocol.

```
┌──────────────────────────────────────────────────────────────────┐
│  Tier 3: Platform Tests   tests/platform/                        │
│  "Do components work correctly together?"                        │
│  Real Mosaic + Canon in-process, mocked CWL executor             │
│  Run after tiers 1 & 2 both pass                                 │
├──────────────────────────────────────────────────────────────────┤
│  Tier 2: Contract Tests   tests/contracts/                       │
│  "Does each component fulfill its published behavioral spec?"    │
│  Component tested in isolation against explicit behavior claims  │
│  Run after tier 1 passes                                         │
├──────────────────────────────────────────────────────────────────┤
│  Tier 1: Unit Tests       mosaic/tests/  canon/tests/             │
│  "Does this component work correctly in isolation?"              │
│  Mocked dependencies, fast, run on every commit                  │
└──────────────────────────────────────────────────────────────────┘
```

> **Independently-versioned components (aperture, mosaic).** The three tiers above
> assume components installed in-process from the same tree. Components that ship
> as their own repos with independent semver releases are additionally certified
> **per exact version pair** through the **certified-frontier ledger** (platform
> [ADR-0001](platform/design/decisions/ADR-0001-certified-frontier-composition.md);
> tooling in [`certification/`](certification/)). That adds a producer-run
> **contract check** (a consumer's contract file booted in the producer's CI) and
> a DataHelix **composition certification** (one exact pair boots + passes the
> golden path, appended to an append-only ledger; deployment is gated on it).
> Run the ledger tooling tests with `make ledger-test`.

## Tier 1 — Unit Tests

**Location:** `mosaic/tests/`, `canon/tests/`

**What they cover:** Internal logic, edge cases, error paths. Dependencies are mocked.

**Run:**
```bash
cd mosaic && uv run pytest tests/ -v
cd canon && uv run pytest tests/ -v
```

**When they fail:** Fix the component directly. Do not look at tier 2/3.

---

## Tier 2 — Contract Tests

**Location:** `tests/contracts/`

**What they cover:** Explicit behavioral specifications for each component's *public interface*, written from the perspective of its consumers. This is the formal answer to "what does Canon need Mosaic to do?"

Contract tests differ from unit tests in that they:
- Are written from the *consumer's perspective*, not the provider's
- Assert behavioral guarantees that must not change without a version bump
- Catch API drift early — before a full platform run is needed

Each contract file is named `test_<consumer>_expects_<provider>.py` and contains only assertions about the provider's public interface.

**Current contracts:**
- `test_canon_expects_mosaic.py` — behaviors Canon depends on from MosaicClient
- `test_cappella_expects_mosaic.py` — behaviors Cappella depends on from MosaicClient (upsert, query_updated_since, provenance shape)
- `test_cappella_expects_canon.py` — behaviors Cappella depends on from Canon's `resolve()` API
- `test_entity_loader_contract.py` — Mosaic's EntityLoader/IngestPipeline surface (CSV loader, dry-run)
- `test_storage_adapter_contract.py` — Canon's StorageAdapter ABC behavioral contract (canon v0.2)

**Run:**
```bash
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/contracts/ -v
```

**CI (restored 2026-07-07, epic P1.7):** the contract tier runs on every PR as two
parallel seam slices — `contracts-mosaic-seam` (canon↔mosaic, cappella↔mosaic,
entity-loader) and `contracts-canon-seam` (storage-adapter, cappella↔canon) — in
`.github/workflows/tests.yml`. The platform tier runs nightly and via
workflow_dispatch, not per-PR (yet).

**When they fail:**
1. If the failure is in `test_<consumer>_expects_<provider>`: the *provider* changed its behavior in a breaking way. Add a unit test to the provider pinning the correct behavior, then fix it.
2. If the failure is in `test_<provider>_self_contract`: the provider violated one of its own invariants. Same protocol.
3. Update the contract spec if the change was intentional (semver bump).

### Writing New Contracts

When you add a new cross-component dependency, add a contract immediately:

```python
# tests/contracts/test_canon_expects_mosaic.py
class TestMosaicQueryContract:
    """Canon depends on MosaicClient.query() behaving exactly like this."""

    def test_query_returns_paginated_result_with_items(self, hippo_client):
        """Canon iterates result.items — must be a PaginatedResult."""
        ...
```

A failing contract test is a **breaking change signal**. Treat it like a failed type check.

---

## Tier 3 — Platform Tests

**Location:** `tests/platform/`

**What they cover:** End-to-end scenarios using real in-process components. Canon talks to a real MosaicClient via `MosaicClientShim` (no HTTP server). CWL execution is mocked.

**Run:**
```bash
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/platform/ -v
```

**Test files:**
- `test_canon_platform.py` — Canon-only: rules DSL, entity ref parsing, planner decisions, sidecar, ingestion
- `test_mosaic_canon.py` — Cross-cutting: Canon resolving against real Mosaic, full bioinformatics chain, idempotency
- `test_round_trip.py` — Full round-trip: external source → Mosaic → Canon → Mosaic (sec5 §5.2–§5.5)
- `test_cross_component.py` — Cross-component: CSV ingest via Cappella → Mosaic → Canon resolution, entity relationships, provenance chain
- `test_webhook_integration.py` — Webhook triggers: HMAC-SHA256 verification, payload mapping → Mosaic entity creation, deduplication
- `test_cli_integration.py` — CLI integration: `datahelix list`, `datahelix get`, `datahelix search`, `datahelix history` against pipeline-created entities

**When they fail:**
1. Identify which component's behavior changed
2. Check if its unit tests still pass — if not, fix unit tests first
3. Check if the relevant contract test fails — if so, follow the contract failure protocol
4. If unit + contract pass but platform fails, it's an integration issue — add a targeted platform test for the specific interaction, then fix

> **Policy: Contract/platform failures MUST be addressed via TDD.** See [TDD Policy](#tdd-policy) below.

**Markers:**
- `@pytest.mark.platform` — all platform tests
- `@pytest.mark.xfail` — known API gaps, with documented reason and revisit note

---

## Full Test Run

```bash
make test
```

This runs all three tiers in order, failing fast at each stage.

---

## Contract Specification: Component Interfaces

### MosaicClient — Canon's View

These are the behaviors Canon depends on. Any change to these is a breaking change for Canon.

| Method | Behavioral guarantee |
|--------|---------------------|
| `query(entity_type)` | Returns a `PaginatedResult` with `.items` (list of dicts). Each item has `id`, `entity_type`, `data` keys. |
| `query(entity_type, limit=N)` | Returns at most N items. |
| `create(entity_type, data)` | Returns a dict with `id` (str UUID), `entity_type`, `data`, `version` (int, starts at 1), `created_at`, `updated_at`. |
| `create()` with missing required field | Raises `ValidationFailure`. |
| `get(entity_type, id)` | Returns same shape as `create()`. Raises `EntityNotFoundError` if not found **or if entity is deleted/superseded** (unless `include_unavailable=True`). |
| `get(entity_type, id, include_unavailable=True)` | Returns entity regardless of deleted/superseded status. Use for audit/provenance queries only. |
| `update(entity_type, id, data)` | Updates entity, returns new version. Raises `EntityNotFoundError` if id does not exist. |
| `supersede_entity(old_id, new_id)` | Marks old entity as superseded. Old entity excluded from `query()` and raises on `get()` by default. |
| `delete(entity_type, id)` | Returns `True`. Entity excluded from `query()` results and raises on `get()` by default. |

**Gaps being addressed via TDD (currently xfail):**
- `get()` availability filtering — in progress, see `mosaic/tests/core/test_client_availability.py`
- `update()` existence check — in progress, same file

### MosaicQueryClient — Canon's HTTP shim

Canon's `MosaicQueryClient` wraps the HTTP API. The `MosaicClientShim` in `tests/platform/conftest.py` is the in-process equivalent. When the HTTP API changes, update both.

---

### CanonClient — Cappella's View

These are the behaviors Cappella depends on from Canon's `resolve()` API. Any change to these is a breaking change for Cappella.

**Success response shape:**

| Field | Type | Guarantee |
|-------|------|-----------|
| `uri` | `str` | Non-empty. Mosaic entity URI in the form `dhlx://<EntityType>/<uuid>` |
| `decision` | `Literal["REUSE", "BUILD"]` | Always present. `REUSE` means an existing entity was found; `BUILD` means Canon executed a workflow and created a new entity. |
| `entity_id` | `str` | UUID of the resolved entity in Mosaic. Must be retrievable via `MosaicClient.get()` immediately after `resolve()` returns. |
| `entity_type` | `str` | Matches the requested `entity_type` argument. |
| `rule` | `str | None` | `None` on REUSE. Name of the rule that produced the result on BUILD. |

**Partial failure format:**

Cappella calls `resolve()` per-sample and must handle all failure modes. Canon raises typed exceptions — never returns a partial dict.

| Exception | When raised | Cappella behavior |
|---|---|---|
| `CanonResolutionError` | No rule found, or ref expression matched zero or multiple entities | Mark sample as `unresolved` with reason `NO_RULE` or `RESOLUTION_ERROR`; continue run |
| `CanonExecutorError` | CWL execution failed, or in-progress run detected | Mark sample as `unresolved` with reason `EXECUTOR_ERROR`; continue run |
| `CanonRuleValidationError` | Raised at Canon startup — rule file is malformed | Propagate as Cappella startup error; resolution run never starts |

Cappella never catches `Exception` broadly. Only the three documented typed exceptions above are handled as non-aborting per-sample failures.

**URI structure guarantee:**

Canon-produced URIs follow the pattern `dhlx://<EntityType>/<uuid>`. Cappella extracts the UUID component for Mosaic queries. The UUID is always a valid UUID4 string.

```python
# Cappella's expected URI parsing
import re
CANON_URI_RE = re.compile(r"^dhlx://(\w+)/([0-9a-f-]{36})$")

def parse_canon_uri(uri: str) -> tuple[str, str]:
    """Returns (entity_type, uuid). Raises ValueError if uri does not match."""
    m = CANON_URI_RE.match(uri)
    if not m:
        raise ValueError(f"Unexpected Canon URI format: {uri!r}")
    return m.group(1), m.group(2)
```

Any change to the URI format (e.g. from `dhlx://` to a different scheme) is a **breaking change** for Cappella.

**Idempotency guarantee:**

Calling `resolve()` twice with the same `entity_type` and parameters must return the same `uri` both times (on the second call, `decision == "REUSE"`). Cappella depends on this for safe re-runs and progress checkpointing.

---

## TDD Policy

**When a contract or platform test fails (or is marked `xfail`), the fix MUST follow this TDD sequence:**

```
1. RED   — Write unit tests in the affected component (mosaic/tests/ or canon/tests/)
            that assert the desired behavior. Run make test — new tests fail,
            everything else passes.

2. GREEN — Implement the minimum code change to make the unit tests pass.
            Run make test — all unit tests pass.

3. REFACTOR — Remove xfail markers from the contract/platform tests that
               triggered this cycle. Run make test — those tests now pass as
               hard assertions. 0 failures, 0 unexpected xfails.
```

**Why this matters:**
- Contract/platform tests describe *what* we want but at too high a level to drive implementation safely
- Writing unit tests first forces the API design (method signatures, error types, flag names) to be explicit before touching production code
- The red→green signal is unambiguous — you know exactly when the implementation is correct
- You end up with regression coverage at the right layer (component unit tests), not just at the integration level

**When NOT to use TDD:**
- Trivial one-liner fixes where the behavior is already pinned by existing unit tests
- Documentation or comment updates
- Test-only changes (adding more test cases to an existing passing test)

**The test to add lives in the component whose code changes.** If Mosaic's `client.py` changes, add tests to `mosaic/tests/`. If Canon's `planner.py` changes, add tests to `canon/tests/`. Contract and platform tests are the early warning system; unit tests are where the fix is pinned.

---

## Failure Protocol Summary

```
Platform test fails
    │
    ├─► Is the failing assertion about a single component's behavior?
    │       └─► YES → go to that component's unit tests
    │                   ├─► Unit test also fails → fix component, add unit test
    │                   └─► Unit test passes → add a contract test, then fix
    │
    └─► Is it a cross-component interaction issue?
            └─► YES → add a targeted platform test, fix the integration
```

When a platform test reveals a behavioral gap (something that *should* work but doesn't):
1. Mark it `@pytest.mark.xfail(reason="...", strict=False)` with a clear reason
2. File it as a backlog item in the relevant component's plan
3. Remove the `xfail` when the feature is implemented

---

## Running Individual Tiers

```bash
# Tier 1 only
cd mosaic && uv run pytest tests/ -v
cd canon && uv run pytest tests/ -v

# Tier 2 only
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/contracts/ -v

# Tier 3 only
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/platform/ -v

# All tiers
make test

# Just the cross-cutting platform tests
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/platform/test_mosaic_canon.py -v

# Only xfail tests (to check if gaps have been closed)
PYTHONPATH=mosaic/src:canon/src:cappella/src:aperture/src uv run pytest tests/platform/ -v -m "xfail"
```
