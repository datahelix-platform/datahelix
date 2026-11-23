## 7. Non-Functional Requirements

**Document status:** Draft v0.1  
**Depends on:** sec1_overview.md, sec2_architecture.md

---

### 7.1 Reproducibility

Reproducibility is Canon's primary non-functional requirement. Every artifact Canon
produces must be re-producible from its provenance record alone.

**Requirements:**

- Every produced artifact has a `WorkflowRun` entity in Hippo recording: CWL workflow
  file path + SHA256 hash, CWL runner name + version, execution environment type +
  image digest/hash, all input entity UUIDs, all parameters
- CWL workflow file hashes are captured at execution time — if the workflow file changes
  after execution, the hash in `WorkflowRun` still reflects what was actually run
- Container image digests are captured (not just tags) — `sha256:abc123` is reproducible;
  `latest` is not
- Canon raises `CanonRuleValidationError` at startup if any tool reference in a rule
  lacks a version — "STAR without a version" is not allowed
- All entity reference parameters are stored as Hippo UUIDs in the produced entity's
  metadata — UUIDs are stable identifiers; names can change

**Achieving reproducibility from a WorkflowRun record:**

Given a `WorkflowRun` entity, a researcher can reproduce the execution by:
1. Obtaining the CWL file at the recorded hash (from git history or a CWL registry)
2. Pulling the exact container image by digest
3. Resolving all input entity UUIDs to their current URIs
4. Running `cwltool` (or the recorded runner) with the same inputs

This is possible without Canon itself — the `WorkflowRun` is a self-contained recipe.

---

### 7.2 Idempotency

Canon's `canon get` operation is idempotent: calling it multiple times with the same
specification produces the same result without duplicating computation or storage.

**Requirements:**

- A `canon get` call that finds an existing Hippo entity always returns that entity's URI
  without running any computation
- A `canon get` call that finds an in-progress `WorkflowRun` raises `CanonExecutorError`
  rather than launching a duplicate execution
- A `canon get` call after a failed `WorkflowRun` re-runs the workflow (failed results
  are not cached)
- Two concurrent `canon get` calls for the same spec are safe: one will run and the other
  will either find the completed result (REUSE) or the in-progress run (error)

**Idempotency is not guaranteed in concurrent deployments without a distributed lock.**
In v0.1, Canon relies on Hippo's atomic write semantics for single-instance deployments.
Multi-instance Canon deployments (e.g. two Cappella workers calling Canon in parallel for
the same spec) may produce duplicate executions. Distributed locking is deferred to v0.2.

---

### 7.3 Correctness

Canon must never silently return an artifact that does not match the requested specification.

**Requirements:**

- All field comparisons in Hippo queries are exact match — Canon never uses fuzzy matching
  or range queries in v0.1
- Entity reference resolution raises `CanonResolutionError` on zero matches or multiple
  matches — Canon never silently picks one from many
- Tool version is always required in rules — Canon never resolves "any STAR" to a
  specific version without explicit declaration
- The `unpropagated wildcard` validation at startup ensures upstream parameters are
  always preserved in produced artifact metadata — Canon never silently drops provenance
- Sidecar `identity_fields` are validated against the rule's `produces.match` at startup —
  a mismatch between what Canon queries and what it stores is a startup error

---

### 7.4 Observability

Canon provides sufficient visibility into its operations for debugging and monitoring.

**Requirements:**

- `canon plan` provides a dry-run view of the full REUSE/BUILD decision tree before
  any execution
- `canon status` shows recent `WorkflowRun` entities from Hippo (running, completed,
  failed) with timing information
- All Canon operations are logged at configurable levels (`DEBUG`, `INFO`, `WARNING`,
  `ERROR`) to stderr
- `DEBUG` logging includes: Hippo queries + response times, rule matching decisions,
  wildcard bindings, entity ref resolutions
- `INFO` logging includes: REUSE/BUILD decisions, CWL execution start/end, ingestion
  confirmation
- CWL runner stderr is captured in `WorkflowRun.stderr` (truncated to 64KB) for
  post-execution debugging
- Failed `WorkflowRun` entities in Hippo are queryable — `canon status --failed` shows
  all failures

---

### 7.5 Performance

Canon is not a high-throughput system. Its performance envelope is appropriate for
research workloads, not real-time services.

**Targets:**

| Operation | Target latency | Notes |
|---|---|---|
| REUSE (Hippo query hit) | < 500ms | Dominated by Hippo network roundtrip |
| Entity ref resolution | < 200ms per ref | One Hippo query per `ref:T{...}` expression |
| Rule matching | < 10ms | In-memory after startup |
| CWL execution | Minutes to hours | Determined by the workflow, not Canon |
| Canon startup (rule validation) | < 5s for 100 rules | CWL file validation + Hippo schema check |

**Canon does not cache Hippo query results within a single `canon get` call.** Each
entity ref and each registry lookup is a fresh Hippo query. This ensures correctness —
the registry may have been updated by another process between queries — at the cost of
additional network roundtrips. Caching may be added in v0.2 with a configurable TTL.

**Sequential input resolution in v0.1.** Required inputs are resolved one at a time
in the order declared in `requires:`. Parallel resolution (resolving independent inputs
concurrently) is deferred to v0.2. For most pipelines with 2–4 inputs per rule, the
overhead is negligible compared to CWL execution time.

---

### 7.6 Security

Canon inherits Hippo's security model for all data access.

**Requirements:**

- The `mosaic_token` in `canon.yaml` must have read+write access to all entity types
  used by Canon rules — Canon does not perform partial-permission graceful degradation
- `canon.yaml` should not be committed to version control if it contains credentials —
  use environment variable substitution: `mosaic_token: "${MOSAIC_TOKEN}"`
- Canon does not execute arbitrary code from canon_rules.yaml — rules are data, not
  code; wildcard values are never evaluated as expressions
- CWL `ExpressionTool` (JavaScript) is supported but discouraged — JavaScript execution
  in CWL steps is outside Canon's security perimeter; restrict with `cwltool_options:
  ["--disable-ext"]` if needed
- Staging directory (`work_dir/staging`) should be on a filesystem inaccessible to
  other users if input data is sensitive
- Canon does not implement authentication beyond forwarding `mosaic_token` — access
  control for produced artifacts is Hippo's responsibility

---

### 7.7 Deployment and Operations

**Requirements:**

- Canon runs on any system with Python 3.11+ and Docker (or another container runtime)
- No server process required for local use — `canon get` is a CLI command that runs
  and exits
- Single `canon.yaml` per working directory — supports multiple Canon configurations
  for different Hippo deployments or rule sets by running from different directories
- Canon is stateless except for ephemeral CWL work directories and the optional
  `~/.canon/runs.db` SQLite database for `canon status` (rebuildable from Hippo)
- `canon rules validate` should be run in CI/CD alongside CWL file changes to catch
  rule errors before deployment
- Canon version and the Canon Hippo reference schema version are always identical —
  upgrading Canon requires re-running `hippo reference install canon` to apply any
  schema changes

---

### 7.8 Extensibility

Canon is designed to be extended without modifying the core package.

**Extension points:**

| Extension point | Mechanism | Example |
|---|---|---|
| New CWL executor backend | `canon.executor_adapters` entry point | `canon-executor-toil` |
| Community workflow packages | `canon.workflow_packages` entry point | `canon-workflows-rnaseq` |
| Domain entity types | `mosaic.reference_loaders` entry point | bundled in workflow packages |
| Custom Canon entity types | `mosaic.reference_loaders` entry point | lab-specific entity extensions |

All extension points use standard Python entry points — no Canon-specific plugin API
or registration step beyond `pip install`.

---

### 7.9 Versioning and Compatibility

- Canon follows semantic versioning (semver)
- The Canon Hippo reference schema version always matches the Canon package version
- Breaking changes to `canon_rules.yaml` syntax increment the major version
- CWL v1.2 is the minimum supported version — older CWL files are not supported
- Canon guarantees that existing rules continue to work across minor version upgrades
- The `WorkflowRun` entity schema is stable within a major version — fields may be
  added (additive) but not renamed or removed within a major release
