# Canon — Design Notes
*Living document — last updated 2026-03-20*

---

## What Canon Is

Canon is the **semantic dependency resolver and workflow orchestrator** for DataHelix. It sits
between a metadata database (Hippo) and one or more workflow executors (Nextflow, Snakemake,
Cromwell, etc.), providing:

1. **Semantic resolution**: given a metadata specification for a desired output, find
   existing Hippo entities that satisfy it (REUSE) or determine what production rules
   can derive them (BUILD)
2. **Execution delegation**: translate the resolved plan into the native format of the
   configured executor adapter and submit it
3. **Output ingestion**: after execution, ingest produced entities back into Hippo with
   full provenance linkage

Canon does NOT implement workflow execution, HPC submission, retry logic, container
management, or environment configuration — those are the executor's job.

---

## Settled Design Decisions

### Component boundaries

| Decision | Choice |
|---|---|
| Canon's role | Semantic planner/resolver + thin orchestration layer. NOT a workflow manager. |
| Execution | Fully delegated to executor adapters (Nextflow, Snakemake, Cromwell, LocalProcess) |
| Storage | Stateless — Hippo is the sole persistent store. Canon has ephemeral local run state only (`~/.canon/runs.db`, rebuildable from Hippo) |
| Hippo dependency | Required — Canon cannot function without a Hippo instance |
| Relationship to Cappella | Peers that communicate through Hippo. Canon writes WorkflowRun + output entities; Cappella can trigger on them via `mosaic_poll`. No direct coupling. |
| Name | **Canon** — fits music theme, means "rule", canonical form (melody derived from itself) maps to files derived from files |

### The semantic dependency graph

Canon operates on **Hippo entities**, not file paths. A "target" is any entity type with
a metadata specification. The engine asks: does a Hippo entity matching this spec already
exist? If yes, reuse it. If no, find a production rule that can derive it and recurse on
its inputs.

### Production rules

Rules are declared in `canon_rules.yaml`. Each rule:
- Declares what it **produces** (entity type + metadata spec with wildcards)
- Declares what it **requires** (input entities resolved from Hippo, with named bindings)
- Declares how to **execute** (workflow identifier + input bindings + output spec)

Wildcards (`{genome_build}`, `{sample_id}`) are bound at plan time from the request
specification or resolved from required input entities.

```yaml
rule: align_reads
produces:
  entity_type: AlignmentFile
  metadata:
    aligner: STAR
    aligner_version: "2.7.11a"
    genome_build: "{genome_build}"
    ensembl_release: "{ensembl_release}"
    sample_id: "{sample_id}"
requires:
  - bind: fastq_r1
    entity_type: FastqFile
    metadata:
      sample_id: "{sample_id}"
      read: "R1"
  - bind: star_index
    entity_type: StarIndex
    metadata:
      genome_build: "{genome_build}"
      ensembl_release: "{ensembl_release}"
execute:
  workflow: pipelines/star_align     # adapter-resolved, no extension
  inputs:
    fastq_r1: "{fastq_r1.uri}"
    star_index: "{star_index.uri}"
    genome_build: "{genome_build}"
  outputs:
    - bind: bam
      entity_type: AlignmentFile
      pattern: "*.bam"
```

### Value resolution

Inputs to workflows are resolved via typed resolvers:

| Resolver | Syntax | Returns |
|---|---|---|
| URI | `{binding.uri}` | Physical location (s3, file, https, drs URI) |
| Field | `{binding.field_name}` | Specific field value from the entity |
| Inline | static value in rule | Constant — no entity lookup |
| JSON | `{binding.json}` | Full entity serialized as JSON |

Outputs are entity payloads — the workflow emits a `canon_outputs.json` (Hippo ingest
format) that Canon ingests after execution. This is NOT a new format — it's exactly the
existing Hippo batch ingest payload.

### Metadata identity — MVP

**Exact match only for v0.1.** If a request is underspecified (missing required wildcard
bindings), Canon raises a planning error before any execution. No implicit defaults,
no compatibility inference.

**v0.2**: CEL-based `satisfies:` predicates on rules for explicit opt-in compatibility
ranges. Always opt-in — a file never satisfies a request unless its rule declares it can.

### Partial specification handling

Three mechanisms (all v0.1 scope):
1. **Required vs optional wildcards** — required wildcards without a binding = planning error; optional wildcards have declared defaults (recorded in provenance)
2. **Named profiles** (`profiles.yaml`) — bind common parameter sets; `canon run --profile hg38_star_ensembl111`
3. **`foreach` construct** — drive requests from a Hippo query: "produce AlignmentFile for every Sample matching `diagnosis=AD`"

### Executor adapter contract

```python
class WorkflowExecutorAdapter(ABC):
    def render(self, task: CanonTask) -> ExecutorInputs:
        """Translate Canon task → executor-native inputs."""
    def submit(self, inputs: ExecutorInputs) -> RunHandle:
        """Submit to executor. Returns polling handle."""
    def poll(self, handle: RunHandle) -> RunStatus:
        """Check run status: RUNNING / SUCCEEDED / FAILED."""
    def collect_outputs(self, handle: RunHandle) -> Path:
        """Return path to canon_outputs.json after success."""
```

Adapter resolves `workflow: pipelines/star_align` to its native file:
- Nextflow → `pipelines/star_align.nf`
- Snakemake → rule `star_align` in `Snakefile`
- Cromwell → `pipelines/star_align.wdl`
- LocalProcess → `pipelines/star_align.sh`

Built-in adapters v0.1: `LocalProcessAdapter`, `ContainerAdapter`
Built-in adapters v0.2: `NextflowAdapter`, `SnakemakeAdapter`, `CromwellAdapter`
Plugin adapters: Python entry point group `canon.executor_adapters`

### Convention Canon imposes on workflows

Minimal. Workflows must:
1. Accept named parameters (Nextflow params, Snakemake config, WDL inputs) — Canon passes all `execute.inputs` bindings as named params
2. Write `$CANON_WORK_DIR/.canon_outputs.json` on success — standard Hippo ingest payload describing produced entities

That's it. No restructuring of existing pipelines required.

### Outputs are Hippo entities, not files

Canon operates on any Hippo entity type. A `DifferentialExpressionResult` with only
scalar fields (n_significant, padj_threshold) is a valid Canon output. A `DataFile`
with a `uri` field is also a valid Canon output. The entity model handles both uniformly.

### Federation scope

- **v0.1**: single-org, local URIs (s3, file, https)
- **v0.2**: DRS client — Canon can resolve `drs://` URIs from configured remote endpoints
- **v0.3/Bridge**: federated metadata query across DataHelix instances

---

## DRS in Hippo (settled)

### Every entity is resolvable

Every Hippo entity is resolvable to JSON via its REST endpoint. File-bearing entities
are additionally resolvable to physical bytes via their `uri` field. DRS makes both
available via a standard interface.

DRS URI for any entity: `drs://{hippo_host}/{entity_id}` — computed, never stored.

### `uri` is schema-declared, not a system field

Entity types that represent physical artifacts declare a `uri` field (type: `uri`) in
their schema. Pure-metadata entity types (DESeq results, QC summaries) need no `uri`
field. DRS works for both — pure-metadata entities simply have no `access_methods`.

### DRS implementation

Built into `hippo serve` as a router, enabled by config:

```yaml
# hippo.yaml
drs:
  enabled: true
  base_url: "https://datahelix.brainbank-a.org"
  auth: bearer          # passport_visa deferred to v0.3
  public: false
```

Two DRS endpoints added to the existing FastAPI app:
- `GET /ga4gh/drs/v1/objects/{entity_id}` → DRS object (metadata + access methods)
- `GET /ga4gh/drs/v1/objects/{entity_id}/access/{access_id}` → access URL

Can be split into a separate sidecar process later (for public-facing deployments with
different auth policy) — the router isolation makes this a config-level change.

### Passport/Visa auth

Deferred to v0.3 (multi-institution federation). Not needed for single-institution
deployments. Bearer token auth is sufficient for v0.1 DRS.

---

## Open Questions (remaining)

| Question | Priority | Notes |
|---|---|---|
| Production rule output cardinality | Medium | Single primary output + optional secondary outputs? Rules that naturally produce multiple peer outputs (BAM + BAI + log)? |
| Parallel execution of foreach targets | Medium | Parallel by default with `--concurrency N`? Sequential option for debugging? |
| Canon's ephemeral run state schema | Low | What does `~/.canon/runs.db` need to track for in-flight runs? |
| Sidecar format ownership | Low | Keep as internal Canon convention for now; evaluate standardizing if community adoption warrants it |
| Which entity types get `uri` field in the omics example schema | Medium | DataFile yes; StarIndex yes; DESeqResult no — need to walk through Appendix A entity types |

---

## v0.1 MVP Scope

**CLI:**
- `canon plan [request]` — dry run, show REUSE vs BUILD
- `canon run [request]` — execute plan
- `canon status` — show running/completed/failed runs
- `canon rules` — list/validate production rules

**Built-in executors:** LocalProcess, Container (Docker/Singularity)

**Adapters v0.2:** Nextflow, Snakemake, Cromwell

**Not in v0.1:** profiles (v0.2), foreach/query-driven requests (v0.2), DRS server (v0.2), federation (v0.3)

