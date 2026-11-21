# Workflows and Triggers

Cappella automates ingest and resolution operations through a lightweight trigger system. Triggers fire actions — either on a schedule, on-demand, or in response to events emitted by other actions.

## Trigger Types

| Type | Fires when | Added |
|------|-----------|-------|
| `schedule` | Cron expression matches | v0.1 |
| `manual` | CLI or API call | v0.1 |
| `internal_event` | Named event emitted by another trigger's `on_success` | v0.1 |
| `webhook` | External system sends an HTTP POST to the configured path | v0.2 |
| `mosaic_poll` | Hippo entities matching a filter are created or updated | v0.2 |

### Schedule Triggers

Run on a cron schedule:

```yaml
triggers:
  - name: nightly_donor_sync
    type: schedule
    schedule: "0 2 * * *"    # 2 AM every night
    action:
      type: ingest
      adapter: starlims_donors
    on_success: donors_synced
```

### Manual Triggers

Fire on demand via the CLI or API:

```bash
cappella trigger run nightly_donor_sync --config cappella.yaml
```

```bash
curl -X POST http://localhost:8000/triggers/nightly_donor_sync/run
```

### Internal Event Triggers

React to events emitted by other triggers. Use `on_success` on one trigger to chain into another:

```yaml
triggers:
  - name: nightly_donor_sync
    type: schedule
    schedule: "0 2 * * *"
    action:
      type: ingest
      adapter: starlims_donors
    on_success: donors_synced          # emits this event on success

  - name: resolve_after_sync
    type: internal_event
    event: donors_synced               # fires when donors_synced is emitted
    action:
      type: resolve
      entity_type: AlignmentFile
      parameters:
        genome: GRCh38
```

Cycles in trigger chains are detected at startup and rejected.

### Webhook Triggers

*Added in v0.2.* Receive HTTP callbacks from external systems. When an external service (such as HALO) completes an operation, it can POST to a Cappella webhook endpoint to trigger an ingest or resolution action.

```yaml
triggers:
  - name: halo_case_ready
    type: webhook
    path: /webhooks/halo/case_ready
    secret_env: HALO_WEBHOOK_SECRET     # HMAC-SHA256 key from env var
    when: "event.status == 'analysis_complete'"   # CEL condition on payload
    action:
      type: ingest
      adapter: halo_cases
    idempotency_window_seconds: 300     # Auto-deduplicate retries
```

**Signature verification:** The calling system must include an `X-Signature` header containing the HMAC-SHA256 digest of the request body, computed using the secret stored in the environment variable specified by `secret_env`. Cappella validates the signature and returns `403 Forbidden` if it is missing or invalid.

**CEL condition filtering:** The `when` field accepts a [CEL](https://github.com/google/cel-spec) expression that is evaluated against the parsed JSON payload. If the expression evaluates to `false`, Cappella returns `200 OK` but does not execute the action. This allows you to subscribe to a broad event stream and act only on relevant payloads.

**Idempotency and deduplication:** Cappella computes a SHA-256 digest of the request body and stores it for the duration of `idempotency_window_seconds`. If the same payload is received again within that window (e.g., due to a retry from the sender), Cappella returns `200 OK` with the original run ID and does not re-execute the action.

### Hippo Poll Triggers

*Added in v0.2.* Poll Hippo for new or updated entities matching a filter, and fire an action for each matched entity. This is useful for reactive workflows where you want to kick off processing whenever new data arrives in Hippo.

```yaml
triggers:
  - name: trigger_alignment_on_new_sample
    type: mosaic_poll
    poll:
      entity_type: Sample
      filter: "tissue == 'DLPFC' && status == 'received'"
      interval_seconds: 300
      lookback_seconds: 300
    action:
      type: resolve
      entity_type: AlignmentFile
      criteria:
        sample.id: "{entity.id}"
      parameters:
        genome: GRCh38
```

**Polling behavior:** On each tick (every `interval_seconds`), Cappella queries Hippo for entities of the specified `entity_type` whose `updated_at` timestamp falls within the `lookback_seconds` window and that match the `filter` expression. The query uses Hippo's `updated_at` index for efficient retrieval.

**Per-entity actions:** The action fires once per matched entity. Use `{entity.<field>}` bindings in `criteria` and `parameters` to inject values from the matched entity into the action. For example, `{entity.id}` resolves to the matched entity's ID, and `{entity.tissue}` resolves to the entity's `tissue` field value.

**Cursor persistence:** Cappella persists its poll cursor as a `CappellaPollCursor` entity in Hippo, keyed by trigger name. After a restart, polling resumes from the cursor position rather than re-processing old entities. The cursor advances to the latest `updated_at` timestamp seen in each poll cycle, regardless of whether the triggered action succeeds or fails. This means failed actions are not automatically retried by the poll trigger — use reconciliation or manual re-triggering for recovery.

## Action Types

| Action | What it does |
|--------|-------------|
| `ingest` | Run an adapter's fetch → transform → upsert pipeline |
| `resolve` | Run collection resolution for an entity type and criteria |

```yaml
# Ingest action
action:
  type: ingest
  adapter: my_csv_adapter     # must match an adapter name in cappella.yaml

# Resolve action
action:
  type: resolve
  entity_type: GeneCounts
  parameters:
    genome: GRCh38
    annotation: ensembl110
```

## Trigger Status

List all configured triggers and their last-run status:

```bash
cappella status --config cappella.yaml
```

```json
{
  "triggers": {
    "nightly_donor_sync": {
      "status": "scheduled",
      "last_run": "2026-03-26T02:00:47Z",
      "last_result": "success"
    },
    "halo_case_ready": {
      "status": "listening",
      "last_run": "2026-03-27T14:22:01Z",
      "last_result": "success"
    },
    "trigger_alignment_on_new_sample": {
      "status": "polling",
      "last_run": "2026-03-27T14:25:00Z",
      "last_result": "success",
      "cursor": "2026-03-27T14:20:00Z"
    }
  }
}
```

## A Note on Workflow Execution

Cappella does not run bioinformatics analyses or CWL workflows directly. That is [Canon](../../canon/README.md)'s responsibility. When a `resolve` action needs a file to be produced, Cappella calls `canon.resolve()` and Canon handles REUSE/FETCH/BUILD internally.

For aggregate analyses (merging count matrices, running DESeq2 across a cohort) — these are downstream concerns for Composer or custom scripts that consume Cappella's `HarmonizedCollection` output.
