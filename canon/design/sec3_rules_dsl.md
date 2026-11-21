## 3. Canon Rules DSL

**Document status:** Draft v0.1  
**Depends on:** sec1_overview.md, sec2_architecture.md

---

### 3.1 Overview

Canon's knowledge of how to produce artifacts lives in two files:

- **`canon_rules.yaml`** — the rule registry: maps artifact specifications to CWL workflows
- **`<workflow>.canon.yaml`** — per-workflow sidecar: maps CWL outputs to Hippo entities

Together these files form the Canon Rules DSL. They are human-authored YAML, validated
at Canon startup, and versioned in source control alongside the CWL workflow files.

---

### 3.2 Parameter Types

Canon rules use two kinds of parameter values:

**Scalar parameters** — plain values (strings, integers, floats, booleans):

```yaml
quality_cutoff: 20
min_length: 30
strand_specific: true
max_intron_length: 500000
```

Scalars are matched exactly. They are stored as-is on Hippo entities.

**Entity references** — pointers to Hippo entities, written as `ref:EntityType{...}`:

```yaml
genome_build: "ref:GenomeBuild{name=GRCh38}"
aligner: "ref:ToolVersion{tool.name=STAR, version=2.7.11a}"
sample: "ref:Sample{id=AD001}"
```

Entity references are resolved to Hippo UUIDs before any lookup or execution. Dot notation
traverses reference fields on the target entity (`tool.name` follows the `tool` reference
field on `ToolVersion` to the `name` field on `Tool`). All matching is exact — multiple
matches or zero matches raise `CanonResolutionError`.

**Wildcards** — parameters whose values are supplied at resolution time, written as `{name}`:

```yaml
genome_build: "ref:GenomeBuild{name={genome_build}}"   # entity ref with wildcard field
aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
sample: "{sample}"                                       # scalar wildcard
```

Wildcards are bound when Canon resolves the top-level request. They propagate through the
dependency chain — a wildcard in a `produces:` block with the same name as a wildcard in
a `requires:` block is automatically threaded through.

---

### 3.3 canon_rules.yaml Format

```yaml
# canon_rules.yaml — complete format reference

rules:
  - name: <string>              # unique rule identifier (snake_case)
    description: <string>       # optional human-readable description

    produces:
      entity_type: <string>     # Hippo entity type this rule produces
      match:                    # parameters that identify this artifact
        <param>: <value>        # scalar, entity ref, or wildcard

    requires:                   # inputs needed to produce this artifact
      - bind: <string>          # name for this input (used in execute.inputs)
        entity_type: <string>   # Hippo entity type to resolve
        match:                  # parameters identifying the required input
          <param>: <value>

    execute:
      workflow: <path>          # path to CWL workflow file (relative to canon_rules.yaml)
      inputs:                   # CWL workflow input → Canon value mappings
        <cwl_input>: <value>    # value may reference bound inputs via {bind.field}
```

**Complete example — RNA-seq pipeline:**

```yaml
rules:

  - name: trim_reads
    description: Trim adapters and low-quality bases from raw FASTQ reads
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

  - name: align_reads
    description: Align trimmed reads to a reference genome using STAR
    produces:
      entity_type: AlignmentFile
      match:
        sample: "{sample}"
        genome_build: "ref:GenomeBuild{name={genome_build}}"
        aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
        quality_cutoff: "{quality_cutoff}"    # inherited from upstream trim step
        min_length: "{min_length}"            # inherited from upstream trim step
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

  - name: count_genes
    description: Count reads per gene using HTSeq
    produces:
      entity_type: GeneCounts
      match:
        sample: "{sample}"
        genome_build: "ref:GenomeBuild{name={genome_build}}"
        annotation: "ref:GeneAnnotation{source=GENCODE, version={gencode_version}}"
        aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
        counter: "ref:ToolVersion{tool.name=HTSeq, version={htseq_version}}"
        strand_specific: "{strand_specific}"
        quality_cutoff: "{quality_cutoff}"    # inherited
        min_length: "{min_length}"            # inherited
    requires:
      - bind: bam
        entity_type: AlignmentFile
        match:
          sample: "{sample}"
          genome_build: "ref:GenomeBuild{name={genome_build}}"
          aligner: "ref:ToolVersion{tool.name=STAR, version={star_version}}"
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
```

---

### 3.4 Parameter Propagation (Provenance Inheritance)

A key design principle: **every artifact remembers the parameters of all upstream steps
that produced it.** This enables queries like "all GeneCounts produced from reads trimmed
with quality_cutoff=20."

The `match:` block on a `produces:` declaration is the complete parameter set stored on
the Hippo entity. Upstream parameters must be explicitly listed — they do not propagate
automatically. This is intentional: rule authors decide which upstream parameters are
meaningful identity dimensions for each artifact type.

**Example:** `GeneCounts` lists `quality_cutoff` and `min_length` in its `match:` block
even though the counting step itself doesn't use them. These are carried forward from
the `AlignmentFile` (which carries them from `TrimmedFastqFile`). The same wildcard name
`{quality_cutoff}` threads through all three rules, so a `canon get` request for
`GeneCounts` with `quality_cutoff=20` will correctly trace through the dependency chain.

**Rule:** any wildcard that appears in a `requires:` match block must also appear in the
`produces:` match block, or Canon raises a `CanonRuleValidationError` at startup. This
enforces complete provenance declaration.

---

### 3.5 Entity Reference Syntax

Full syntax for entity references in rules:

```
ref:<EntityType>{<field>=<value>, <field>=<value>, ...}
```

**Field traversal with dot notation:**

```yaml
# Follow the 'tool' reference field on ToolVersion to reach Tool.name
aligner: "ref:ToolVersion{tool.name=STAR, version=2.7.11a}"

# Follow annotation → GeneAnnotation.source
gtf: "ref:GeneAnnotationFile{annotation.source=GENCODE, annotation.version=43}"
```

Dot notation may traverse up to 3 levels. Deeper traversal raises `CanonResolutionError`.

**Wildcards inside entity references:**

```yaml
# genome_build wildcard used inside a ref
genome_build: "ref:GenomeBuild{name={genome_build}}"

# Multiple wildcards in one ref
aligner: "ref:ToolVersion{tool.name={aligner_name}, version={aligner_version}}"
```

**Resolution rules:**

1. All literal fields in a `ref:` expression must match exactly (case-sensitive)
2. Wildcard fields are resolved first, then the resulting literal expression is looked up
3. If zero entities match → `CanonResolutionError: no entity found`
4. If multiple entities match → `CanonResolutionError: ambiguous reference` (exact match required)
5. The resolved UUID is used for all subsequent Hippo queries

---

### 3.6 Input Value Expressions

The `execute.inputs:` block maps CWL workflow inputs to resolved values. Values may be:

**Bound input fields** — access fields on resolved input entities:

```yaml
inputs:
  fastq: "{trimmed_fastq.uri}"        # URI field on TrimmedFastqFile entity
  read_count: "{raw_fastq.read_count}" # scalar field on FastqFile entity
  sample_id: "{sample.id}"            # field on Sample entity (via ref resolution)
```

**Scalar wildcards** — passed through directly from the request spec:

```yaml
inputs:
  quality_cutoff: "{quality_cutoff}"
  strand_specific: "{strand_specific}"
```

**Resolved entity reference fields** — fields on entity ref targets:

```yaml
inputs:
  genome_name: "{genome_build.name}"   # 'genome_build' was resolved as ref:GenomeBuild{...}
```

**Static values** — literal strings or numbers in the rule itself:

```yaml
inputs:
  output_format: "BAM"
  sort_order: "coordinate"
```

**Expression evaluation order:**
1. Entity references in `requires:` match blocks are resolved to UUIDs
2. Wildcards are bound from the request spec
3. Input expressions are evaluated left-to-right
4. The resulting `inputs` dict is written to CWL `inputs.json` and passed to the executor

---

### 3.7 The Canon Sidecar (`.canon.yaml`)

Every CWL workflow used by Canon must have a companion `.canon.yaml` sidecar file in the
same directory. The sidecar declares what Hippo entities the CWL outputs map to.

**Sidecar format:**

```yaml
# <workflow_name>.canon.yaml

outputs:
  <cwl_output_name>:
    entity_type: <string>            # Hippo entity type for this output
    identity_fields:                 # fields that uniquely identify this artifact
      - <field_name>                 # must match fields declared in the rule's produces.match
    mosaic_fields:                    # CWL output/input → Hippo entity field mappings
      <mosaic_field>: <expression>    # expression may reference CWL outputs or rule inputs
    optional: <bool>                 # default false; if true, missing output is not an error
```

**Expression syntax in `mosaic_fields:`:**

| Expression | Meaning |
|---|---|
| `"{outputs.<name>.location}"` | File URI from CWL output object |
| `"{outputs.<name>.checksum}"` | SHA1 checksum from CWL output object |
| `"{outputs.<name>.size}"` | File size in bytes from CWL output object |
| `"{inputs.<name>}"` | Value from CWL inputs (what was passed in) |
| `"{outputs.<name>.<key>}"` | Field from a CWL record output |

**Complete sidecar example — star_align.canon.yaml:**

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
      # Entity reference fields are stored as UUIDs (already resolved during execution)
      sample: "{inputs.sample}"
      genome_build: "{inputs.genome_build}"
      aligner: "{inputs.aligner}"
      quality_cutoff: "{inputs.quality_cutoff}"
      min_length: "{inputs.min_length}"

  bam_index:
    entity_type: AlignmentIndex
    identity_fields:
      - alignment         # ref to parent AlignmentFile entity
    mosaic_fields:
      uri: "{outputs.bam_index.location}"
      alignment: "{outputs.bam.entity_id}"   # UUID of the just-ingested AlignmentFile
    optional: true        # some aligners don't produce an index; not an error if missing
```

**Validation rules for sidecars:**
- Every `identity_field` must be present in `mosaic_fields`
- Every CWL output named in the sidecar must exist in the workflow's `outputs:` block
- At least one non-optional output must be declared
- Canon validates sidecars at startup against their paired CWL files

---

### 3.8 Rule Validation

Canon validates all rules at startup before accepting any requests. Validation errors
are reported together (not fail-fast) so all problems are visible at once.

**Checks performed:**

| Check | Error |
|---|---|
| Duplicate rule names | `CanonRuleValidationError: duplicate rule name` |
| Duplicate `produces` specs (same entity_type + match) | `CanonRuleValidationError: ambiguous produces` |
| CWL workflow file not found | `CanonRuleValidationError: workflow not found` |
| Canon sidecar not found | `CanonRuleValidationError: sidecar not found` |
| Sidecar output not in CWL outputs | `CanonRuleValidationError: unknown CWL output` |
| Wildcard in `requires.match` not in `produces.match` | `CanonRuleValidationError: unpropagated wildcard` |
| Entity ref without version on a Tool type | `CanonRuleValidationError: tool version required` |
| Input expression references unknown binding | `CanonRuleValidationError: unknown binding` |
| Circular rule dependencies | `CanonCycleError: cycle detected` |

Run rule validation manually:

```bash
canon rules validate           # validate all rules
canon rules validate --rule align_reads   # validate one rule
canon rules list               # list all rules with produces specs
```

---

### 3.9 Naming Conventions

**Rule names:** `snake_case` verb phrases describing the transformation.
Examples: `trim_reads`, `align_reads`, `count_genes`, `build_star_index`

**Wildcard names:** `snake_case` nouns describing the parameter.
Examples: `{sample}`, `{genome_build}`, `{star_version}`, `{quality_cutoff}`

**Entity reference type names:** `PascalCase` matching Hippo entity type names.
Examples: `ref:ToolVersion{...}`, `ref:GenomeBuild{...}`, `ref:Sample{...}`

**Workflow files:** `snake_case.cwl` co-located with `snake_case.canon.yaml`.
Examples: `star_align.cwl` / `star_align.canon.yaml`

---

### 3.10 Worked Example — Complete Request Trace

Request: `canon get GeneCounts` with:
```
sample=ref:Sample{id=AD002}
genome_build=ref:GenomeBuild{name=GRCh38}
annotation=ref:GeneAnnotation{source=GENCODE, version=43}
aligner=ref:ToolVersion{tool.name=STAR, version=2.7.11a}
counter=ref:ToolVersion{tool.name=HTSeq, version=2.0.3}
strand_specific=reverse
quality_cutoff=20
min_length=30
cutadapt_version=4.4
```

**Step 1 — Resolve entity refs:**
```
Sample{id=AD002}                              → uuid:sample-ad002
GenomeBuild{name=GRCh38}                      → uuid:gbuild-grch38
GeneAnnotation{source=GENCODE, version=43}    → uuid:annot-gencode43
ToolVersion{tool.name=STAR, version=2.7.11a}  → uuid:toolv-star-2711a
ToolVersion{tool.name=HTSeq, version=2.0.3}   → uuid:toolv-htseq-203
ToolVersion{tool.name=cutadapt, version=4.4}  → uuid:toolv-cutadapt-44
```

**Step 2 — Query Hippo for GeneCounts:**
```
GET /entities?entity_type=GeneCounts
  &sample=sample-ad002&genome_build=gbuild-grch38
  &annotation=annot-gencode43&aligner=toolv-star-2711a
  &counter=toolv-htseq-203&strand_specific=reverse
  &quality_cutoff=20&min_length=30
→ Not found (BUILD)
```

**Step 3 — Find rule → count_genes**

**Step 4 — Resolve requires[bam]:**
```
canon get AlignmentFile{
  sample=sample-ad002, genome_build=gbuild-grch38,
  aligner=toolv-star-2711a, quality_cutoff=20, min_length=30}
→ Found: uuid:align-ad002  URI: s3://bucket/AD002.bam  (REUSE)
```

**Step 5 — Resolve requires[gtf]:**
```
canon get GeneAnnotationFile{annotation=annot-gencode43}
→ Found: uuid:gtf-gc43  URI: s3://refs/gencode.v43.gtf.gz  (REUSE)
```

**Step 6 — Execute htseq_count.cwl:**
```
inputs.json:
  bam: "s3://bucket/AD002.bam"
  gtf: "s3://refs/gencode.v43.gtf.gz"
  strand_specific: "reverse"
→ produces: s3://bucket/counts/AD002_GC43_STAR.counts.tsv
```

**Step 7 — Ingest output:**
```
POST /entities → GeneCounts{
  uri: "s3://bucket/counts/AD002_GC43_STAR.counts.tsv",
  sample: sample-ad002,
  genome_build: gbuild-grch38,
  annotation: annot-gencode43,
  aligner: toolv-star-2711a,
  counter: toolv-htseq-203,
  strand_specific: reverse,
  quality_cutoff: 20, min_length: 30
} → uuid:counts-ad002
```

**Step 8 — Record WorkflowRun, return URI.**

Total executions: 1 (HTSeq only — STAR alignment and GTEx annotation file already existed).
