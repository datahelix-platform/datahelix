# Section 1: Overview & Scope

**Status:** Draft v0.1  
**Last updated:** 2026-03-25

---

## 1.1 What Cappella Is

Cappella is the **harmonization engine** of the DataHelix platform. Its name reflects its role: like voices singing *a cappella* — in harmony, without instrumentation — Cappella takes data arriving from many different sources and makes them sing together in a single, consistent, provenance-rich picture stored in Hippo.

Cappella answers the question: **"Is everything we know about this subject consistent, present, and correct?"**

It does not answer: "Where is the analysis file?" (that's Canon), "What entities exist?" (that's Hippo), or "How do I visualize these results?" (that's Aperture/Composer).

---

## 1.2 Core Responsibilities

### Harmonization
Data arrives from multiple external sources — STARLIMS (sample and donor records), HALO (histopathology scores), REDCap (clinical assessments), sequencing cores (FASTQ manifests), and Canon (computed file artifacts). Each source has its own schema, identifier conventions, and update cadence. Cappella's job is to:

- Pull structured data from external sources via **adapter plugins**
- Transform fields to the canonical Hippo schema
- Validate consistency against existing Hippo entities
- Upsert via ExternalID (create if absent, update if changed)
- Record structured provenance context on every write

### Collection Resolution
When a user (via Aperture, a CLI, or Composer) asks for "all aligned reads for CTE DLPFC samples with these characteristics," Cappella:

1. Queries Hippo to find matching donors, samples, and datasets
2. Applies **selection logic** — choosing between alternatives (multiple sequencing runs, QC thresholds, recency)
3. Calls `canon.resolve()` for each required artifact per sample
4. Returns a **harmonized collection** — a fully-resolved, provenance-rich JSON response in Hippo schema space

Cappella returns the collection. It does not merge files, run analyses, or transform the contents of files. Downstream consumers (Composer, notebooks, custom scripts) receive the collection and decide what to do with it.

### Reconciliation
Cappella actively monitors for inconsistencies — a Donor in STARLIMS that doesn't match the Donor in REDCap, a Sample with no corresponding FASTQ, an entity that exists in an external system but not yet in Hippo. These discrepancies are surfaced as structured audit events and optionally trigger resolution workflows.

### Trigger Engine
Cappella executes ingest and resolution operations in response to:
- **Schedule triggers** — periodic syncs with external systems
- **Webhook triggers** — push notifications from external systems
- **Hippo poll triggers** — reactive to entity state changes in Hippo
- **Manual triggers** — explicit API calls from users or Composer
- **Internal event triggers** — chained actions within Cappella

---

## 1.3 What Cappella Is Not

**Cappella does not run bioinformatics analyses.** CWL execution, file production, and file caching are Canon's domain. Cappella calls `canon.resolve()` and receives a URI; it never invokes cwltool or manages file storage directly.

**Cappella does not aggregate or transform file contents.** Merging count matrices, running DESeq2, combining cluster results — these are Composer concerns. Cappella delivers the collection of resolved entities; the consumer decides how to use them.

**Cappella does not own any data.** It is stateless. Hippo is the sole persistent store. Every write Cappella makes goes through HippoClient; no Cappella-local database exists.

**Cappella is not a workflow DAG engine.** Trigger chaining (action A emits event, action B reacts) is simple event-driven composition, not a DAG scheduler. Complex multi-step analysis pipelines that require DAG semantics belong in Composer.

---

## 1.4 Relationship to Other Components

```
┌──────────────────────────────────────────────────────────────┐
│  Aperture / Composer                                          │
│  "How do humans see, request, and analyze results?"          │
│  Consumes Cappella collections; runs aggregate analyses      │
├──────────────────────────────────────────────────────────────┤
│  Cappella                                                     │
│  "Is everything consistent, present, and correct?"           │
│  Harmonizes sources → Hippo; resolves collections via Canon  │
├────────────────┬─────────────────────────────────────────────┤
│  Canon         │  External Adapters (STARLIMS, HALO, REDCap) │
│  Artifact      │  Structured attribute data from external    │
│  resolution    │  systems, transformed to Hippo schema       │
│  (REUSE/FETCH/ │                                             │
│   BUILD/FAIL)  │                                             │
├────────────────┴─────────────────────────────────────────────┤
│  Hippo                                                        │
│  "What is known." All entities, attributes, relationships,   │
│  provenance. Structured data + file URI pointers.            │
└──────────────────────────────────────────────────────────────┘
```

### Canon
Canon is Cappella's **artifact resolution engine**, not a peer data source. When Cappella needs to ensure that aligned read files exist for a cohort, it calls `canon.resolve()` for each sample. Canon handles REUSE/FETCH/BUILD/FAIL internally; Cappella never invokes cwltool or touches storage directly. Canon inserts file-backed entities into Hippo directly — this is by design, consistent with external adapters that also write to Hippo directly. Cappella's harmonization responsibility is to ensure consistency *across* all entities, regardless of how they were written.

### External Adapters
STARLIMS, HALO, REDCap, and similar systems are accessed via pluggable `ExternalSourceAdapter` implementations that live in Cappella. The `ExternalSourceAdapter` ABC is defined in Hippo (as a plugin contract); concrete implementations for specific systems are Cappella's domain. Adapters pull records, transform to Hippo schema, and upsert via ExternalID.

### Hippo
Hippo is Cappella's sole persistent store. All state — entity records, sync history, adapter configs — lives in Hippo entities. Cappella never maintains its own database.

### Aperture / Composer
Aperture is the portal — the human interface. Composer (Aperture's analysis plugin layer, or an independent tool) receives Cappella's harmonized collections and applies domain-specific transformations: merging count files, running DESeq2, visualizing clusters. The boundary is clean: Cappella delivers resolved entity collections in JSON; Composer decides what to do with the files those entities point to.

---

## 1.5 Harmonized Collection Format

Cappella's primary output for collection resolution requests is a **HarmonizedCollection** — a structured JSON response containing:

```json
{
  "request": {
    "entity_type": "GeneCounts",
    "criteria": {"diagnosis": "CTE", "tissue": "DLPFC", "genome": "GRCh38"},
    "requested_at": "2026-03-25T17:30:00Z",
    "requested_by": "aperture-user:adam"
  },
  "selection": {
    "strategy": "most_recent_per_sample",
    "qc_threshold": {"min_reads": 1000000}
  },
  "resolved": [
    {
      "sample_id": "S001",
      "entity": {"id": "uuid-1", "entity_type": "GeneCounts", "uri": "s3://bucket/s001.counts.tsv"},
      "status": "reused",
      "canon_decision": "REUSE"
    },
    {
      "sample_id": "S002",
      "entity": {"id": "uuid-2", "entity_type": "GeneCounts", "uri": "s3://bucket/s002.counts.tsv"},
      "status": "built",
      "canon_decision": "BUILD"
    }
  ],
  "unresolved": [
    {
      "sample_id": "S003",
      "reason": "no_fastq",
      "detail": "No SequencingDataset found in Hippo for sample S003"
    }
  ],
  "provenance": {
    "mosaic_version": "0.3.1",
    "canon_version": "0.2.0",
    "cappella_version": "0.1.0",
    "genome_build": {"id": "uuid-genome", "name": "GRCh38", "release": "110"}
  }
}
```

This format is stable and versioned. Composer and other consumers parse it to extract URIs, sample mappings, and provenance. The format is designed to be directly serializable to a Hippo entity (`ResolutionRun`) for long-term audit storage.

---

## 1.6 Scope: v0.1

**In scope for Cappella v0.1:**
- Adapter plugin system and ExternalSourceAdapter ABC (implementations: STARLIMS stub, manual ingest)
- Ingest pipeline: pull → transform → validate → upsert via ExternalID
- Collection resolution: Hippo query + selection logic + Canon delegation + HarmonizedCollection output
- Reconciliation: inconsistency detection and structured audit events
- Trigger engine: schedule, manual, internal_event (webhook + mosaic_poll deferred to v0.2)
- Provenance: structured context on all Hippo writes
- REST API: `POST /resolve`, `POST /ingest`, `GET /status`, `POST /triggers/{name}/run`

**Deferred to v0.2:**
- Webhook trigger implementation
- Hippo poll triggers
- Live external system integrations (STARLIMS, HALO, REDCap concrete adapters)
- `ResolutionRun` entity storage in Hippo for long-term audit

**Out of scope (Composer/Aperture concerns):**
- Aggregate analysis (merge counts, DESeq2, clustering)
- File format transformation
- Domain-specific computation
- Visualization
