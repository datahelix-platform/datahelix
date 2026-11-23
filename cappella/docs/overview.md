# Cappella — Overview

**Cappella** is the harmonization engine of the DataHelix platform. Its job is to make data from many different sources sing together in a single, consistent, provenance-rich picture.

## The Problem It Solves

A neuroscience research lab tracks data across multiple systems:
- **STARLIMS** — sample and donor records (exports CSV)
- **HALO** — histopathology scores (JSON API)
- **REDCap** — clinical assessments (CSV export or SQL)
- **Sequencing core** — FASTQ manifests (spreadsheets)
- **Canon** — computed artifacts (alignment files, gene counts)

Each system uses different field names, different controlled vocabularies, and different update cadences. Cappella pulls all of this together into Hippo — the platform's structured domain graph — ensuring everything is consistent, correctly linked, and fully provenance-tracked.

## What Cappella Does

**Ingest & harmonize** — Pull records from external sources, transform field names and vocabulary to the canonical Hippo schema, detect conflicts between sources, and upsert with full provenance context.

**Collection resolution** — Given a high-level research question ("give me all gene counts for CTE DLPFC donors"), Cappella queries Hippo to find matching entities, applies selection logic to choose the right dataset per sample, and calls Canon to ensure all required files are materialized. Returns a structured `HarmonizedCollection` with resolved URIs and provenance.

**Reconciliation** — Actively detects inconsistencies: a donor present in STARLIMS but missing from Hippo, a field value that differs between two trusted sources, a sample with no corresponding sequencing dataset. Findings are logged for human review.

**Trigger engine** — Automates ingest and resolution operations on a schedule, on-demand via the API, or in response to internal events.

## What Cappella Does NOT Do

- **Run analyses** — DESeq2, clustering, QC pipelines are downstream (Composer) concerns
- **Manage files** — Canon handles file storage, caching, and production
- **Own data** — All persistent state lives in Hippo; Cappella is stateless

## Platform Position

```
Aperture / Composer  ← user interface, aggregate analysis
      │
   Cappella          ← harmonize sources, resolve collections
    │    │
  Canon  External Adapters (STARLIMS, HALO, REDCap, CSV files)
      │
   Hippo             ← entity store (all metadata + file URIs)
```

## Key Concepts

**HarmonizedCollection** — Cappella's primary output. A JSON object containing:
- `resolved[]` — entities with URIs and Canon decision (REUSE/FETCH/BUILD)
- `unresolved[]` — samples that couldn't be resolved, with structured reasons
- `provenance{}` — versions, genome build, selection criteria

**Adapter** — A plugin that knows how to pull records from one external system. Cappella ships four generic adapters (`csv`, `json`, `xml`, `sql`) and supports custom plugins via the `cappella.adapters` entry point group.

**SelectionStrategy** — Logic for choosing one dataset when a sample has multiple candidates. Built-in: `most_recent`, `highest_quality`, `explicit`, `single_only`. Custom strategies are pluggable.

**Trigger** — A rule that fires an ingest or resolution operation. Types: `schedule` (cron), `manual` (API call), `internal_event` (chained from another action), `webhook` (external HTTP callback), `mosaic_poll` (poll Hippo for new/updated entities).
