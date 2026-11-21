# Section 5: Integration Test Strategy

**Document status:** Draft v0.1
**Last updated:** 2026-03-31
**Depends on:** `platform/design/INDEX.md`, `mosaic/design/sec7_nfr.md`, `cappella/design/sec6_nfr.md`
**Feeds into:** Phase 1 Epic 1.1 — implementation of `tests/contracts/` and `tests/platform/`

---

## 5.1 Purpose and Scope

This document specifies the **round-trip integration test strategy** for the DataHelix platform. It covers:

1. The full end-to-end scenario: external source → Cappella → Mosaic (formerly Hippo, ADR-0004) → Canon → Mosaic (provenance write-back)
2. Test data setup requirements
3. Assertions at each stage
4. Contract test coverage matrix

This strategy is the authoritative source for what the Phase 1 integration test suite must cover. It does not replace the unit test policies in `TESTING.md`; it extends the Tier 2 (contract) and Tier 3 (platform) layers with the cross-component integration view.

> **Independently-versioned components (aperture, mosaic) — see [ADR-0001](decisions/ADR-0001-certified-frontier-composition.md).**
> The in-process round-trip below covers the in-tree components. For components that ship as their own repos/submodules with independent semver releases, the composition is certified **per exact version pair (with artifact digests)** via the **certified-frontier ledger**, and deployment is gated on it. That infrastructure — the ledger tooling, the versioned bootstrap fixture, the golden-path Playwright suite (one scenario per product loop), the certification workflow, the bump bot, and the deploy gate — lives in [`certification/`](../../certification/). The two strategies are complementary: this section is the in-process integration view; ADR-0001 is the cross-repo composition-certification view.

---

## 5.2 Full Round-Trip Scenario

### 5.2.1 Scenario definition

The canonical integration test scenario traces a single sample from an external source through the full platform stack:

```
External source
    │  (1) adapter sync — Cappella ingests specimen record
    ▼
Mosaic
    │  (2) entity created: Sample{subject_id, tissue_type, ...}
    ▼
Canon (via Cappella resolve)
    │  (3) resolve(AlignedDatafile, {sample_id: <uuid>, ...})
    │      → REUSE if alignment exists; BUILD if not
    ▼
Mosaic
    │  (4) provenance write-back: WorkflowRun entity, AlignedDatafile entity
    ▼
Mosaic (query)
    │  (5) Canon result URI retrievable; provenance queryable
```

Each arrow is a testable assertion boundary. The test must verify both the happy path (full success) and partial-failure behavior (Canon REUSE vs BUILD, unresolved items).

### 5.2.2 Scope boundary

This integration test does **not** invoke a real CWL executor. The Canon BUILD path is tested using a mock CWL executor that produces a deterministic output file URI. The integration test validates that:

- Cappella wires inputs correctly to Canon's `resolve()` call
- Canon writes a `WorkflowRun` entity and an output entity to Mosaic
- The provenance chain from input `Sample` through `WorkflowRun` to output `AlignedDatafile` is queryable

Real CWL execution is validated in Canon's own unit tests, not in the platform round-trip.

---

## 5.3 Test Data Setup

### 5.3.1 Minimal schema

The integration test uses a single-file schema that defines the minimum entity types needed to trace the round-trip:

```yaml
# tests/fixtures/integration_schema.yaml

entity_types:
  Subject:
    fields:
      external_id: {type: string, required: true, unique: true}
      species:     {type: string, required: true}

  Sample:
    fields:
      subject_id:  {type: ref, target: Subject, required: true}
      tissue_type: {type: string, required: true}

  AlignedDatafile:
    fields:
      sample_id:   {type: ref, target: Sample, required: true}
      aligner:     {type: string, required: true}
      aligner_version: {type: string, required: true}
      uri:         {type: string, required: true}
```

### 5.3.2 Minimal Canon rules

```yaml
# tests/fixtures/integration_rules.yaml

rules:
  - name: align_sample
    produces:
      entity_type: AlignedDatafile
      match:
        sample_id: "{{sample_id}}"
        aligner: hisat2
        aligner_version: "2.2.1"
    requires:
      - entity_type: Sample
        bind: sample
        match:
          id: "{{sample_id}}"
    execute:
      workflow: tests/fixtures/align.cwl
      inputs:
        sample: "{{sample.uri}}"
      outputs:
        uri: aligned_bam
```

### 5.3.3 Seed data

The test fixture creates the following entities in Mosaic before the round-trip begins:

| Entity | Field | Value |
|--------|-------|-------|
| `Subject` | `external_id` | `SUBJ-001` |
| `Subject` | `species` | `Homo sapiens` |
| `Sample` | `subject_id` | `<subject uuid>` |
| `Sample` | `tissue_type` | `brain` |

---

## 5.4 Stage-by-Stage Assertions

### Stage 1 — Cappella adapter sync

**Action:** Run the test adapter's `sync()` against a mocked external source that returns one specimen record for `SUBJ-001`.

**Assertions:**
- `MosaicClient.query(Sample)` returns exactly one entity
- The returned entity has `tissue_type == "brain"` and `subject_id` pointing to the seeded `Subject`
- A `SyncRun` log entry exists with `entities_created == 1`, `entities_updated == 0`, `entities_unchanged == 0`, `errors == []`
- Re-running the same sync is idempotent: `entities_unchanged == 1`, no new `Sample` created

**Failure signal:** Cappella adapter wrote a duplicate entity, or `subject_id` ref was not resolved to the canonical UUID.

---

### Stage 2 — Mosaic entity integrity

**Action:** Direct `MosaicClient` queries after the sync.

**Assertions:**
- `client.get(Sample, <sample_uuid>)` returns the full entity with all required fields
- `client.history(<sample_uuid>)` contains one provenance event with `actor == "cappella:adapter:test_adapter"` and `operation == "create"`
- `client.query(Sample, limit=100)` returns the entity in results (availability filter: available only)

---

### Stage 3 — Canon resolve (REUSE path)

**Precondition:** An `AlignedDatafile` entity already exists in Mosaic for the seeded `Sample`, seeded directly.

**Action:** Call `canon.resolve(AlignedDatafile, {sample_id: <uuid>, aligner: "hisat2", aligner_version: "2.2.1"})`.

**Assertions:**
- Return value is a non-empty URI string
- The URI matches `dhlx://AlignedDatafile/<existing_uuid>`
- No `WorkflowRun` entity was created in Mosaic (REUSE does not write)
- `canon plan(...)` output shows `REUSE` decision for this spec

---

### Stage 4 — Canon resolve (BUILD path)

**Precondition:** No `AlignedDatafile` exists for the seeded `Sample` (fresh Mosaic state).

**Action:** Call `canon.resolve(AlignedDatafile, {sample_id: <uuid>, aligner: "hisat2", aligner_version: "2.2.1"})` with mock CWL executor returning a deterministic URI.

**Assertions:**
- Return value is a non-empty URI string for the newly created entity
- A `WorkflowRun` entity exists in Mosaic with:
  - `status == "completed"`
  - `rule == "align_sample"`
  - `input_entities` contains `<sample_uuid>`
  - `cwl_workflow_sha256` is a non-empty string
- An `AlignedDatafile` entity exists in Mosaic with `uri == <mock_output_uri>` and `sample_id == <sample_uuid>`
- `canon plan(...)` output shows `BUILD` decision before execution, `REUSE` after

**Failure signal:** `WorkflowRun` entity missing; `AlignedDatafile` not written to Mosaic; provenance chain broken.

---

### Stage 5 — Provenance write-back verification

**Action:** Query Mosaic for the full provenance chain after a BUILD.

**Assertions:**
- `client.history(<aligned_datafile_uuid>)` contains a `create` event with actor `"canon:align_sample"`
- The `WorkflowRun` entity's `input_entities` contains `<sample_uuid>`
- The `WorkflowRun` entity is linked to the `AlignedDatafile` via the `produced_by` relationship (or equivalent relationship as defined in the integration schema)
- `client.query(WorkflowRun, filters={rule: "align_sample"})` returns the run in results
- `client.query(AlignedDatafile, filters={sample_id: <sample_uuid>})` returns the output entity

---

## 5.5 Partial-Failure Behavior

The round-trip test includes a **partial failure scenario** to validate Cappella's non-aborting behavior:

**Setup:** A Cappella resolution run over a cohort of 3 samples, where 2 have matching Canon rules and 1 does not.

**Expected result structure:**
```json
{
  "resolved": [
    {"sample_id": "uuid-1", "uri": "dhlx://AlignedDatafile/uuid-A"},
    {"sample_id": "uuid-2", "uri": "dhlx://AlignedDatafile/uuid-B"}
  ],
  "unresolved": [
    {
      "sample_id": "uuid-3",
      "reason": "NO_RULE",
      "detail": "No Canon rule produces AlignedDatafile for tissue_type=csf"
    }
  ]
}
```

**Assertions:**
- `len(result.resolved) == 2`
- `len(result.unresolved) == 1`
- `unresolved[0].reason` is one of the documented reason codes: `NO_RULE`, `RESOLUTION_ERROR`, `EXECUTOR_ERROR`, `MOSAIC_ERROR`
- The resolved entities are in Mosaic and queryable
- The run did not abort — a `SyncRun` log entry exists with `status == "partial_success"`

---

## 5.6 Contract Test Coverage Matrix

The following table maps cross-component contracts to their test files. All must pass before Phase 1 exits.

| Contract | Test file | Status | Key assertions |
|---|---|---|---|
| Canon expects Mosaic | `tests/contracts/test_canon_expects_mosaic.py` | Exists | `query()`, `create()`, `get()`, availability filtering, `update()` |
| Cappella expects Mosaic | `tests/contracts/test_cappella_expects_mosaic.py` | Exists (commit a5900b2) | Upsert-by-ExternalID, `query_updated_since()`, provenance event shape |
| Cappella expects Canon | `tests/contracts/test_cappella_expects_canon.py` | ✅ Written (commit 59cd0ef) | `resolve()` URI format, REUSE/BUILD idempotency, `resolve_with_decision()` decision field, CanonNoRuleError/CanonExecutorError/CanonRuleValidationError hierarchy |
| Entity loader contract | `tests/contracts/test_entity_loader_contract.py` | In repo — review needed | Flat-file ingestion behavioral guarantees |

The Cappella-expects-Canon contract gap is now closed. See `TESTING.md §Contract Specification: Cappella's View of Canon` for the behavioral spec.

---

## 5.7 File Layout

All integration test artifacts live in the following locations:

```
tests/
├── contracts/
│   ├── test_canon_expects_mosaic.py          # existing
│   ├── test_cappella_expects_mosaic.py       # existing
│   ├── test_cappella_expects_canon.py       # ✅ written (Phase 1, commit 59cd0ef)
│   └── test_entity_loader_contract.py       # existing, review needed
├── fixtures/
│   ├── integration_schema.yaml              # minimal schema (§5.3.1)
│   ├── integration_rules.yaml              # minimal Canon rules (§5.3.2)
│   └── align.cwl                           # mock CWL workflow stub
└── platform/
    ├── conftest.py                          # MosaicClientShim, mock CWL executor
    ├── test_canon_platform.py               # existing
    ├── test_mosaic_canon.py                  # existing
    └── test_round_trip.py                   # ✅ written (Phase 1, commit 59cd0ef) — §5.4 scenarios
platform/
└── benchmarks/
    └── baseline.md                         # NFR performance baselines (§5.8)
```

---

## 5.8 Performance Regression Gate

Once `platform/benchmarks/baseline.md` is written, the round-trip test suite must include a smoke-level performance check:

| Check | Threshold | Notes |
|---|---|---|
| Single `client.get()` (warm) | < 10ms | 2× Mosaic p99 target — allows test overhead |
| Adapter sync (1 record) | < 5s | Wall clock; includes Mosaic write + ExternalID lookup |
| Canon resolve (REUSE, 1 sample) | < 5s | 2.5× Cappella target; allows test harness overhead |
| Full round-trip (BUILD, 1 sample, mock CWL) | < 15s | Wall clock; mock CWL returns immediately |

These thresholds are **not** hard performance benchmarks — they are regression gates. A failure here means something in the stack became unexpectedly slow, not that the system fails to meet production NFRs. Production baselines are in `platform/benchmarks/baseline.md`.
