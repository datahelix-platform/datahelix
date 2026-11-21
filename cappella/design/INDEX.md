# Cappella — Integration & Harmonization Engine
## Specification Index

**Codename:** Cappella  
**Component:** Integration & Harmonization Engine  
**Version:** 0.1 (implemented)

---

## Document Map

| File | Section | Status | Notes |
|---|---|---|---|
| `sec1_overview.md` | 1. Overview & Scope | ✅ Draft v0.1 | Harmonization engine, collection resolution, HarmonizedCollection format, v0.1 scope |
| `sec2_architecture.md` | 2. Architecture | ✅ Draft v0.1 | Adapter registry, ingest pipeline, collection resolver, trigger engine, reconciliation, API surface |
| `sec3_adapters.md` | 3. Adapter System | ✅ Draft v0.1 | ExternalSourceAdapter ABC, field mapping config, vocabulary normalization, built-in stubs, error handling |
| `sec4_audit.md` | 4. Audit & Observability | ✅ Draft v0.1 | Structured log events, HarmonizationConflict provenance, health endpoint |
| `sec5_workflows.md` | 5. Collection Resolution Workflow | ✅ Draft v0.1 | Schema-driven traversal, selection strategies, partial failure, async resolution, CLI |
| `sec6_nfr.md` | 6. Non-Functional Requirements | ✅ Draft v0.1 | Performance targets, reliability, scalability tiers, extensibility, deployment, full cappella.yaml |
| `sec7_testing.md` | 7. Trigger Engine Test Strategy | ✅ Draft v0.1 | Behavior matrix for schedule/manual/internal_event (v0.1) and webhook/mosaic_poll (v0.2); STARLIMS and HALO scenarios; test file map |

---

## Key Decisions (from Platform Design Sessions)

See `platform/design/INDEX.md` for full rationale and config format examples.

| Decision | Choice |
|---|---|
| Primary role | Integration and harmonization engine — the "conductor" coordinating all data sources into Hippo |
| Storage | Stateless — Hippo is the sole persistent store; Cappella owns no data |
| Hippo dependency | Required — Cappella cannot function without a Hippo instance |
| External adapter implementations | Live in Cappella (STARLIMS, HALO, REDCap, partner portals) — `ExternalSourceAdapter` ABC stays in Hippo |
| Field mapping and transformation config | Lives in Cappella adapter config — separate from Hippo's canonical schema |
| Trigger model | Unified `source` + `action` format: `webhook`, `schedule`, `mosaic_poll`, `manual`, `internal_event` |
| Action chaining | Actions emit named internal events (`emits:`); triggers subscribe with `type: internal_event` |
| Event payload | Entity IDs only — downstream actions query Hippo fresh at execution time |
| Query-fresh-at-invocation | All actions read current Hippo state at execution time; never rely on stale trigger context |
| Hippo reactive triggers (MVP) | Polling (`mosaic_poll`) — sufficient because Cappella drives most Hippo writes in normal operation |
| Hippo reactive triggers (future) | Hippo event hook plugin system — deferred |
| Idempotency (MVP) | Upsert by ExternalID — look up by source system ID, update if changed, create if absent |
| Idempotency (future) | Short-window digest deduplication for webhook retries — deferred to when live integrations are scoped |
| Out-of-order delivery | Deferred — not in MVP scope |
| Operational audit (MVP) | Structured JSON logs per trigger execution (run_id, trigger, adapter, status, entity counts, errors) |
| Operational audit (future) | `SyncRun` entities in Hippo — log schema mirrors Hippo entity shape for easy migration |
| Conditional triggers | `when:` CEL condition on trigger source — same expression language as validators |
| Tooling | `cappella trigger explain <name>` — shows full trigger chain, subscriptions, conditions |
| Artifact resolution | Delegated entirely to Canon — Cappella calls `canon.resolve(entity_type, params)` for per-sample/per-artifact work; Canon handles REUSE/FETCH/BUILD/FAIL internally |
| Workflow execution | NOT Cappella's concern — Canon handles all CWL execution; Cappella calls `canon.resolve()` for per-artifact work |
| Aggregate analysis | NOT Cappella's concern — Composer receives `HarmonizedCollection` and runs aggregate steps (DESeq2, CountsMatrix merge, etc.) |
| HarmonizedCollection | Cappella's primary output — resolved/unresolved entities with URIs, Canon decisions, and provenance in structured JSON |
| Canon relationship | Canon is Cappella's artifact resolution engine, NOT an external data source adapter. Structurally different from STARLIMS/REDCap adapters. |
| Partial failure | Never abort; collect unresolved items with structured reasons; caller decides acceptability |
| Generic adapters | CSVAdapter, JSONAdapter, XMLAdapter, SQLAdapter bundled in core — config-driven field/vocab mapping; SQLAdapter uses SQLAlchemy, query in config; covers most use cases without custom code |
| Custom adapter plugins | cappella.adapters entry points; handle complex auth/pagination/protocols; field mapping in code |
| Field mapping | In adapter config (for generic adapters) or adapter code (for custom plugins); not in cappella.yaml |
| Vocabulary normalization | In adapter config (for generic adapters) or adapter code (for custom plugins); not in cappella.yaml |
| Schema-driven traversal | Entity graph traversal inferred from Hippo schema references declarations; fallback to explicit paths in cappella.yaml for v0.1 |
| Canon transport (v0.1) | In-process (import canon directly); HTTP mode available for distributed deployment |
| Resolution API | Always async — POST /resolve validates immediately (400/422/202); client polls GET /resolve/{run_id}; CLI blocks with progress display; live samples_resolved counter for Aperture/Composer |
| CLI | In scope for v0.1 — cappella resolve/ingest/trigger/status/findings |
| Workflow executor strategy | **Resolved** — Canon owns per-artifact CWL execution; Cappella delegates to `canon.resolve()` |

---

## Open Questions

| Question | Priority | Notes |
|---|---|---|
| Workflow executor strategy | ~~High~~ **Resolved** | Canon owns per-artifact CWL execution. Cappella delegates artifact resolution to `canon.resolve()`. For v0.1 aggregate/cohort-level analyses (multi-sample inputs), Cappella invokes Canon's `CWLExecutorAdapter` directly and ingests results via `OutputIngestionPipeline`. Cappella does NOT wrap Nextflow/Snakemake — it reuses Canon's executor adapter layer. Aggregate Canon rules (v0.3) will eventually replace direct Cappella CWL execution. |
| Cappella adapter config format | **Resolved ✅** | Adapter config format is finalized and implemented in v0.1. Each built-in adapter (CSV, JSON, XML, SQL) accepts `entity_type`, `external_id_field`, `field_map`, `vocabulary_map`, `trust_level`, and adapter-specific fields (`source`, `url`, `records_path`, `records_xpath`, `connection_string`, `query`, `incremental_query`) via a flat `config:` dict in `cappella.yaml`. Vocabulary normalization and field renaming are handled at the adapter level. Custom adapters implement their own config parsing. See `sec3_adapters.md` for full reference. |
| Idempotency for live synchronous integrations | High (deferred) | Full design when live integrations are scoped: webhook digest deduplication, out-of-order delivery, source timestamp handling. ExternalID upsert is the stable foundation. |
| Execution backend model | Medium | Local process vs. queue-backed worker vs. HPC submission. Must scale from laptop to cloud without code changes — consistent with Hippo's deployment tier model. |
| Trigger failure handling | Medium | Retry logic, dead-letter queue, alerting strategy for failed trigger executions. |

---

> ✅ User docs have been updated to align with the v0.1 design and implementation. See `cappella/docs/` for the current documentation.
