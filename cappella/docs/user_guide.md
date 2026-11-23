# Cappella — User Guide

## Configuration Reference

All Cappella behavior is controlled by `cappella.yaml`. Environment variables can be injected using `${VAR_NAME}` syntax anywhere in the file.

### Full Configuration Example

```yaml
mosaic:
  url: "http://localhost:8001"
  token: "${MOSAIC_TOKEN}"

canon:
  enabled: true
  url: "http://localhost:8002"   # for HTTP mode
  mode: in_process               # "in_process" | "http"

server:
  host: "0.0.0.0"
  port: 8000
  workers: 1

resolution:
  max_concurrent_canon_calls: 5
  canon_timeout_seconds: 300.0

adapters:
  # See "Adapters" section below

triggers:
  # See "Triggers" section below

logging:
  level: INFO          # DEBUG | INFO | WARNING | ERROR
  format: json         # "json" | "text"
  output: stdout       # "stdout" | file path
```

---

## Adapters

Adapters pull records from external systems and transform them to the Hippo schema.

### CSVAdapter

For tabular data from CSV files, HTTP URLs, or direct uploads.

```yaml
adapters:
  my_csv_source:
    type: csv
    trust_level: 80        # 0-100; higher wins conflicts
    config:
      source: file         # "file" | "http" | "manual_upload"
      url: "/data/export.csv"     # file path or HTTP URL
      entity_type: Sample
      external_id_field: SAMPLE_ID    # CSV column that uniquely identifies each record
      field_map:
        SAMPLE_ID: external_id         # CSV column → Hippo field name
        TISSUE: tissue
        DONOR_ID: donor_id
      vocabulary_map:
        tissue:                        # field name → {source value: canonical value}
          "DLPFC": "dorsolateral prefrontal cortex"
          "HC": "hippocampus"
```

**Sources:**
- `file` — read from a local file path (set `url` to the path)
- `http` — GET request to a URL on each sync
- `manual_upload` — data must be provided when calling `pipeline.run(data=bytes)` or via `POST /ingest/{adapter_name}`

### JSONAdapter

For REST APIs or JSON files. Supports JSONPath to locate the records array within a response envelope.

```yaml
adapters:
  halo_api:
    type: json
    trust_level: 70
    config:
      source: http
      url: "https://halo.example.edu/api/v2/scores"
      auth_header: "X-API-Key: ${HALO_KEY}"
      records_path: "$.data.records[*]"   # JSONPath to the records array
      entity_type: HistopathologyScore
      external_id_field: score_id
      field_map:
        score_id: external_id
        sample_barcode: sample_external_id
        value: score_value
```

### SQLAdapter

For any SQL database (PostgreSQL, MySQL, SQLite). The query is declared in config — no code needed.

```yaml
adapters:
  lims_db:
    type: sql
    trust_level: 90
    config:
      connection_string: "postgresql://${LIMS_USER}:${LIMS_PASS}@lims.example.edu/lims"
      entity_type: Donor
      external_id_field: subject_id
      query: |
        SELECT subject_id, sex, age_at_death, diagnosis
        FROM subjects
        WHERE status = 'available'
      incremental_query: |
        SELECT subject_id, sex, age_at_death, diagnosis
        FROM subjects
        WHERE updated_at > :since
      field_map:
        subject_id: external_id
      vocabulary_map:
        diagnosis:
          "CTE": "chronic traumatic encephalopathy"
```

**Security:** Use a read-only database account. Cappella rejects queries containing write operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`) at startup.

**Incremental sync:** When `incremental_query` is set and the adapter is configured with `incremental: true`, the `:since` parameter is automatically bound to the timestamp of the last successful sync.

### Custom Adapter Plugins

For complex integrations (OAuth flows, paginated APIs, SFTP, proprietary protocols), implement `ExternalSourceAdapter` in a separate package:

```python
from cappella.adapters.base import ExternalSourceAdapter
from cappella.types import RawRecord, TransformedRecord

class MyLIMSAdapter(ExternalSourceAdapter):
    name = "my_lims"
    entity_types = ["Sample", "Donor"]
    supports_incremental = True

    def __init__(self, config: dict) -> None:
        self._client = MyLIMSClient(config["base_url"], config["token"])

    def fetch(self, since=None):
        for record in self._client.get_all(since=since):
            yield RawRecord(
                source_system="my_lims",
                external_id=record["id"],
                data=record,
            )

    def transform(self, record: RawRecord) -> TransformedRecord:
        return TransformedRecord(
            entity_type="Sample",
            data={"name": record.data["sample_name"], ...},
            external_id=record.external_id,
            source_system="my_lims",
            trust_level=80,
        )
```

Register via entry point in your package's `pyproject.toml`:
```toml
[project.entry-points."cappella.adapters"]
my_lims = "my_lims_package:MyLIMSAdapter"
```

---

## Conflict Resolution

When two sources provide different values for the same field on the same entity, Cappella uses trust levels to decide:

- **Higher trust wins** — the source with the higher `trust_level` (0-100) overwrites the other
- **Last-write wins** — if trust levels are equal, the most recent sync wins
- **Manual review** — if the same field conflicts with equal trust, a `HarmonizationConflict` provenance event is recorded on the entity for human review

Every conflict is permanently recorded as a provenance event on the entity in Hippo — nothing is silently overwritten.

---

## Collection Resolution

The resolution API finds all entities matching a set of criteria, ensuring they are materialized via Canon.

### Request Format

```python
from cappella.resolver.collection import CollectionResolver, ResolutionRequest

resolver = CollectionResolver()
request = ResolutionRequest(
    entity_type="GeneCounts",
    criteria={
        "donor.diagnosis": "chronic traumatic encephalopathy",
        "sample.tissue": "DLPFC",
    },
    parameters={
        "genome": "GRCh38",
        "annotation": "ensembl110",
    },
    selection={
        "strategy": "most_recent",
        "filters": {"min_reads": 1000000},
    },
)
collection = resolver.resolve(request, hippo_client=hippo, canon_client=canon)
```

### Criteria Dot Notation

Criteria use dot notation to traverse entity relationships:
- `donor.diagnosis` — filter the `Donor` entity linked via `Sample.donor_id`
- `sample.tissue` — filter the `Sample` entity linked via `SequencingDataset.sample_id`
- `dataset.assay` — filter the `SequencingDataset` directly

The traversal path is inferred automatically from the Hippo schema's `references:` declarations via `HippoClient.schema_references()` (implemented in Hippo v0.4). Schema fields must declare `references: {entity_type: <name>}` for traversal to work.

### Selection Strategies

| Strategy | Behavior |
|----------|----------|
| `most_recent` | Pick the dataset with the latest `created_at` after filters |
| `highest_quality` | Pick highest value of `quality_field` (configurable) after filters |
| `explicit` | Use declared `overrides` map; fall back to `most_recent` for uncovered samples |
| `single_only` | Raise error if any sample has multiple candidates after filters |

Custom strategies via `cappella.selection_strategies` entry point:
```python
from cappella.types import SelectionStrategy

class LabStandardStrategy(SelectionStrategy):
    def select(self, candidates, filters=None):
        # Your lab's custom selection logic
        ...
```

---

## Triggers

Triggers automate ingest and resolution operations.

### Schedule Triggers

```yaml
triggers:
  - name: nightly_sync
    type: schedule
    schedule: "0 2 * * *"    # cron expression
    action:
      type: ingest
      adapter: lims_db
    on_success: lims_sync_complete    # emit this internal event on success
```

### Manual Triggers

Fire on demand via the CLI or API:

```bash
cappella trigger run nightly_sync --config cappella.yaml
```

```bash
curl -X POST http://localhost:8000/triggers/nightly_sync/run
```

### Internal Event Triggers

React to events emitted by other triggers:

```yaml
triggers:
  - name: resolve_after_sync
    type: internal_event
    event: lims_sync_complete         # fires when lims_sync_complete is emitted
    action:
      type: resolve
      entity_type: GeneCounts
      parameters:
        genome: GRCh38
```

### Webhook Triggers

*Added in v0.2.* Receive HTTP callbacks from external systems. Cappella exposes a webhook endpoint that external services (such as HALO) can POST to, triggering an ingest or resolution action.

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

**Signature verification:** The calling system must include an `X-Signature` header containing the HMAC-SHA256 digest of the request body, computed with the secret specified by `secret_env`. Cappella returns `403 Forbidden` if the signature is missing or invalid.

**CEL condition filtering:** The `when` field accepts a [CEL](https://github.com/google/cel-spec) expression evaluated against the parsed JSON payload. If the expression evaluates to `false`, Cappella returns `200 OK` but takes no action. This lets you subscribe to a broad event stream and only act on relevant payloads.

**Idempotency:** Within the configured `idempotency_window_seconds`, Cappella computes a SHA-256 digest of the request body and deduplicates retries automatically. If a payload with the same digest arrives within the window, Cappella returns `200 OK` with the original run ID and does not re-execute the action.

### Hippo Poll Triggers

*Added in v0.2.* Poll Hippo for new or updated entities matching a filter, and fire an action for each matched entity.

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

**Polling behavior:** On each tick, Cappella queries Hippo for entities of the specified `entity_type` whose `updated_at` falls within the lookback window and that match the `filter` expression. The query uses Hippo's `updated_at` index for efficient retrieval.

**Per-entity actions:** The action is fired once per matched entity. Use `{entity.<field>}` bindings in `criteria` and `parameters` to inject values from the matched entity into the action. For example, `{entity.id}` resolves to the matched entity's ID.

**Cursor persistence:** Cappella persists its poll cursor as a `CappellaPollCursor` entity in Hippo, keyed by trigger name. This ensures that after a restart, polling resumes from where it left off rather than re-processing old entities. The cursor advances to the latest `updated_at` timestamp seen in each poll cycle, regardless of whether the triggered action succeeds or fails.

**Trigger types:**
- `schedule` — cron expression (uses standard 5-field cron syntax)
- `manual` — fire via `cappella trigger run <name>` or `POST /triggers/{name}/run`
- `internal_event` — fires when a named event is emitted by another trigger's `on_success`
- `webhook` — fires when an external system sends an HTTP POST to the configured path
- `mosaic_poll` — fires per entity when Hippo entities matching the filter are created or updated

**Action types:**
- `ingest` — run an adapter's fetch/transform/upsert pipeline
- `resolve` — run collection resolution

---

## Reconciliation

Run inconsistency checks across your entity data:

```bash
cappella reconcile \
  --entity-types Donor Sample \
  --config cappella.yaml
```

**Built-in checks:**
- `missing_entity` — entity referenced in external system has no Hippo record
- `stale_entity` — Hippo entity not updated within expected window
- `field_conflict` — same field has different values in two trusted sources
- `broken_reference` — entity references a nonexistent entity
- `missing_artifact` — entity has no associated file artifact

**View findings:**
```bash
cappella findings --config cappella.yaml
cappella findings --check field_conflict --entity-type Donor --config cappella.yaml
```

Each finding is a structured record with the entity ID, field, source values, and a suggested action (manual review, trust source A/B).

---

## Provenance

Every entity write made by Cappella carries a structured provenance context in Hippo:

```json
{
  "cappella_version": "0.1.0",
  "source_system": "lims_db",
  "adapter": "sql",
  "run_id": "uuid-123",
  "trigger": "nightly_sync",
  "trust_level": 90,
  "fetched_at": "2026-03-26T02:00:01Z"
}
```

This is queryable through Hippo's standard provenance API — every entity change has a complete audit trail.
