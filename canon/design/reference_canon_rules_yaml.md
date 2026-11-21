# Canon Rules Reference: `canon_rules.yaml` and `.canon.yaml` Sidecars

**Document status:** Draft v0.1
**Depends on:** sec3_rules_dsl.md, sec3b_cwl_integration.md, sec2_architecture.md

---

## Overview

Canon's knowledge of how to produce artifacts is declared in two YAML formats:

- **`canon_rules.yaml`** — the rule registry: maps artifact specifications to CWL workflows. One file per Canon project, path configurable via `rules_file` in `canon.yaml`.
- **`<workflow>.canon.yaml`** — per-workflow sidecar: maps CWL outputs to Hippo entities. One file per CWL workflow referenced in the rules.

Both formats are human-authored YAML, validated at Canon startup, and versioned in source control alongside the CWL workflow files.

---

## Part 1: `canon_rules.yaml`

### Top-Level Structure

```yaml
rules:
  - <rule>
  - <rule>
  ...
```

`rules` is the only top-level key. It contains a list of rule objects. There is no metadata header, version field, or other top-level keys. The list may be empty (Canon starts with no rules and no error), but a non-list value raises `CanonRuleValidationError`.

---

### Rule Object

Each rule is a YAML mapping with the following fields:

| Field | Type | Required | Default |
|---|---|---|---|
| `name` | `string` | Yes | — |
| `description` | `string` | No | — |
| `produces` | `mapping` | Yes | — |
| `requires` | `list[mapping]` | No | `[]` |
| `execute` | `mapping` | Yes | — |

---

#### `name`

**Type:** `string`
**Required:** Yes

Unique identifier for this rule within the rules file. Used in error messages, `canon rules list` output, `WorkflowRun.rule_name` provenance records, and the `canon rules validate --rule <name>` command.

**Convention:** `snake_case` verb phrase describing the transformation.

```yaml
name: trim_reads
name: build_star_index
name: align_reads
name: count_genes
```

**Validation:** duplicate rule names raise `CanonRuleValidationError: duplicate rule name '{name}'`.

---

#### `description`

**Type:** `string`
**Required:** No

Human-readable description of what this rule does. Shown in `canon rules list` output and error messages. Has no effect on rule matching.

```yaml
description: Align trimmed reads to a reference genome using STAR
```

---

#### `produces`

**Type:** `mapping`
**Required:** Yes

Declares what artifact this rule produces. Used for rule matching: when Canon needs an entity of `produces.entity_type` with parameters matching `produces.match`, this rule is a candidate.

| Field | Type | Required | Description |
|---|---|---|---|
| `entity_type` | `string` | Yes | Hippo entity type this rule produces |
| `match` | `mapping` | Yes | Parameter set that identifies this artifact |

```yaml
produces:
  entity_type: AlignmentFile
  match:
    sample: "{sample}"
    genome_build: "ref:GenomeBuild{name={genome_build}}"
    aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
    quality_cutoff: "{quality_cutoff}"
    min_length: "{min_length}"
```

**`produces.entity_type`**

Must be a valid Hippo entity type name (`PascalCase`). Canon verifies at startup that this type exists in the connected Hippo instance's schema. Domain entity types (`AlignmentFile`, `FastqFile`, etc.) are defined in your Hippo schema configuration; Canon's own entity types (`Tool`, `ToolVersion`, etc.) are defined in the Canon reference schema.

**`produces.match`**

A mapping from parameter names to parameter values. Values may be:
- **Scalar** — a plain string, integer, float, or boolean
- **Entity reference** — `ref:EntityType{...}` (see [Entity Reference Syntax](#entity-reference-syntax))
- **Wildcard** — `{name}` (see [Wildcards](#wildcards))
- **Wildcard inside entity reference** — `ref:EntityType{field={wildcard}}`

The `match` block is the complete parameter set stored on the produced Hippo entity. All parameters that should be queryable (including upstream provenance parameters) must appear here — they do not propagate automatically from upstream rules.

**Validation:** duplicate `produces` specs (same `entity_type` + same `match`) across rules raises `CanonRuleValidationError: ambiguous produces`.

---

#### `requires`

**Type:** `list[mapping]`
**Required:** No
**Default:** `[]`

A list of input artifacts that must be resolved before this rule can execute. Each entry is resolved by a recursive `canon get` call — it may REUSE an existing artifact or trigger a further BUILD.

Each entry in `requires` is a mapping with:

| Field | Type | Required | Description |
|---|---|---|---|
| `bind` | `string` | Yes | Name for this input — used in `execute.inputs` expressions |
| `entity_type` | `string` | Yes | Hippo entity type to resolve |
| `match` | `mapping` | Yes | Parameters identifying the required input |

```yaml
requires:
  - bind: trimmed_fastq
    entity_type: TrimmedFastqFile
    match:
      sample: "{sample}"
      trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
      quality_cutoff: "{quality_cutoff}"
      min_length: "{min_length}"
  - bind: genome_index
    entity_type: StarIndex
    match:
      genome_build: "ref:GenomeBuild{name={genome_build}}"
      aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
```

**`requires[].bind`**

A `snake_case` identifier. Bound input values are accessible in `execute.inputs` expressions as `{bind_name.field}`. For example, `bind: trimmed_fastq` → `{trimmed_fastq.uri}` in `execute.inputs`.

**`requires[].entity_type`**

Same semantics as `produces.entity_type`.

**`requires[].match`**

Same semantics as `produces.match` — scalars, entity references, and wildcards. Wildcards here must appear in `produces.match` (see [Wildcard Propagation Rule](#wildcard-propagation-rule)).

**Resolution order:** required inputs are resolved sequentially in the order they appear in the list. In v0.1, Canon does not parallelize input resolution.

---

#### `execute`

**Type:** `mapping`
**Required:** Yes

Declares how to run the CWL workflow that produces this artifact.

| Field | Type | Required | Description |
|---|---|---|---|
| `workflow` | `string` | Yes | Path to the CWL workflow file |
| `inputs` | `mapping` | Yes | CWL workflow input → value mappings |

```yaml
execute:
  workflow: workflows/star_align.cwl
  inputs:
    fastq: "{trimmed_fastq.uri}"
    genome_index: "{genome_index.uri}"
    genome_build: "{genome_build}"
    aligner: "{aligner}"
    quality_cutoff: "{quality_cutoff}"
    min_length: "{min_length}"
    sample_id: "{sample.id}"
```

**`execute.workflow`**

Path to the CWL workflow file. Relative paths are resolved relative to `canon_rules.yaml`. Must point to a CWL `Workflow` (not a bare `CommandLineTool`). A companion `.canon.yaml` sidecar must exist in the same directory.

```yaml
workflow: workflows/star_align.cwl        # relative to canon_rules.yaml
workflow: /abs/path/to/star_align.cwl     # absolute path
```

**Validation:**
- File must exist at startup
- Must be a valid YAML file
- `cwlVersion` must be `v1.2`
- `class` must be `Workflow`
- A `.canon.yaml` sidecar must exist alongside it

**`execute.inputs`**

Maps CWL workflow input names to values. Keys are the `inputs:` identifiers declared in the CWL workflow file. Every input declared in the CWL workflow must have a corresponding key here (Canon validates this at startup).

Values are [input value expressions](#input-value-expressions).

---

## Part 2: Parameter Types

### Scalar Parameters

Plain YAML values — strings, integers, floats, or booleans:

```yaml
quality_cutoff: 20
min_length: 30
strand_specific: true
max_intron_length: 500000
mode: "paired"
```

Scalars are matched exactly against Hippo entity fields. They are stored as-is on the produced Hippo entity. YAML type is preserved (integer `20` ≠ string `"20"`).

---

### Entity References

Pointers to Hippo entities. An entity reference is resolved to a Hippo UUID before any lookup or execution.

**Syntax:**

```
ref:<EntityType>{<field>=<value>[, <field>=<value>...]}
```

```yaml
genome_build: "ref:GenomeBuild{name=GRCh38}"
aligner: "ref:ToolVersion{tool.name=STAR, version=2.7.11a}"
annotation: "ref:GeneAnnotation{source=GENCODE, version=43}"
sample: "ref:Sample{id=AD001}"
```

Entity reference strings must be quoted in YAML (the `{` and `}` characters require quoting).

**See:** [Entity Reference Syntax](#entity-reference-syntax) for the full reference.

---

### Wildcards

Parameters whose values are supplied at resolution time (not hard-coded in the rule). Written as `{name}` where `name` is the wildcard identifier.

```yaml
sample: "{sample}"
quality_cutoff: "{quality_cutoff}"
genome_build: "{genome_build}"    # plain wildcard — scalar value
```

Wildcard names are `snake_case`. The same name in `produces.match` and `requires[].match` creates a binding — the value is automatically threaded through from the top-level request.

Wildcards may also appear inside entity reference expressions:

```yaml
aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
genome_build: "ref:GenomeBuild{name={genome_build}}"
```

**See:** [Wildcard Propagation Rule](#wildcard-propagation-rule) for the mandatory propagation requirement.

---

## Part 3: Entity Reference Syntax

### Full Syntax

```
ref:<EntityType>{<field>=<value>[, <field>=<value>...]}
```

- `<EntityType>` — `PascalCase` Hippo entity type name
- `<field>=<value>` — comma-separated field constraints
- Field names are case-sensitive
- Values are literal strings (no quoting needed inside the braces)
- Whitespace around `=` and `,` is ignored

### Dot-Notation Field Traversal

Dot notation traverses reference fields to access fields on a related entity:

```yaml
# Follow the 'tool' reference field on ToolVersion, then match 'name' on Tool
aligner: "ref:ToolVersion{tool.name=STAR, version=2.7.11a}"

# Follow annotation → GeneAnnotation, then match source and version
gtf: "ref:GeneAnnotationFile{annotation.source=GENCODE, annotation.version=43}"
```

`tool.name=STAR` is implemented as a Hippo JOIN query: find `ToolVersion` entities whose `tool` reference field points to a `Tool` entity with `name=STAR`. This is not a client-side filter.

**Maximum traversal depth:** 3 levels. Deeper paths raise `CanonResolutionError: dot-notation traversal exceeds maximum depth (3)`.

### Wildcards Inside Entity References

Field values inside a `ref:` expression may be wildcards:

```yaml
# genome_build wildcard inside an entity ref field
genome_build: "ref:GenomeBuild{name={genome_build}}"

# Multiple wildcards in one ref
aligner: "ref:ToolVersion{tool.name={aligner_name}, version={aligner_version}}"

# Mixed literal and wildcard fields
aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
```

Wildcards inside refs are substituted from the request spec before the entity lookup. If the wildcard is not bound, Canon raises `CanonPlanningError: unbound wildcard '{name}'`.

### Resolution Rules

1. All literal field values must match exactly (case-sensitive, exact string)
2. Wildcard fields are substituted from the request spec before resolution
3. Dot-notation traversal is implemented as Hippo JOIN queries, not client-side filters
4. Zero matches → `CanonResolutionError: no {EntityType} entity found matching {constraints}`
5. Multiple matches → `CanonResolutionError: ambiguous reference — {n} {EntityType} entities match {constraints}. Provide additional fields to disambiguate`
6. The resolved UUID is used for all subsequent Hippo queries and stored on produced entities

---

## Part 4: Wildcards

### Wildcard Syntax

`{name}` — a single identifier in curly braces. No spaces inside the braces.

```yaml
sample: "{sample}"
quality_cutoff: "{quality_cutoff}"
star_version: "{star_version}"
```

Wildcard names are `snake_case`. They are bound when Canon evaluates a request — the value comes from the `--param` arguments to `canon get` or the parameters passed programmatically.

### Wildcard Propagation Rule

**Any wildcard that appears in a `requires[].match` block must also appear in `produces.match`.**

This rule enforces complete provenance declaration. If a `requires` input is parameterized by `{quality_cutoff}`, the produced artifact must also declare `quality_cutoff` in its identity — otherwise the produced entity's metadata would silently omit an upstream parameter that distinguishes it from other artifacts.

```yaml
# CORRECT — quality_cutoff appears in both produces.match and requires[].match
produces:
  entity_type: AlignmentFile
  match:
    sample: "{sample}"
    quality_cutoff: "{quality_cutoff}"   # ← declared here

requires:
  - bind: trimmed_fastq
    entity_type: TrimmedFastqFile
    match:
      sample: "{sample}"
      quality_cutoff: "{quality_cutoff}" # ← used here — valid because declared in produces
```

```yaml
# INVALID — quality_cutoff used in requires but missing from produces
produces:
  entity_type: AlignmentFile
  match:
    sample: "{sample}"
    # quality_cutoff is NOT here — startup error

requires:
  - bind: trimmed_fastq
    entity_type: TrimmedFastqFile
    match:
      sample: "{sample}"
      quality_cutoff: "{quality_cutoff}"  # ← unpropagated wildcard
```

**Violation:** `CanonRuleValidationError: unpropagated wildcard '{quality_cutoff}' in rule '{name}' requires[0].match — must appear in produces.match`

---

## Part 5: Input Value Expressions

The `execute.inputs` mapping uses expressions to compute the concrete values passed to `inputs.json` for the CWL workflow. Expressions are `snake_case` identifiers in curly braces.

### Expression Types

**Bound input field** — access a field on a resolved required input entity:

```yaml
inputs:
  fastq: "{trimmed_fastq.uri}"          # uri field on TrimmedFastqFile entity
  read_count: "{raw_fastq.read_count}"  # scalar field on resolved entity
  genome_index: "{genome_index.uri}"    # uri field on StarIndex entity
```

The part before `.` must be a `bind` name from `requires`. The part after `.` is a field name on the resolved Hippo entity (typically `uri`, but any entity field is valid).

**Scalar wildcard** — pass a wildcard value directly to CWL:

```yaml
inputs:
  quality_cutoff: "{quality_cutoff}"
  strand_specific: "{strand_specific}"
  min_length: "{min_length}"
```

**Entity reference field** — access a field on a resolved entity reference from `produces.match`:

```yaml
inputs:
  genome_name: "{genome_build.name}"    # genome_build was ref:GenomeBuild{name={genome_build}}
  aligner_version: "{aligner.version}"  # aligner was ref:ToolVersion{...}
  sample_id: "{sample.id}"              # sample was ref:Sample{id={sample}}
```

These expressions follow the reference to the resolved Hippo entity and extract the named field.

**Static value** — a literal string or number with no `{...}` expression:

```yaml
inputs:
  output_format: "BAM"
  sort_order: "coordinate"
  threads: 8
```

### Expression Evaluation Order

1. Wildcards are bound from the request spec
2. Entity references in `produces.match` and `requires[].match` are resolved to UUIDs
3. Required inputs are resolved (recursive `canon get`) → bound by `bind` name
4. `execute.inputs` expressions are evaluated left-to-right
5. The resulting dict is written to `inputs.json` and passed to the CWL executor

### CWL Type Mapping

Canon maps bound values to CWL input types as follows:

| Expression result | CWL type | `inputs.json` representation |
|---|---|---|
| Hippo entity `uri` (file URI, S3 URI, DRS URI) | `File` | `{"class": "File", "location": "<uri>"}` |
| Hippo entity `uri` (directory URI) | `Directory` | `{"class": "Directory", "location": "<uri>"}` |
| Scalar string | `string` | `"value"` |
| Scalar integer | `int` | `20` |
| Scalar float | `float` | `0.05` |
| Scalar boolean | `boolean` | `true` |
| Hippo entity UUID (passthrough) | `string` | `"uuid:..."` |

Canon infers `File` vs. `Directory` from the CWL workflow's declared input type for that parameter. The workflow's input declaration is authoritative.

**Validation:** `CanonRuleValidationError: unknown binding '{name}' in execute.inputs — '{name}' is not a wildcard or requires bind name`

---

## Part 6: `.canon.yaml` Sidecar Format

Every CWL workflow referenced in `canon_rules.yaml` must have a companion `.canon.yaml` sidecar file in the same directory. The sidecar declares which Hippo entities the CWL workflow's outputs map to and how CWL output values become Hippo entity fields.

The sidecar keeps CWL files entirely standard — no Canon-specific extensions to the CWL format itself.

### Sidecar File Naming and Location

The sidecar must be named by replacing `.cwl` with `.canon.yaml`:

```
workflows/
  star_align.cwl           → star_align.canon.yaml (required)
  cutadapt.cwl             → cutadapt.canon.yaml   (required)
  htseq_count.cwl          → htseq_count.canon.yaml (required)
```

### Top-Level Structure

```yaml
outputs:
  <cwl_output_name>:
    entity_type: <string>
    identity_fields:
      - <field>
    mosaic_fields:
      <mosaic_field>: <expression>
    optional: <bool>
```

The only top-level key is `outputs`. It is a mapping from CWL output names (as declared in the CWL workflow's `outputs:` block) to output descriptor objects.

---

### `outputs.<name>.entity_type`

**Type:** `string`
**Required:** Yes

The Hippo entity type that this CWL output maps to. Must be a valid Hippo entity type name.

```yaml
outputs:
  bam:
    entity_type: AlignmentFile
```

---

### `outputs.<name>.identity_fields`

**Type:** `list[string]`
**Required:** Yes

The subset of `mosaic_fields` that uniquely identify this artifact. These fields are used by Canon for the registry lookup query in Phase 2 of the resolution algorithm. Every field listed here must appear in `mosaic_fields`.

Identity fields should match the parameters in the corresponding rule's `produces.match` block.

```yaml
identity_fields:
  - sample
  - genome_build
  - aligner
  - quality_cutoff
  - min_length
```

**Validation:** every `identity_field` must be present in `mosaic_fields` — `CanonRuleValidationError: identity_field '{field}' is not declared in mosaic_fields`.

---

### `outputs.<name>.mosaic_fields`

**Type:** `mapping`
**Required:** Yes

Maps Hippo entity field names to expressions that compute their values from the CWL execution context. See [Sidecar Expression Syntax](#sidecar-expression-syntax) below.

```yaml
mosaic_fields:
  uri: "{outputs.bam.location}"
  file_size_bytes: "{outputs.bam.size}"
  checksum_sha1: "{outputs.bam.checksum}"
  sample: "{inputs.sample}"
  genome_build: "{inputs.genome_build}"
  aligner: "{inputs.aligner}"
  quality_cutoff: "{inputs.quality_cutoff}"
  min_length: "{inputs.min_length}"
```

---

### `outputs.<name>.optional`

**Type:** `boolean`
**Required:** No
**Default:** `false`

If `true`, a missing output (CWL output is `null` or absent) is not an error — Canon skips ingestion for this output. Use this for outputs that some workflow runs produce but others do not (e.g. BAM index files that are only generated when the aligner produces a sorted BAM).

```yaml
bam_index:
  entity_type: AlignmentIndex
  optional: true
  ...
```

**Validation:** at least one non-optional output must be declared per sidecar — `CanonRuleValidationError: sidecar has no required outputs`.

---

### Sidecar Expression Syntax

All expressions in `mosaic_fields` are strings containing `{...}` placeholders:

| Expression | Source | Description |
|---|---|---|
| `{outputs.<name>.location}` | CWL output | File URI from the CWL output object, after relocation to `output_storage` |
| `{outputs.<name>.checksum}` | CWL output | SHA1 checksum from the CWL output object (`sha1:deadbeef...`) |
| `{outputs.<name>.size}` | CWL output | File size in bytes (integer) |
| `{outputs.<name>.<key>}` | CWL output | Field from a CWL record output |
| `{outputs.<name>.entity_id}` | Ingestion | UUID of the Hippo entity created for another output in this sidecar (for cross-output references) |
| `{inputs.<name>}` | CWL inputs | Value that was passed to the CWL workflow — for entity ref fields, this is the Hippo UUID |

**Notes on `{outputs.<name>.location}`:** Canon relocates output files from the cwltool work directory to `output_storage` before evaluating this expression. The value is the final storage URI (`s3://...` or `file://...`), not the temporary cwltool path.

**Notes on `{inputs.<name>}`:** the value is whatever was passed to `inputs.json`. For entity reference fields (`genome_build`, `aligner`, `sample`, etc.), this is the Hippo UUID. For scalar fields, this is the scalar value. Storing the UUID — not the name — is correct: UUIDs are stable identifiers that can be queried against.

**Literal values** — strings without any `{...}` placeholders are stored as-is.

---

### Complete Sidecar Example

```yaml
# star_align.canon.yaml

outputs:
  bam:
    entity_type: AlignmentFile
    identity_fields:
      - sample
      - genome_build
      - aligner
      - quality_cutoff
      - min_length
    mosaic_fields:
      uri: "{outputs.bam.location}"
      file_size_bytes: "{outputs.bam.size}"
      checksum_sha1: "{outputs.bam.checksum}"
      sample: "{inputs.sample}"
      genome_build: "{inputs.genome_build}"
      aligner: "{inputs.aligner}"
      quality_cutoff: "{inputs.quality_cutoff}"
      min_length: "{inputs.min_length}"

  bam_index:
    entity_type: AlignmentIndex
    identity_fields:
      - alignment
    mosaic_fields:
      uri: "{outputs.bam_index.location}"
      alignment: "{outputs.bam.entity_id}"    # UUID of the AlignmentFile just ingested
    optional: true
```

---

## Part 7: Complete Validation Table

Canon validates all rules and sidecars at startup before accepting any requests. All errors are collected and reported together.

### Rule Validation (`CanonRuleValidationError`)

| Check | Condition | Error message |
|---|---|---|
| Duplicate rule name | Two rules have the same `name` | `duplicate rule name '{name}'` |
| Duplicate produces spec | Two rules have the same `entity_type` + `match` after resolving fixed params | `ambiguous produces: multiple rules can produce {entity_type} with these parameters` |
| Workflow file not found | `execute.workflow` path does not exist | `workflow not found: {path}` |
| Workflow not valid YAML | CWL file is not parseable | `workflow is not valid YAML: {path}` |
| Wrong CWL version | `cwlVersion != v1.2` | `CWL version {v} is not supported — Canon requires v1.2` |
| Not a Workflow | CWL file `class` is `CommandLineTool` or other | `Canon rules must reference a CWL Workflow, not {class}: {path}` |
| Sidecar not found | No `.canon.yaml` alongside the CWL file | `sidecar not found: {path}.canon.yaml` |
| Sidecar output not in CWL | A sidecar output name is not in the CWL `outputs:` block | `unknown CWL output '{name}' in sidecar {sidecar_path}` |
| Missing identity_field | An `identity_field` is not in `mosaic_fields` | `identity_field '{field}' is not declared in mosaic_fields` |
| No required outputs | All sidecar outputs are `optional: true` | `sidecar has no required outputs: {path}` |
| Unpropagated wildcard | A wildcard in `requires[].match` is absent from `produces.match` | `unpropagated wildcard '{name}' in rule '{rule}' requires[{i}].match — must appear in produces.match` |
| Tool ref without version | An entity ref to `ToolVersion` lacks a `version` field (or `version` is itself a wildcard on a non-wildcard produces spec) | `tool version required in rule '{rule}' — entity ref to ToolVersion must include a version field` |
| Unknown binding in inputs | `execute.inputs` expression references a `{bind.field}` where `bind` is not in `requires` | `unknown binding '{bind}' in execute.inputs of rule '{rule}'` |
| Missing CWL input | A CWL workflow input has no corresponding key in `execute.inputs` | `CWL workflow input '{input}' has no mapping in execute.inputs of rule '{rule}'` |

### Startup / Configuration (`CanonConfigError`)

| Check | Error |
|---|---|
| Canon entity types missing from Hippo | `Canon entity types not found in Hippo schema. Run: hippo reference install canon` |
| Executor adapter not found | `executor '{name}' not found. Available adapters: {list}` |
| Executor binary unavailable | `executor '{name}' is configured but cwltool is not installed or not on PATH` |

### Runtime Rule Errors

These raise during resolution, not at startup:

| Error class | Condition |
|---|---|
| `CanonCycleError` | Circular rule dependency: rule A requires an artifact that requires the same rule A (directly or transitively) |
| `CanonNoRuleError` | No rule can produce the requested `entity_type` with the given parameters |
| `CanonResolutionError` | `ref:T{...}` expression matches zero or more than one Hippo entity |
| `CanonPlanningError` | Unbound wildcard — a required parameter was not supplied in the request |

---

## Part 8: Naming Conventions Summary

| Element | Convention | Examples |
|---|---|---|
| Rule names | `snake_case` verb phrase | `trim_reads`, `align_reads`, `count_genes`, `build_star_index` |
| Wildcard names | `snake_case` noun | `{sample}`, `{genome_build}`, `{star_version}`, `{quality_cutoff}` |
| Bind names | `snake_case` noun (the bound artifact) | `trimmed_fastq`, `genome_index`, `bam`, `gtf` |
| Entity type names | `PascalCase` | `AlignmentFile`, `TrimmedFastqFile`, `StarIndex`, `GeneCounts` |
| Entity ref types | `PascalCase` | `ref:ToolVersion{...}`, `ref:GenomeBuild{...}` |
| Workflow files | `snake_case.cwl` paired with `snake_case.canon.yaml` | `star_align.cwl` / `star_align.canon.yaml` |

---

## Part 9: Complete `canon_rules.yaml` Example

```yaml
# canon_rules.yaml — RNA-seq pipeline (trim → align → count)

rules:

  - name: trim_reads
    description: Trim adapters and low-quality bases from raw FASTQ reads using cutadapt
    produces:
      entity_type: TrimmedFastqFile
      match:
        sample: "{sample}"
        trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"
    requires:
      - bind: raw_fastq
        entity_type: FastqFile
        match:
          sample: "{sample}"
    execute:
      workflow: workflows/cutadapt.cwl
      inputs:
        fastq: "{raw_fastq.uri}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"
        sample_id: "{sample}"

  - name: build_star_index
    description: Build a STAR genome index for a given genome build and STAR version
    produces:
      entity_type: StarIndex
      match:
        genome_build: "ref:GenomeBuild{name={genome_build}}"
        aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
    requires:
      - bind: genome_fasta
        entity_type: GenomeFasta
        match:
          genome_build: "ref:GenomeBuild{name={genome_build}}"
    execute:
      workflow: workflows/star_index.cwl
      inputs:
        fasta: "{genome_fasta.uri}"
        genome_build: "{genome_build}"
        aligner: "{aligner}"

  - name: align_reads
    description: Align trimmed reads to a reference genome using STAR
    produces:
      entity_type: AlignmentFile
      match:
        sample: "{sample}"
        genome_build: "ref:GenomeBuild{name={genome_build}}"
        aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
        trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"
    requires:
      - bind: trimmed_fastq
        entity_type: TrimmedFastqFile
        match:
          sample: "{sample}"
          trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
          quality_cutoff: "{quality_cutoff}"
          min_length: "{min_length}"
      - bind: genome_index
        entity_type: StarIndex
        match:
          genome_build: "ref:GenomeBuild{name={genome_build}}"
          aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
    execute:
      workflow: workflows/star_align.cwl
      inputs:
        fastq: "{trimmed_fastq.uri}"
        genome_index: "{genome_index.uri}"
        genome_build: "{genome_build}"
        aligner: "{aligner}"
        sample_id: "{sample}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"

  - name: count_genes
    description: Count reads per gene using HTSeq-count
    produces:
      entity_type: GeneCounts
      match:
        sample: "{sample}"
        genome_build: "ref:GenomeBuild{name={genome_build}}"
        annotation: "ref:GeneAnnotation{source=GENCODE, version={gencode_version}}"
        aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
        trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
        counter: "ref:ToolVersion{tool.name=HTSeq, version={htseq_version}}"
        strand_specific: "{strand_specific}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"
    requires:
      - bind: bam
        entity_type: AlignmentFile
        match:
          sample: "{sample}"
          genome_build: "ref:GenomeBuild{name={genome_build}}"
          aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
          trimmer: "ref:ToolVersion{tool.name=cutadapt, version={cutadapt_version}}"
          quality_cutoff: "{quality_cutoff}"
          min_length: "{min_length}"
      - bind: gtf
        entity_type: GeneAnnotationFile
        match:
          annotation: "ref:GeneAnnotation{source=GENCODE, version={gencode_version}}"
    execute:
      workflow: workflows/htseq_count.cwl
      inputs:
        bam: "{bam.uri}"
        gtf: "{gtf.uri}"
        strand_specific: "{strand_specific}"
        sample_id: "{sample}"
```
