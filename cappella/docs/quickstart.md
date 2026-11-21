# Cappella — Quick Start

## Installation

```bash
pip install cappella

# For SQL adapter support:
pip install cappella[sql]

# For development:
pip install cappella[dev]
```

## Minimal Configuration

Create `cappella.yaml`:

```yaml
mosaic:
  url: "http://localhost:8001"
  token: "${MOSAIC_TOKEN}"

canon:
  enabled: true
  mode: in_process    # import canon directly (no separate service needed)

adapters:
  donors:
    type: csv
    trust_level: 80
    config:
      source: file
      url: "/data/exports/donors.csv"
      entity_type: Donor
      external_id_field: SUBJECT_ID
      field_map:
        SUBJECT_ID: external_id
        SEX: sex
        AGE_AT_DEATH: age_at_death
        DIAGNOSIS: diagnosis
      vocabulary_map:
        diagnosis:
          "CTE": "chronic traumatic encephalopathy"
          "AD": "Alzheimer disease"

triggers:
  - name: weekly_donor_sync
    type: schedule
    schedule: "0 2 * * 0"    # Sunday 2 AM
    action:
      type: ingest
      adapter: donors
```

## Start the Service

```bash
cappella serve --config cappella.yaml
```

Or just use the CLI without starting a server.

## Ingest Data

**From a file (scheduled or manual):**
```bash
cappella ingest donors --config cappella.yaml
```

**Upload a CSV directly:**
```bash
cappella ingest donors --file new_donors.csv --config cappella.yaml
```

**Fire a trigger manually:**
```bash
cappella trigger run weekly_donor_sync --config cappella.yaml
```

## Resolve a Collection

Get all gene counts for CTE DLPFC samples against GRCh38:

```bash
cappella resolve \
  --entity-type GeneCounts \
  --criteria "donor.diagnosis=chronic traumatic encephalopathy" \
  --criteria "sample.tissue=DLPFC" \
  --parameters genome=GRCh38 \
  --config cappella.yaml \
  --output my_collection.json
```

Output (`my_collection.json`):
```json
{
  "request": {
    "entity_type": "GeneCounts",
    "criteria": {"donor.diagnosis": "chronic traumatic encephalopathy", "sample.tissue": "DLPFC"}
  },
  "selection": {"strategy": "most_recent"},
  "resolved": [
    {"sample_id": "S001", "entity": {"id": "uuid-1", "uri": "s3://bucket/s001.counts.tsv"}, "status": "reused"},
    {"sample_id": "S002", "entity": {"id": "uuid-2", "uri": "s3://bucket/s002.counts.tsv"}, "status": "built"}
  ],
  "unresolved": [
    {"sample_id": "S003", "reason": "no_dataset", "detail": "No SequencingDataset found for sample S003"}
  ],
  "provenance": {"cappella_version": "0.1.0", "canon_version": "0.2.0"},
  "resolved_count": 2,
  "unresolved_count": 1
}
```

## Via the REST API

```bash
# Start the server
cappella serve --config cappella.yaml

# Resolve via API
curl -X POST http://localhost:8000/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "entity_type": "GeneCounts",
    "criteria": {"donor.diagnosis": "chronic traumatic encephalopathy"},
    "parameters": {"genome": "GRCh38"}
  }'

# Response: 202 Accepted with run_id
# {"run_id": "uuid-789", "status": "queued", "poll_url": "/resolve/uuid-789"}

# Poll for result
curl http://localhost:8000/resolve/uuid-789
```

## Check Status

```bash
cappella status --config cappella.yaml
```

```json
{
  "cappella_version": "0.1.0",
  "mosaic": {"status": "ok", "version": "0.3.1"},
  "adapters": {
    "donors": {"status": "ok", "last_sync": "2026-03-26T02:00:47Z"}
  }
}
```

## Python API

```python
from cappella.config import load_config
from cappella.adapters.csv_adapter import CSVAdapter
from cappella.ingest.pipeline import IngestPipeline

# Load config
config = load_config("cappella.yaml")

# Ingest from CSV
adapter = CSVAdapter(config.adapters["donors"].config)
pipeline = IngestPipeline(hippo_client=hippo_client)
result = pipeline.run(adapter)

print(f"Ingested {result.upserted} entities ({result.created} new, {result.updated} updated)")
print(f"Conflicts detected: {result.conflicts_detected}")
```

## Next Steps

- [User Guide](user_guide.md) — detailed adapter configuration, selection strategies, triggers
- [Design Spec](../design/INDEX.md) — architecture decisions and component boundaries
- [API Reference](api_reference.md) — full REST API and CLI documentation
