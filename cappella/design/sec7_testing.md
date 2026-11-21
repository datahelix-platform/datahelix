# Section 7: Trigger Engine Test Strategy

**Status:** Draft v0.1 (Epic 1.3 — Phase 1 deliverable)
**Last updated:** 2026-03-31
**Depends on:** sec2_architecture.md (§2.5 Trigger Engine), sec3_adapters.md, sec6_nfr.md
**Feeds into:** `tests/cappella/` test suite, `platform/design/sec5_integration_test_strategy.md`

---

## 7.1 Scope

This section defines the test strategy for Cappella's trigger engine. It covers the three trigger source types targeted for v0.1 and v0.2:

| Trigger source | Version | Status |
|---------------|---------|--------|
| `schedule` | v0.1 | Implemented |
| `manual` | v0.1 | Implemented |
| `internal_event` | v0.1 | Implemented |
| `webhook` | v0.2 | Deferred — spec complete here |
| `mosaic_poll` | v0.2 | Deferred — spec complete here |

For each trigger source, this section defines:
- The behavior matrix (inputs → expected outcomes)
- Test scenarios against real external source patterns (STARLIMS, HALO)
- Edge cases requiring explicit test coverage
- Test infrastructure requirements

---

## 7.2 Test Infrastructure

### 7.2.1 Fake External Source

All trigger engine tests use a fake external source (`cappella.testing.FakeExternalSource`) that:
- Provides deterministic record sets (configurable at test setup)
- Supports incremental pulls (tracks a `since` cursor in memory)
- Records all fetch calls for assertion
- Can be configured to fail (raises `AdapterFetchError`) on demand

```python
from cappella.testing import FakeExternalSource, FakeHippoClient

fake_source = FakeExternalSource(
    records=[
        {"id": "S001", "patient_id": "P001", "tissue": "DLPFC", "diagnosis": "CTE"},
        {"id": "S002", "patient_id": "P002", "tissue": "DLPFC", "diagnosis": "CTE"},
    ],
    entity_type="Sample",
    external_id_field="id",
)
```

### 7.2.2 Fake Hippo Client

`cappella.testing.FakeHippoClient` provides an in-memory Hippo store:
- Supports `create`, `update`, `find_by_external_id` operations
- Records all writes for assertion (`assert_entity_created`, `assert_entity_updated`)
- Supports conflict simulation (configurable field disagreements between sources)

### 7.2.3 Test Isolation

Each trigger engine test:
- Creates a fresh `FakeCappellaApp` with an isolated `FakeHippoClient`
- Does not touch any real external system
- Runs synchronously (async resolution is tested separately in `tests/cappella/test_resolution.py`)

---

## 7.3 `schedule` Trigger Behavior Matrix

Schedule triggers fire at a cron-defined interval. The following scenarios must be tested:

### 7.3.1 Core Execution Scenarios

| Test ID | Trigger config | Action | Expected outcome |
|---------|---------------|--------|-----------------|
| `SCH-01` | `schedule: "0 2 * * *"`, `action: ingest`, `incremental: true` | Fires at scheduled time | Adapter `fetch(since=last_run_at)` called; only changed records processed |
| `SCH-02` | `schedule: "0 2 * * *"`, `action: ingest`, `incremental: false` | Fires at scheduled time | Adapter `fetch(since=None)` called; full sync |
| `SCH-03` | Schedule trigger with `on_success: emit: starlims_sync_complete` | Ingest succeeds | `starlims_sync_complete` internal event emitted after ingest completes |
| `SCH-04` | Schedule trigger with `on_success: emit` | Ingest partially fails (2/10 records fail transform) | Event still emitted; failed records logged; partial success is not failure |
| `SCH-05` | Schedule trigger with `on_failure: emit: starlims_sync_failed` | Adapter raises `AdapterFetchError` | `starlims_sync_failed` event emitted; no `on_success` event |
| `SCH-06` | Two schedule triggers both fire at same interval | Both actions independent | Both execute; no ordering guarantee assumed |

### 7.3.2 STARLIMS Scenario (schedule)

STARLIMS is a production LIMS system that exports sample and donor records nightly. The expected integration pattern:

```yaml
triggers:
  - name: nightly_starlims_donor_sync
    type: schedule
    schedule: "0 1 * * *"
    action:
      type: ingest
      adapter: starlims_donors
      incremental: true
    on_success:
      emit: starlims_donors_synced

  - name: nightly_starlims_sample_sync
    type: schedule
    schedule: "0 2 * * *"
    action:
      type: ingest
      adapter: starlims_samples
      incremental: true
    on_success:
      emit: starlims_samples_synced
```

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `SCH-STAR-01` | 50 new samples from STARLIMS nightly sync | All 50 samples created in Hippo with `source: starlims` provenance |
| `SCH-STAR-02` | 3 samples updated in STARLIMS (field values changed) | Hippo entities updated; `HarmonizationConflict` events written if fields conflict with REDCap data |
| `SCH-STAR-03` | STARLIMS returns 0 new records (no changes since last sync) | No Hippo writes; `SyncRun` log entry records 0 created, 0 updated |
| `SCH-STAR-04` | STARLIMS API returns 503 | Adapter raises `AdapterFetchError`; trigger run logged as failed; no partial writes |

### 7.3.3 Incremental Sync Cursor

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `SCH-INC-01` | First-ever run (`since=None`) | Full sync; `last_run_at` persisted after completion |
| `SCH-INC-02` | Second run, some records modified after `last_run_at` | Only modified records fetched; cursor advances to new `run_at` |
| `SCH-INC-03` | Second run, adapter does not support incremental (`supports_incremental: false`) | Full sync performed even when `incremental: true` in config; warning logged |

---

## 7.4 `manual` and `internal_event` Trigger Behavior Matrix

### 7.4.1 Manual Trigger

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `MAN-01` | `POST /triggers/{name}/run` for an ingest trigger | Trigger fires immediately; returns `run_id` |
| `MAN-02` | `POST /triggers/{name}/run` for a non-existent trigger name | `404 Not Found` |
| `MAN-03` | Manual trigger for a resolve action | Collection resolution job submitted; `run_id` returned |
| `MAN-04` | `cappella trigger run nightly_starlims_sync` (CLI) | Same as MAN-01; CLI blocks with progress indicator |

### 7.4.2 `internal_event` Trigger Chaining

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `EVT-01` | A emits `sync_complete`; B subscribes to `sync_complete` | B fires after A's `on_success`; B receives no payload (actions query Hippo fresh) |
| `EVT-02` | A emits event; B subscribes; B action fails | B failure does not retroactively fail A; both runs logged independently |
| `EVT-03` | A emits event; B and C both subscribe | Both B and C fire; execution order is not guaranteed |
| `EVT-04` | Cycle: A emits `foo`; B subscribes to `foo` and emits `bar`; A subscribes to `bar` | `CanonConfigError: trigger chain cycle detected [A → B → A]` at config validation time, not at runtime |
| `EVT-05` | Event emitted with no subscribers | Event is silently ignored; logged at DEBUG level |

---

## 7.5 `webhook` Trigger Behavior Matrix (v0.2)

Webhook triggers receive HTTP POST requests from external systems and fire a Cappella action in response. They require endpoint registration, signature verification, and retry-safe idempotency.

### 7.5.1 Configuration

```yaml
triggers:
  - name: halo_sample_created
    type: webhook
    path: /webhooks/halo/sample_created    # Cappella registers this route
    secret_env: HALO_WEBHOOK_SECRET        # HMAC-SHA256 verification key
    when: "event.type == 'sample.created'" # CEL condition on payload
    action:
      type: ingest
      adapter: halo_samples
      incremental: false
    idempotency_window_seconds: 300        # Dedup window for retry storms
```

### 7.5.2 Core Webhook Scenarios

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `WH-01` | Valid POST to webhook endpoint, valid HMAC signature | Trigger fires; action executes; `200 OK` returned |
| `WH-02` | Valid POST, invalid HMAC signature | `403 Forbidden`; action does NOT fire; security event logged |
| `WH-03` | Valid POST, missing `X-Signature` header | `403 Forbidden`; action does NOT fire |
| `WH-04` | Valid POST, CEL `when` condition evaluates to false | `200 OK` (acknowledged) but action NOT executed; logged as `skipped` |
| `WH-05` | Duplicate POST within `idempotency_window_seconds` (same payload digest) | `200 OK` (acknowledged); action NOT re-executed; dedup logged |
| `WH-06` | Duplicate POST after idempotency window expires | Action executes normally (window has passed) |
| `WH-07` | External system retries (3x) because Cappella returned `500` | On retry success, action fires once; prior partial execution (if any) is safe via upsert idempotency |

### 7.5.3 HALO Scenario (webhook)

HALO is a pathology imaging platform that emits webhook events when new cases are added. The integration pattern for image metadata ingestion:

```yaml
triggers:
  - name: halo_case_ready
    type: webhook
    path: /webhooks/halo/case_ready
    secret_env: HALO_WEBHOOK_SECRET
    when: "event.status == 'analysis_complete'"
    action:
      type: ingest
      adapter: halo_cases
```

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `WH-HALO-01` | HALO emits `case_ready` with `status: analysis_complete` | HALO adapter fetches case record; entity created in Hippo |
| `WH-HALO-02` | HALO emits `case_ready` with `status: in_progress` (not analysis_complete) | Webhook acknowledged; ingest NOT triggered (CEL condition false) |
| `WH-HALO-03` | HALO emits event for case that already exists in Hippo | Upsert: entity updated if fields changed; skipped if identical |
| `WH-HALO-04` | HALO emits same event twice within 60s (retry) | Second event deduplicated; only one ingest run |
| `WH-HALO-05` | HALO webhook payload is malformed JSON | `400 Bad Request`; no action; error logged with payload excerpt |

### 7.5.4 Signature Verification

Cappella verifies `X-Signature: sha256=<hmac>` on all incoming webhook requests.

```python
import hmac, hashlib

def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

The secret is loaded from the environment variable named in `secret_env`. If the env var is unset at startup, Cappella raises `CappellaConfigError` — a webhook trigger with no secret is rejected at config validation time.

---

## 7.6 `mosaic_poll` Trigger Behavior Matrix (v0.2)

`mosaic_poll` triggers fire when Hippo entities matching a query change. Cappella polls Hippo periodically using the `updated_at` index.

### 7.6.1 Configuration

```yaml
triggers:
  - name: on_new_sample
    type: mosaic_poll
    poll:
      entity_type: Sample
      filter: "status == 'received'"     # CEL filter on entity fields
      interval_seconds: 120              # Poll every 2 minutes
      lookback_seconds: 300              # On first run, look back 5 minutes
    action:
      type: resolve
      entity_type: AlignmentFile
      criteria:
        sample.id: "{entity.id}"         # Bind from the matched entity
      parameters:
        genome: GRCh38
```

### 7.6.2 Core `mosaic_poll` Scenarios

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `HP-01` | Poll interval fires; new `Sample` entity matching filter exists since last poll | Action fires once per new entity; `entity.id` bound from matched entity |
| `HP-02` | Poll fires; no new entities since last poll | No action fired; poll cursor advances |
| `HP-03` | Poll fires; 5 new entities since last poll | Action fires 5 times (once per entity); all are independent action invocations |
| `HP-04` | Poll fires; new entity created, then updated within same poll window | Only one action per entity ID; deduplication by entity ID within poll batch |
| `HP-05` | First ever poll run (no cursor stored) | Uses `lookback_seconds` to set initial cursor; catches recently created entities |
| `HP-06` | Hippo query times out during poll | Poll cycle aborted; cursor NOT advanced (retry on next interval); error logged |
| `HP-07` | Action triggered by poll fails (e.g., Canon unreachable) | Poll cursor advances regardless; failed action logged; entity is NOT re-triggered on next poll (to avoid retry storms) |

### 7.6.3 Polling Against STARLIMS Ingestion (mosaic_poll)

The canonical `mosaic_poll` use case is triggering alignment resolution when new samples arrive from STARLIMS.

```yaml
triggers:
  - name: trigger_alignment_on_new_sample
    type: mosaic_poll
    poll:
      entity_type: Sample
      filter: "tissue == 'DLPFC' && status == 'received'"
      interval_seconds: 300
    action:
      type: resolve
      entity_type: AlignmentFile
      criteria:
        sample.id: "{entity.id}"
      parameters:
        genome: GRCh38
    on_success:
      emit: alignment_queued
```

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `HP-STAR-01` | Nightly STARLIMS sync creates 10 new `DLPFC` samples | Poll fires next interval; 10 alignment resolution jobs queued; `alignment_queued` event emitted 10 times |
| `HP-STAR-02` | Sample exists but tissue = `cerebellum` (filter mismatch) | Poll does not match entity; no action |
| `HP-STAR-03` | `AlignmentFile` already exists for sample (Canon REUSE) | Canon returns existing URI; no new execution; Cappella logs REUSE |
| `HP-STAR-04` | Sample status updated from `received` to `qc_failed` after already being processed | Updated entity does not re-match filter (status changed); no duplicate action |

### 7.6.4 Change Detection Implementation Notes

Cappella's `mosaic_poll` uses Hippo's `GET /entities/{type}?updated_after={cursor}&limit=N` query (Phase 1 REST gap — cursor pagination). The poll cursor is stored as a `CappellaPollCursor` Hippo entity (keyed by trigger name). This means:

- Cursor state survives Cappella restarts (it's in Hippo, not in-process memory)
- Multiple Cappella instances polling the same trigger must coordinate — advisory lock on cursor entity update (v0.2 design detail)
- If cursor entity is missing on startup, Cappella falls back to `lookback_seconds` as initial window

---

## 7.7 Cross-Trigger Interaction Tests

These tests validate behavior when multiple trigger types interact.

| Test ID | Scenario | Expected outcome |
|---------|----------|-----------------|
| `XTR-01` | `schedule` trigger fires; emits event; `internal_event` trigger chains into `mosaic_poll` subscription | Chain resolves correctly; no event lost between trigger types |
| `XTR-02` | `webhook` fires; `internal_event` subscriber starts ingest; `mosaic_poll` fires before ingest completes | Both run independently; no interference; both logged with distinct `run_id` |
| `XTR-03` | Two `mosaic_poll` triggers watching same entity type with different filters | Both fire independently when their respective filters match; no cross-trigger dedup |
| `XTR-04` | `schedule` ingest and `webhook` ingest both write to same entity within same second | Conflict resolution (`trust_level` or last-write-wins) applies; `HarmonizationConflict` event written |

---

## 7.8 Trigger Failure Handling

### Failure Modes and Expected Behavior

| Failure mode | Expected Cappella behavior |
|-------------|--------------------------|
| Adapter `fetch()` raises `AdapterFetchError` | Trigger run marked `failed`; `on_failure` event emitted if configured; retry on next scheduled interval |
| Adapter `transform()` raises `AdapterTransformError` for one record | Remaining records proceed; failed record counted in error log; trigger run marked `partial_success` |
| Canon unreachable during resolve action | All samples marked `canon_timeout` in unresolved list; trigger run marked `partial_success` |
| Hippo unreachable during upsert | Trigger run fails immediately (Hippo is required); logged; retry on next interval |
| Trigger action takes longer than `resolution.canon_timeout_seconds` | Per-sample Canon call times out; sample added to `unresolved` with `reason: canon_timeout` |

### Trigger Run Log Schema

Every trigger execution produces a structured JSON log entry:

```json
{
  "run_id": "uuid-run-456",
  "trigger_name": "nightly_starlims_sync",
  "trigger_type": "schedule",
  "started_at": "2026-04-01T02:00:00Z",
  "finished_at": "2026-04-01T02:01:34Z",
  "status": "success",                      // success | partial_success | failed
  "adapter": "starlims_samples",
  "records_fetched": 312,
  "records_created": 8,
  "records_updated": 3,
  "records_skipped": 301,
  "records_failed": 0,
  "errors": []
}
```

---

## 7.9 Test Coverage Targets

| Trigger type | Unit tests | Integration tests | Real-source simulation |
|-------------|-----------|------------------|----------------------|
| `schedule` | SCH-01–06 | SCH-STAR-01–04, SCH-INC-01–03 | FakeExternalSource (STARLIMS pattern) |
| `manual` | MAN-01–04 | — | — |
| `internal_event` | EVT-01–05 | XTR-01–02 | — |
| `webhook` | WH-01–07 | WH-HALO-01–05 | FakeExternalSource (HALO pattern) |
| `mosaic_poll` | HP-01–07 | HP-STAR-01–04, XTR-03–04 | FakeHippoClient (STARLIMS post-ingest) |

Test files:
- `cappella/tests/test_trigger_schedule.py` — SCH-* scenarios
- `cappella/tests/test_trigger_manual.py` — MAN-* scenarios
- `cappella/tests/test_trigger_internal_event.py` — EVT-* scenarios
- `cappella/tests/test_trigger_webhook.py` — WH-* scenarios (v0.2)
- `cappella/tests/test_trigger_mosaic_poll.py` — HP-* scenarios (v0.2)
- `cappella/tests/test_trigger_cross.py` — XTR-* scenarios
