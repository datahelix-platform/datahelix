# Section 4: Audit & Observability

**Status:** Draft v0.1  
**Last updated:** 2026-03-25

---

## 4.1 Audit Philosophy

Cappella's audit model is: **every write to Hippo carries provenance, and every Cappella operation that changes state produces a structured log entry.** The audit trail is not a separate system — it is the Hippo provenance event model, extended with Cappella-specific context.

In v0.1, operational audit (sync run results, resolution run results, reconciliation findings) is written to structured JSON logs. In v0.2, these become Hippo entities for queryability through the standard HippoClient API.

---

## 4.2 Provenance Context

Every entity write made by Cappella carries a structured `context` in the Hippo provenance event:

```json
{
  "cappella_version": "0.1.0",
  "source_system": "starlims",
  "adapter": "starlims",
  "adapter_version": "1.0.0",
  "run_id": "uuid-run-123",
  "trigger": "nightly_starlims_sync",
  "fetched_at": "2026-03-25T02:00:01Z",
  "trust_level": 80
}
```

For collection resolution runs, artifact writes by Canon carry Canon's own provenance context. Cappella does not add additional context to Canon's writes — Canon is responsible for its own provenance.

---

## 4.3 Structured Log Events

Cappella emits structured JSON log events to stdout (or a configured log sink) for all significant operations. These are machine-parseable and can be ingested by log aggregation tools (Datadog, CloudWatch, ELK).

### Event Types

| Event | When emitted |
|-------|-------------|
| `adapter_run_started` | Sync run begins |
| `adapter_run_completed` | Sync run ends (success, partial, failure) |
| `record_transform_failed` | A record could not be transformed |
| `record_upsert_conflict` | Conflict detected during upsert |
| `resolution_run_started` | Collection resolution begins |
| `resolution_run_completed` | Collection resolution ends |
| `canon_resolve_failed` | Canon returned an error for a sample |
| `reconciliation_started` | Reconciliation run begins |
| `reconciliation_finding` | A discrepancy was detected |
| `trigger_fired` | A trigger executed |
| `trigger_failed` | A trigger encountered an error |

### Example: adapter_run_completed

```json
{
  "event": "adapter_run_completed",
  "timestamp": "2026-03-25T02:00:47Z",
  "run_id": "uuid-run-123",
  "adapter": "starlims",
  "trigger": "nightly_starlims_sync",
  "mode": "incremental",
  "since": "2026-03-24T02:00:00Z",
  "fetched": 150,
  "transformed": 149,
  "upserted": 23,
  "skipped_identical": 126,
  "failed_transform": 1,
  "conflicts_detected": 2,
  "duration_seconds": 46.2,
  "status": "partial_success"
}
```

### Example: reconciliation_finding

```json
{
  "event": "reconciliation_finding",
  "timestamp": "2026-03-25T03:00:12Z",
  "finding_id": "uuid-finding-456",
  "check": "field_conflict",
  "entity_type": "Donor",
  "entity_id": "uuid-donor-789",
  "field": "diagnosis",
  "source_a": {"system": "starlims", "value": "CTE", "updated_at": "2026-03-24T..."},
  "source_b": {"system": "redcap", "value": "Probable CTE", "updated_at": "2026-03-25T..."},
  "severity": "warning",
  "suggested_action": "manual_review"
}
```

---

## 4.4 HarmonizationConflict Events

When `validate()` returns errors or a field conflict is detected during upsert, Cappella records a `HarmonizationConflict` provenance event on the affected Hippo entity. This is queryable via the standard Hippo provenance API.

```json
{
  "event_type": "HarmonizationConflict",
  "entity_id": "uuid-donor-789",
  "conflict_type": "field_conflict",
  "field": "diagnosis",
  "existing_value": "CTE",
  "incoming_value": "Probable CTE",
  "incoming_source": "redcap",
  "resolution": "existing_wins",
  "resolution_reason": "starlims (trust=80) > redcap (trust=60)",
  "cappella_run_id": "uuid-run-123"
}
```

This creates a permanent, queryable audit trail of every conflict and how it was resolved.

---

## 4.5 ReconciliationFinding Entity (v0.2)

**Opinion (mark for review):** In v0.1, reconciliation findings are structured log events. In v0.2, they become `ReconciliationFinding` Hippo entities, queryable via HippoClient and surfaced in Aperture as a "data quality" view. The log structure in §4.3 is designed to map directly to the future entity schema — migration from logs to entities is straightforward.

---

## 4.6 Health Endpoint

`GET /status` returns Cappella's operational health:

```json
{
  "cappella_version": "0.1.0",
  "mosaic": {"status": "ok", "version": "0.3.1", "url": "http://localhost:8000"},
  "canon": {"status": "ok", "version": "0.2.0", "url": "http://localhost:8001"},
  "adapters": {
    "starlims": {"status": "ok", "last_sync": "2026-03-25T02:00:47Z"},
    "halo": {"status": "stub", "last_sync": null},
    "manual": {"status": "ok", "last_sync": null}
  },
  "triggers": {
    "nightly_starlims_sync": {"status": "scheduled", "next_run": "2026-03-26T02:00:00Z"}
  }
}
```
