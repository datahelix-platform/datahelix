# Canon — Design Specification Index

**Codename:** Canon  
**Component:** Semantic Artifact Resolver  
**Version:** 0.2-draft  
**Last updated:** 2026-03-24

---

## Document Map

| File | Section | Status | Notes |
|---|---|---|---|
| `sec1_overview.md` | 1. Overview & Scope | ✅ Draft complete | |
| `sec2_architecture.md` | 2. Architecture | ✅ Draft complete | |
| `sec3_rules_dsl.md` | 3. Canon Rules DSL | ✅ Draft complete | |
| `sec3b_cwl_integration.md` | 3b. CWL Integration | ✅ Draft complete | |
| `sec4_resolution_algorithm.md` | 4. Resolution Algorithm | ✅ Draft complete | |
| `sec5_executor_adapters.md` | 5. Executor Adapters | ✅ Draft complete | |
| `sec5b_storage_adapters.md` | 5b. Storage Adapters | ✅ Draft complete | v0.2 target; plugin architecture for local/S3/GCS/OSF/iRODS |
| `sec6_mosaic_integration.md` | 6. Mosaic Integration | ✅ Draft complete | |
| `sec7_nfr.md` | 7. Non-Functional Requirements | ✅ Draft complete | |
| `sec8_dynamic_rules.md` | 8. Dynamic Rule Registration & Convention Output Mapping | ✅ Draft complete | v0.2/v0.3 target |
| `reference_canon_yaml.md` | Reference: canon.yaml schema | ✅ Draft complete | |
| `reference_canon_rules_yaml.md` | Reference: canon_rules.yaml schema | ✅ Draft complete | |
| `appendix_a_rnaseq_example.md` | Appendix A: RNA-seq worked example | ✅ Draft complete | |

---

## Key Decisions Log

### Component Identity

| Decision | Choice | Rationale |
|---|---|---|
| Canon's role | Semantic artifact resolver — "give me this artifact, I'll find it or make it" | Narrow, composable, testable |
| Scope boundary | One operation: `canon get <spec>` → URI. No cohort logic, no set management. | Complexity cap; Cappella owns the set-level logic |
| Workflow language | CWL (Common Workflow Language v1.2) | Mature standard, schematic/execution separation, community tooling, visual builder ecosystem |
| Bundled adapters | `CwltoolAdapter` only — bundled in core `canon` package | cwltool is the universal baseline; all other adapters are plugins |
| Plugin adapters | All non-cwltool adapters (Toil, Nextflow, etc.) are separate installable packages: `canon-executor-toil`, `canon-executor-nextflow`, etc. | Keeps core package lean; users install only what their environment supports |
| Storage | Stateless — Hippo is the sole persistent store | Consistent with platform adapter pattern |
| Hippo dependency | Required — Canon cannot function without a Hippo instance | Canon reads registry (does this exist?) and writes results (here's what I made) |

### Resolution Model

| Decision | Choice | Rationale |
|---|---|---|
| Resolution strategy | Lazy recursive — resolve one artifact at a time, walk dependencies on demand | Simpler than upfront DAG planning; avoids building plan objects |
| Artifact identity | Entity type + parameter set, where parameters may be scalars or entity references | Maps directly to Hippo entity queries; entity refs enable graph traversal |
| Reuse check | Query Hippo before any execution | Hippo is the authoritative registry of what has been computed |
| Dependency resolution | Canon calls itself recursively for required inputs | Each `requires:` entry in a Canon rule is resolved the same way as the top-level request |
| Cycle detection | Required — Canon must detect circular rule dependencies | Prevents infinite recursion; raises `CanonCycleError` with cycle path |
| Partial specification (v0.1) | Error — all identity parameters must be fully specified | Exact match only for v0.1; ambiguity is always an error, never silently resolved |

### Entity Reference Model ("Everything is an Entity")

| Decision | Choice | Rationale |
|---|---|---|
| Parameter entity promotion | Key parameters that other entities need to reference become Hippo entities, not scalars | Enables graph traversal queries ("all alignments using STAR against GRCh38") |
| Tool / ToolVersion separation | `Tool` (base type, name + category) and `ToolVersion` (extends Tool, adds version string) as distinct Hippo entity types | Hippo single inheritance / polymorphism naturally supports this; enables "all STAR versions" queries |
| Version required | Canon rules MUST specify tool version; error if omitted | Reproducibility requires exact version — "any STAR" is ambiguous and not allowed |
| Hippo polymorphism | `ToolVersion` extends `Tool` using Hippo's `base:` inheritance | `client.query("Tool")` returns both `Tool` and `ToolVersion` entities; subtypes are fully queryable |
| Entity reference syntax in rules | `ref:EntityType{field=value, nested.field=value}` | Dot notation for traversing reference fields; resolved to Hippo UUID before lookup |
| Candidates for entity promotion | `Tool`, `ToolVersion`, `GenomeBuild`, `GeneAnnotation`, `Sample`, `Cohort` | Anything queried across multiple artifacts or needing its own metadata |
| Non-entity parameters | Scalar pipeline params (quality_cutoff, min_length, max_intron_length, etc.) stay as plain values | Entities only when other things need to point to them or query by them |

### Execution Environment and Reproducibility

| Decision | Choice | Rationale |
|---|---|---|
| Environment configuration | Lives in CWL tool definitions (`DockerRequirement`, `SoftwareRequirement`, `EnvVarRequirement`) — not in Canon rules or ToolVersion entities | CWL already handles this; no duplication; site-specific (Docker vs Singularity vs conda vs modules) |
| Reproducibility record | `WorkflowRun` entity in Hippo records: CWL file + hash, runner + version, execution environment type + digest/hash | Complete recipe for reproducing any run; harvested from CWL provenance output |
| ToolVersion entity content | Semantic identity only: tool name, version string, optional bio.tools/Bioconda links | No container/env info; that's site-specific and belongs in WorkflowRun |
| Execution environment types | docker, singularity, conda, module, local — all recorded uniformly as `execution_environment` JSON on WorkflowRun | Flexible blob; whatever CWL runner captured is recorded verbatim |

### CWL Integration

| Decision | Choice | Rationale |
|---|---|---|
| Workflow language | CWL v1.2 | Standard, tooled, schematic/execution separation |
| Canon metadata extension | Sidecar YAML (`.canon.yaml`) alongside CWL workflow file — declares Hippo entity type + identity parameters for each output | Keeps CWL files standard and valid; Canon annotation is separate |
| Tool definitions | Standard CWL `CommandLineTool` with native requirements | No Canon-specific changes to CWL tool files |
| Execution | Delegated to configured CWL runner (cwltool default; Toil, Nextflow CWL mode as plugins) | Canon never runs commands directly |

### Component Boundaries (Canon vs. Cappella)

| Concern | Owner |
|---|---|
| Which artifacts to request | Cappella |
| Cohort construction (which samples match criteria X) | Cappella |
| Parallelism across multiple artifact requests | Cappella |
| Failure handling across a batch of requests | Cappella |
| "Does this artifact exist?" | Canon |
| "How do I produce this artifact?" | Canon |
| Walking the dependency chain for a single artifact | Canon |
| Running CWL workflows | Canon (via CWL executor adapter) |
| Recording WorkflowRun provenance | Canon |
| Ingesting outputs into Hippo | Canon |

### Deferred Decisions

| Question | Priority | Notes |
|---|---|---|
| Partial specification / constraint queries | High | v0.1 requires full exact spec; CEL-based constraint predicates deferred to v0.2 |
| Aggregate/collect rules (sample sets, gather steps) | Medium | CountsMatrix use case; deferred to v0.3 — Cappella handles set logic through v0.2 |
| Snakemake/Nextflow native adapter (non-CWL) | Medium | v0.1: CWL only; native adapters as entry-point plugins in v0.2 |
| Storage adapter plugin system | High | Specified in sec5b; v0.1 has local stub + S3 warn; full plugin system in v0.2 |
| Dynamic rule registration API | High | Specified in sec8; v0.2: URL-based CWL + convention mapping; v0.3: inline CWL + array outputs |
| Convention-based CWL→Hippo output mapping | High | Specified in sec8; CWL record output field names = Hippo entity field names; `from_output` for disambiguation; replaces sidecar requirement for well-typed entities |
| Array-typed CWL outputs | Medium | Specified in sec8; `array_mode: one_per_item` creates one entity per array element; `resolve_all()` deferred to v0.3 |
| `resolve_all()` / collection query | Medium | v0.3 — `canon.resolve_all(entity_type, partial_spec)` returns all matching entities; needed for array-output workflows (clustering → N entities). For v0.1/v0.2 Composer queries Hippo directly. |
| `ProductionRuleDefinition` Hippo entity type | High | v0.2 — dynamic rules stored as Hippo entities with provenance; must be added to Canon reference schema (canon/mosaic_reference/schema.yaml) alongside Tool, ToolVersion, WorkflowRun |
| Sidecar format superseded by convention mapping | Medium | sec8 convention (CWL record output names = Hippo field names + `from_output`) replaces sidecar for well-typed single/multi-entity outputs; sidecar still valid for legacy rules but not required for dynamically registered rules |
| Visual workflow builder | Low | Use existing CWL editors (Rabix Composer, cwl-viewer) for now |
| DRS URI integration | Medium | Canon outputs get `self` URI from Hippo; DRS server in Hippo v0.2 |
| Federation / cross-lab artifact sharing | Low | Hippo DRS + Canon DRS client; deferred to v0.3 |
| ToolVersion entity pre-population | Medium | Who creates Tool/ToolVersion entities? Canon lazily on first use, or `hippo-reference-bioconda` plugin? |

---

## Open Questions

| Question | Priority | Notes |
|---|---|---|
| OQ1: Canon sidecar format | High | Exact schema of `.canon.yaml` alongside CWL workflow — how are Hippo entity type and identity params declared per output? |
| OQ2: Output ingestion after CWL run | Medium | CWL outputs are `File` objects with checksums. Canon maps them to Hippo entities using sidecar + CWL output values. Full mapping spec needed. |
| OQ3: Work directory lifecycle | Low | Where does Canon put CWL work dirs? Cleanup policy? |
| OQ4: Partial ref resolution ordering | Medium | When multiple Hippo entities match `ref:ToolVersion{tool.name=STAR}` and no version is given — confirm this is always an error in v0.1, never silent disambiguation |
| OQ5: ToolVersion entity schema | Medium | Exact fields for `Tool` and `ToolVersion` Hippo entity types — part of a Canon reference schema package or user-defined? |

### Canon Hippo Reference Schema

| Decision | Choice | Rationale |
|---|---|---|
| Canon entity schema distribution | Bundled inside `canon` package, registered via `mosaic.reference_loaders` entry point | Tightly coupled to Canon version; simplifies install; no separate package to manage |
| Install UX | `pip install canon` + `hippo reference install canon` | Standard Hippo reference loader pattern; keeps Canon and its schema in sync |
| Hippo dependency on Canon schema | Optional — Hippo users who don't use Canon don't install it | Canon schema adds no value to standalone Hippo deployments |
| Canon dependency on its schema | Required — Canon needs `Tool`, `ToolVersion`, `GenomeBuild`, `GeneAnnotation`, `WorkflowRun` in Hippo | Canon raises `CanonConfigError` at startup if these types are not found in the Hippo schema |
| Release coupling | Canon package version and its Hippo reference schema are versioned and released together | Schema changes require a new Canon release; no independent schema versioning |
| Schema location in package | `canon/mosaic_reference/` — `loader.py` (ReferenceLoader impl) + `schema.yaml` (entity type definitions) | Discoverable at `canon.mosaic_reference.loader:CanonReferenceLoader` via entry point |


### Canon Workflow Packages

| Decision | Choice | Rationale |
|---|---|---|
| Workflow sharing mechanism | Python packages on PyPI + git (pip install from GitHub) | Ubiquitous, no new registry infrastructure, familiar to Python users |
| Naming convention | `canon-workflows-<name>` (e.g. `canon-workflows-rnaseq`) | Discoverable via PyPI search; consistent namespace |
| Entry point group | `canon.workflow_packages` | Enables automatic discovery by Canon at startup |
| Hippo schema shipping | Workflow packages also register `mosaic.reference_loaders` entry point | One package provides plugins for both Canon and Hippo; standard Python entry point pattern |
| Domain entity types | Workflow package ships `schema.yaml` fragment; applied via `hippo reference install <name>` | Batteries-included install: one pip install + two CLI commands sets up everything |
| Private/lab workflows | Install from git: `pip install git+https://github.com/org/repo.git` | No PyPI publishing required; entry points work identically from git installs |
| WorkflowPackage ABC | Defined in `canon.workflows.base` — `name`, `version`, `rules()`, `workflows_dir()`, `schema()` | Same pattern as Hippo's `ReferenceLoader` ABC |
| Deferred | v0.1 ships without workflow package support; `canon.workflow_packages` entry point reserved | Core resolver and executor must be stable before packaging layer is designed |

