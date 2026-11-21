# Appendix A: RNA-seq Worked Example

**Document status:** Draft v0.1
**Depends on:** reference_canon_yaml.md, reference_canon_rules_yaml.md, sec3b_cwl_integration.md

---

## Overview

This appendix walks through a complete Canon setup for a bulk RNA-seq pipeline:

```
raw FASTQs → cutadapt (trim) → STAR (align) → HTSeq-count → gene counts
```

The example uses three samples (`DLPFC_001`, `DLPFC_002`, `DLPFC_003`), GRCh38 reference genome, GENCODE v44 annotation, and specific pinned tool versions throughout.

The example is self-contained: it shows the `canon.yaml` config, the required Hippo entities, the `canon_rules.yaml`, the CWL workflow files and their sidecars, and example `canon get` / `canon plan` / `canon status` commands.

---

## Part 1: Setup

### 1.1 canon.yaml

```yaml
# canon.yaml

mosaic_url: "https://hippo.lab.example.org"
mosaic_token: "${MOSAIC_TOKEN}"
executor: cwltool
rules_file: canon_rules.yaml

work_dir: /scratch/canon-work

output_storage:
  type: s3
  bucket: lab-rnaseq-data
  prefix: canon-outputs/

cwltool_options:
  - "--singularity"
  - "--parallel"

log_level: INFO
```

### 1.2 Install Canon's Hippo Reference Schema

Canon requires `Tool`, `ToolVersion`, `GenomeBuild`, `GeneAnnotation`, and `WorkflowRun` entity types. Install them once per Hippo deployment:

```bash
pip install canon
hippo reference install canon
```

### 1.3 Hippo Entities That Must Pre-Exist

These entities must be present in Hippo before running any Canon rules. They represent reference data and tool identities — Canon does not create them automatically.

#### Tool entities

```bash
hippo entity create Tool \
  --name STAR \
  --category aligner \
  --description "Spliced Transcripts Alignment to a Reference" \
  --biotools-id STAR \
  --bioconda-name star

hippo entity create Tool \
  --name cutadapt \
  --category trimmer \
  --description "Adapter trimmer for sequencing reads" \
  --biotools-id cutadapt \
  --bioconda-name cutadapt

hippo entity create Tool \
  --name HTSeq \
  --category counter \
  --description "Read counting for RNA-seq" \
  --biotools-id HTSeq \
  --bioconda-name htseq
```

#### ToolVersion entities

```bash
hippo entity create ToolVersion \
  --name STAR \
  --category aligner \
  --version 2.7.11a \
  --bioconda-build "2.7.11a--h9ee0642_0" \
  --release-date 2023-11-01

hippo entity create ToolVersion \
  --name cutadapt \
  --category trimmer \
  --version 4.6 \
  --bioconda-build "4.6--py311h38fbfac_1" \
  --release-date 2023-10-15

hippo entity create ToolVersion \
  --name HTSeq \
  --category counter \
  --version 2.0.5 \
  --bioconda-build "2.0.5--py311h38fbfac_0" \
  --release-date 2023-09-01
```

#### GenomeBuild entity

```bash
hippo entity create GenomeBuild \
  --name GRCh38 \
  --patch p14 \
  --species "Homo sapiens" \
  --ucsc-name hg38 \
  --ncbi-accession GCA_000001405.15 \
  --fasta-uri "s3://lab-references/genomes/GRCh38/GRCh38.primary_assembly.genome.fa" \
  --fai-uri "s3://lab-references/genomes/GRCh38/GRCh38.primary_assembly.genome.fa.fai"
```

#### GeneAnnotation entity

```bash
hippo entity create GeneAnnotation \
  --source GENCODE \
  --version 44 \
  --genome-build "ref:GenomeBuild{name=GRCh38}" \
  --release-date 2023-06-01 \
  --gtf-uri "s3://lab-references/annotations/gencode.v44.primary_assembly.annotation.gtf.gz" \
  --gene-count 61852
```

#### Sample entities

```bash
hippo entity create Sample \
  --id DLPFC_001 \
  --tissue "dorsolateral prefrontal cortex" \
  --species "Homo sapiens" \
  --library-type "bulk RNA-seq" \
  --library-prep "TruSeq Stranded Total RNA"

hippo entity create Sample \
  --id DLPFC_002 \
  --tissue "dorsolateral prefrontal cortex" \
  --species "Homo sapiens" \
  --library-type "bulk RNA-seq" \
  --library-prep "TruSeq Stranded Total RNA"

hippo entity create Sample \
  --id DLPFC_003 \
  --tissue "dorsolateral prefrontal cortex" \
  --species "Homo sapiens" \
  --library-type "bulk RNA-seq" \
  --library-prep "TruSeq Stranded Total RNA"
```

#### FastqFile entities (raw input data)

These represent the raw FASTQ files that already exist — Canon's starting point.

```bash
hippo entity create FastqFile \
  --sample "ref:Sample{id=DLPFC_001}" \
  --uri "s3://lab-rnaseq-data/raw/DLPFC_001_R1.fastq.gz" \
  --read-number 1 \
  --read-count 45218903 \
  --file-size-bytes 6834201600

hippo entity create FastqFile \
  --sample "ref:Sample{id=DLPFC_002}" \
  --uri "s3://lab-rnaseq-data/raw/DLPFC_002_R1.fastq.gz" \
  --read-number 1 \
  --read-count 52441287 \
  --file-size-bytes 7921843200

hippo entity create FastqFile \
  --sample "ref:Sample{id=DLPFC_003}" \
  --uri "s3://lab-rnaseq-data/raw/DLPFC_003_R1.fastq.gz" \
  --read-number 1 \
  --read-count 41887652 \
  --file-size-bytes 6321233920
```

#### GeneAnnotationFile entity (GTF file record)

```bash
hippo entity create GeneAnnotationFile \
  --annotation "ref:GeneAnnotation{source=GENCODE, version=44}" \
  --uri "s3://lab-references/annotations/gencode.v44.primary_assembly.annotation.gtf.gz" \
  --file-size-bytes 1287344128
```

---

## Part 2: canon_rules.yaml

```yaml
# canon_rules.yaml

rules:

  # ──────────────────────────────────────────────────
  # Rule 1: Trim adapters and low-quality bases
  # ──────────────────────────────────────────────────
  - name: trim_reads
    description: >
      Trim Illumina TruSeq adapters and low-quality 3' bases from single-end reads
      using cutadapt. quality_cutoff and min_length are identity dimensions carried
      forward through all downstream artifacts.
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
        adapter: "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA"  # TruSeq Read 1 adapter
        sample_id: "{sample}"

  # ──────────────────────────────────────────────────
  # Rule 2: Build STAR genome index
  # ──────────────────────────────────────────────────
  - name: build_star_index
    description: >
      Build a STAR genome index for a given reference genome assembly and STAR version.
      The index is reused across all samples with the same genome_build + aligner combination.
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
        threads: 16

  # ──────────────────────────────────────────────────
  # Rule 3: Align trimmed reads with STAR
  # ──────────────────────────────────────────────────
  - name: align_reads
    description: >
      Align trimmed reads to a reference genome using STAR two-pass alignment.
      Produces a coordinate-sorted, indexed BAM file. Carries forward quality_cutoff
      and min_length from the trimming step for full provenance tracing.
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
        sample_id: "{sample}"
        genome_build: "{genome_build}"
        aligner: "{aligner}"
        trimmer: "{trimmer}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"

  # ──────────────────────────────────────────────────
  # Rule 4: Count reads per gene with HTSeq
  # ──────────────────────────────────────────────────
  - name: count_genes
    description: >
      Count reads per gene feature using HTSeq-count. Inherits quality_cutoff and
      min_length from the alignment step so that GeneCounts entities are fully
      parameterized for cross-sample queries.
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
        annotation: "{annotation}"
        counter: "{counter}"
        aligner: "{aligner}"
        trimmer: "{trimmer}"
        genome_build: "{genome_build}"
        quality_cutoff: "{quality_cutoff}"
        min_length: "{min_length}"
```

---

## Part 3: CWL Files

### 3.1 Directory Layout

```
workflows/
  cutadapt.cwl
  cutadapt.canon.yaml
  star_index.cwl
  star_index.canon.yaml
  star_align.cwl
  star_align.canon.yaml
  htseq_count.cwl
  htseq_count.canon.yaml
  tools/
    cutadapt_tool.cwl
    star_genomegenerate.cwl
    star_alignreads.cwl
    samtools_sort.cwl
    samtools_index.cwl
    htseq_count_tool.cwl
```

---

### 3.2 cutadapt.cwl

```yaml
# workflows/cutadapt.cwl
cwlVersion: v1.2
class: Workflow

inputs:
  fastq:          File
  quality_cutoff: int
  min_length:     int
  adapter:        string
  sample_id:      string

outputs:
  trimmed_fastq:
    type: File
    outputSource: cutadapt/trimmed_fastq
  report:
    type: File
    outputSource: cutadapt/report

steps:
  cutadapt:
    run: tools/cutadapt_tool.cwl
    in:
      fastq:          fastq
      quality_cutoff: quality_cutoff
      min_length:     min_length
      adapter:        adapter
      sample_id:      sample_id
    out: [trimmed_fastq, report]
```

**`tools/cutadapt_tool.cwl`:**

```yaml
# workflows/tools/cutadapt_tool.cwl
cwlVersion: v1.2
class: CommandLineTool

requirements:
  DockerRequirement:
    dockerPull: "quay.io/biocontainers/cutadapt:4.6--py311h38fbfac_1"
  ResourceRequirement:
    coresMin: 4
    ramMin: 8000

baseCommand: cutadapt

inputs:
  fastq:
    type: File
    inputBinding:
      position: 100
  quality_cutoff:
    type: int
    inputBinding:
      prefix: "-q"
  min_length:
    type: int
    inputBinding:
      prefix: "--minimum-length"
  adapter:
    type: string
    inputBinding:
      prefix: "-a"
  sample_id:
    type: string

arguments:
  - valueFrom: "$(inputs.sample_id).trimmed.fastq.gz"
    prefix: "-o"
  - valueFrom: "$(inputs.sample_id).cutadapt_report.txt"
    prefix: "--json"
  - "--cores=0"

outputs:
  trimmed_fastq:
    type: File
    outputBinding:
      glob: "$(inputs.sample_id).trimmed.fastq.gz"
  report:
    type: File
    outputBinding:
      glob: "$(inputs.sample_id).cutadapt_report.txt"
```

**`workflows/cutadapt.canon.yaml`:**

```yaml
# workflows/cutadapt.canon.yaml
outputs:
  trimmed_fastq:
    entity_type: TrimmedFastqFile
    identity_fields:
      - sample
      - trimmer
      - quality_cutoff
      - min_length
    mosaic_fields:
      uri: "{outputs.trimmed_fastq.location}"
      file_size_bytes: "{outputs.trimmed_fastq.size}"
      checksum_sha1: "{outputs.trimmed_fastq.checksum}"
      sample: "{inputs.sample_id}"
      trimmer: "{inputs.trimmer}"        # Hippo UUID of ToolVersion entity
      quality_cutoff: "{inputs.quality_cutoff}"
      min_length: "{inputs.min_length}"
  report:
    entity_type: TrimReport
    identity_fields:
      - sample
      - trimmer
    mosaic_fields:
      uri: "{outputs.report.location}"
      sample: "{inputs.sample_id}"
      trimmer: "{inputs.trimmer}"
    optional: true
```

> Note: `trimmer` is not declared as a CWL workflow input in `cutadapt.cwl` — it is a passthrough parameter added to `execute.inputs` in the rule so the sidecar can capture it for Hippo entity identity. The CWL workflow's `inputs:` block must include it (as `string`) even though it is not used by cutadapt itself. This is the standard Canon passthrough pattern.

**Updated `cutadapt.cwl` with passthrough inputs:**

```yaml
# workflows/cutadapt.cwl (with Canon passthrough inputs)
cwlVersion: v1.2
class: Workflow

inputs:
  fastq:          File
  quality_cutoff: int
  min_length:     int
  adapter:        string
  sample_id:      string
  trimmer:        string    # passthrough: Hippo UUID of ToolVersion{cutadapt 4.6}

outputs:
  trimmed_fastq:
    type: File
    outputSource: cutadapt/trimmed_fastq
  report:
    type: File
    outputSource: cutadapt/report

steps:
  cutadapt:
    run: tools/cutadapt_tool.cwl
    in:
      fastq:          fastq
      quality_cutoff: quality_cutoff
      min_length:     min_length
      adapter:        adapter
      sample_id:      sample_id
    out: [trimmed_fastq, report]
```

---

### 3.3 star_align.cwl

This is the main alignment workflow: trim → align → sort → index (trim is a separate rule that produces the input, so this workflow starts at the STAR step).

```yaml
# workflows/star_align.cwl
cwlVersion: v1.2
class: Workflow

inputs:
  fastq:          File
  genome_index:   Directory
  sample_id:      string
  # Passthrough inputs for Canon provenance
  genome_build:   string    # Hippo UUID of GenomeBuild entity
  aligner:        string    # Hippo UUID of ToolVersion{STAR 2.7.11a}
  trimmer:        string    # Hippo UUID of ToolVersion{cutadapt 4.6}
  quality_cutoff: int
  min_length:     int

outputs:
  bam:
    type: File
    outputSource: index/bam
  bam_index:
    type: File
    outputSource: index/bam_index

steps:
  align:
    run: tools/star_alignreads.cwl
    in:
      fastq:        fastq
      genome_index: genome_index
      sample_id:    sample_id
    out: [bam, log_final, log_progress]

  sort:
    run: tools/samtools_sort.cwl
    in:
      bam:       align/bam
      sample_id: sample_id
    out: [sorted_bam]

  index:
    run: tools/samtools_index.cwl
    in:
      bam: sort/sorted_bam
    out: [bam, bam_index]
```

**`tools/star_alignreads.cwl`:**

```yaml
# workflows/tools/star_alignreads.cwl
cwlVersion: v1.2
class: CommandLineTool

requirements:
  DockerRequirement:
    dockerPull: "quay.io/biocontainers/star:2.7.11a--h9ee0642_0"
  ResourceRequirement:
    coresMin: 8
    ramMin: 40000

baseCommand: STAR

arguments:
  - --runMode
  - alignReads
  - --outSAMtype
  - BAM
  - Unsorted
  - --outSAMattributes
  - NH
  - HI
  - AS
  - NM
  - MD
  - --readFilesCommand
  - zcat
  - --outReadsUnmapped
  - Fastx

inputs:
  fastq:
    type: File
    inputBinding:
      prefix: --readFilesIn
  genome_index:
    type: Directory
    inputBinding:
      prefix: --genomeDir
  sample_id:
    type: string
    inputBinding:
      prefix: --outSAMattrRGline
      valueFrom: "ID:$(inputs.sample_id) SM:$(inputs.sample_id) PL:ILLUMINA"

outputs:
  bam:
    type: File
    outputBinding:
      glob: "Aligned.out.bam"
  log_final:
    type: File
    outputBinding:
      glob: "Log.final.out"
  log_progress:
    type: File
    outputBinding:
      glob: "Log.progress.out"
```

**`tools/samtools_sort.cwl`:**

```yaml
# workflows/tools/samtools_sort.cwl
cwlVersion: v1.2
class: CommandLineTool

requirements:
  DockerRequirement:
    dockerPull: "quay.io/biocontainers/samtools:1.18--h50ea8bc_1"
  ResourceRequirement:
    coresMin: 4
    ramMin: 16000

baseCommand: [samtools, sort]

arguments:
  - prefix: "-@"
    valueFrom: "4"

inputs:
  bam:
    type: File
    inputBinding:
      position: 1
  sample_id:
    type: string
    inputBinding:
      prefix: "-o"
      valueFrom: "$(inputs.sample_id).Aligned.sortedByCoord.out.bam"

outputs:
  sorted_bam:
    type: File
    outputBinding:
      glob: "$(inputs.sample_id).Aligned.sortedByCoord.out.bam"
```

**`tools/samtools_index.cwl`:**

```yaml
# workflows/tools/samtools_index.cwl
cwlVersion: v1.2
class: CommandLineTool

requirements:
  DockerRequirement:
    dockerPull: "quay.io/biocontainers/samtools:1.18--h50ea8bc_1"
  ResourceRequirement:
    coresMin: 2
    ramMin: 4000

baseCommand: [samtools, index]

inputs:
  bam:
    type: File
    inputBinding:
      position: 1

outputs:
  bam:
    type: File
    outputBinding:
      glob: "*.bam"
    secondaryFiles:
      - .bai
  bam_index:
    type: File
    outputBinding:
      glob: "*.bam.bai"
```

**`workflows/star_align.canon.yaml`:**

```yaml
# workflows/star_align.canon.yaml
outputs:
  bam:
    entity_type: AlignmentFile
    identity_fields:
      - sample
      - genome_build
      - aligner
      - trimmer
      - quality_cutoff
      - min_length
    mosaic_fields:
      uri: "{outputs.bam.location}"
      file_size_bytes: "{outputs.bam.size}"
      checksum_sha1: "{outputs.bam.checksum}"
      sample: "{inputs.sample_id}"
      genome_build: "{inputs.genome_build}"
      aligner: "{inputs.aligner}"
      trimmer: "{inputs.trimmer}"
      quality_cutoff: "{inputs.quality_cutoff}"
      min_length: "{inputs.min_length}"

  bam_index:
    entity_type: AlignmentIndex
    identity_fields:
      - alignment
    mosaic_fields:
      uri: "{outputs.bam_index.location}"
      alignment: "{outputs.bam.entity_id}"   # UUID assigned to AlignmentFile above
    optional: true
```

---

### 3.4 htseq_count.cwl

```yaml
# workflows/htseq_count.cwl
cwlVersion: v1.2
class: Workflow

inputs:
  bam:            File
  gtf:            File
  strand_specific: string    # "yes", "no", or "reverse"
  sample_id:      string
  # Canon passthrough inputs
  annotation:     string    # Hippo UUID of GeneAnnotation entity
  counter:        string    # Hippo UUID of ToolVersion{HTSeq 2.0.5}
  aligner:        string    # Hippo UUID of ToolVersion{STAR 2.7.11a}
  trimmer:        string    # Hippo UUID of ToolVersion{cutadapt 4.6}
  genome_build:   string    # Hippo UUID of GenomeBuild entity
  quality_cutoff: int
  min_length:     int

outputs:
  counts:
    type: File
    outputSource: htseq/counts

steps:
  htseq:
    run: tools/htseq_count_tool.cwl
    in:
      bam:             bam
      gtf:             gtf
      strand_specific: strand_specific
      sample_id:       sample_id
    out: [counts]
```

**`tools/htseq_count_tool.cwl`:**

```yaml
# workflows/tools/htseq_count_tool.cwl
cwlVersion: v1.2
class: CommandLineTool

requirements:
  DockerRequirement:
    dockerPull: "quay.io/biocontainers/htseq:2.0.5--py311h38fbfac_0"
  ResourceRequirement:
    coresMin: 2
    ramMin: 8000

baseCommand: [python, -m, HTSeq.scripts.count]

arguments:
  - "--format=bam"
  - "--order=pos"

inputs:
  bam:
    type: File
    inputBinding:
      position: 10
  gtf:
    type: File
    inputBinding:
      position: 11
  strand_specific:
    type: string
    inputBinding:
      prefix: "--stranded"
  sample_id:
    type: string

stdout: "$(inputs.sample_id).counts.tsv"

outputs:
  counts:
    type: stdout
```

**`workflows/htseq_count.canon.yaml`:**

```yaml
# workflows/htseq_count.canon.yaml
outputs:
  counts:
    entity_type: GeneCounts
    identity_fields:
      - sample
      - genome_build
      - annotation
      - aligner
      - trimmer
      - counter
      - strand_specific
      - quality_cutoff
      - min_length
    mosaic_fields:
      uri: "{outputs.counts.location}"
      file_size_bytes: "{outputs.counts.size}"
      checksum_sha1: "{outputs.counts.checksum}"
      sample: "{inputs.sample_id}"
      genome_build: "{inputs.genome_build}"
      annotation: "{inputs.annotation}"
      aligner: "{inputs.aligner}"
      trimmer: "{inputs.trimmer}"
      counter: "{inputs.counter}"
      strand_specific: "{inputs.strand_specific}"
      quality_cutoff: "{inputs.quality_cutoff}"
      min_length: "{inputs.min_length}"
```

---

## Part 4: Example Canon Commands

### 4.1 Validate Rules Before Running

```bash
canon rules validate
```

Expected output:
```
Canon rules validation
─────────────────────────────────────────────────
✓ trim_reads       workflows/cutadapt.cwl        ← sidecar ok
✓ build_star_index workflows/star_index.cwl      ← sidecar ok
✓ align_reads      workflows/star_align.cwl      ← sidecar ok
✓ count_genes      workflows/htseq_count.cwl     ← sidecar ok

4 rules validated. 0 errors.
```

### 4.2 canon plan — Dry Run for First Sample

```bash
canon plan GeneCounts \
  --param "sample=ref:Sample{id=DLPFC_001}" \
  --param "genome_build=ref:GenomeBuild{name=GRCh38}" \
  --param "annotation=ref:GeneAnnotation{source=GENCODE,version=44}" \
  --param "aligner=ref:ToolVersion{tool.name=STAR,version=2.7.11a}" \
  --param "trimmer=ref:ToolVersion{tool.name=cutadapt,version=4.6}" \
  --param "counter=ref:ToolVersion{tool.name=HTSeq,version=2.0.5}" \
  --param strand_specific=reverse \
  --param quality_cutoff=20 \
  --param min_length=30
```

**Output (first run — nothing in Hippo yet):**

```
Canon execution plan
──────────────────────────────────────────────────────────────────────────
🟡 BUILD  GeneCounts
           sample=DLPFC_001  genome_build=GRCh38  annotation=GENCODE/44
           aligner=STAR/2.7.11a  trimmer=cutadapt/4.6  counter=HTSeq/2.0.5
           strand_specific=reverse  quality_cutoff=20  min_length=30
           rule: count_genes → workflows/htseq_count.cwl

  🟡 BUILD  AlignmentFile
             sample=DLPFC_001  genome_build=GRCh38  aligner=STAR/2.7.11a
             trimmer=cutadapt/4.6  quality_cutoff=20  min_length=30
             rule: align_reads → workflows/star_align.cwl

    🟡 BUILD  TrimmedFastqFile
               sample=DLPFC_001  trimmer=cutadapt/4.6
               quality_cutoff=20  min_length=30
               rule: trim_reads → workflows/cutadapt.cwl

      🟢 REUSE  FastqFile
                 sample=DLPFC_001
                 entity: uuid:fastq-dlpfc001  uri: s3://lab-rnaseq-data/raw/DLPFC_001_R1.fastq.gz

    🟡 BUILD  StarIndex
               genome_build=GRCh38  aligner=STAR/2.7.11a
               rule: build_star_index → workflows/star_index.cwl

      🟢 REUSE  GenomeFasta
                 genome_build=GRCh38
                 entity: uuid:fasta-grch38  uri: s3://lab-references/genomes/GRCh38/GRCh38.primary_assembly.genome.fa

  🟢 REUSE  GeneAnnotationFile
             annotation=GENCODE/44
             entity: uuid:gtf-gc44  uri: s3://lab-references/annotations/gencode.v44.primary_assembly.annotation.gtf.gz

──────────────────────────────────────────────────────────────────────────
Summary: 4 BUILD (4 CWL executions), 3 REUSE (0 executions)
Build order:
  1. trim_reads        (DLPFC_001)
  2. build_star_index  (GRCh38 / STAR 2.7.11a)
  3. align_reads       (DLPFC_001)
  4. count_genes       (DLPFC_001)

Estimated storage: ~12.5 GB new outputs
```

### 4.3 canon plan — Second Sample (Index Already Built)

After running for `DLPFC_001`, the `StarIndex` and `TrimmedFastqFile` for DLPFC_001 exist, but DLPFC_002 is new. The STAR index is shared:

```bash
canon plan GeneCounts \
  --param "sample=ref:Sample{id=DLPFC_002}" \
  --param "genome_build=ref:GenomeBuild{name=GRCh38}" \
  --param "annotation=ref:GeneAnnotation{source=GENCODE,version=44}" \
  --param "aligner=ref:ToolVersion{tool.name=STAR,version=2.7.11a}" \
  --param "trimmer=ref:ToolVersion{tool.name=cutadapt,version=4.6}" \
  --param "counter=ref:ToolVersion{tool.name=HTSeq,version=2.0.5}" \
  --param strand_specific=reverse \
  --param quality_cutoff=20 \
  --param min_length=30
```

**Output:**

```
Canon execution plan
──────────────────────────────────────────────────────────────────────────
🟡 BUILD  GeneCounts
           sample=DLPFC_002  ...
           rule: count_genes → workflows/htseq_count.cwl

  🟡 BUILD  AlignmentFile
             sample=DLPFC_002  ...
             rule: align_reads → workflows/star_align.cwl

    🟡 BUILD  TrimmedFastqFile
               sample=DLPFC_002  trimmer=cutadapt/4.6  quality_cutoff=20  min_length=30
               rule: trim_reads → workflows/cutadapt.cwl

      🟢 REUSE  FastqFile
                 sample=DLPFC_002
                 entity: uuid:fastq-dlpfc002  uri: s3://lab-rnaseq-data/raw/DLPFC_002_R1.fastq.gz

    🟢 REUSE  StarIndex
               genome_build=GRCh38  aligner=STAR/2.7.11a
               entity: uuid:staridx-grch38-2711a  uri: s3://lab-rnaseq-data/canon-outputs/StarIndex/2026-03-24/build_star_index-abc123/

  🟢 REUSE  GeneAnnotationFile
             annotation=GENCODE/44
             entity: uuid:gtf-gc44  uri: s3://lab-references/annotations/gencode.v44.primary_assembly.annotation.gtf.gz

──────────────────────────────────────────────────────────────────────────
Summary: 3 BUILD (3 CWL executions), 3 REUSE (0 executions)
Build order:
  1. trim_reads   (DLPFC_002)
  2. align_reads  (DLPFC_002)
  3. count_genes  (DLPFC_002)

Estimated storage: ~9.2 GB new outputs
```

The `StarIndex` is REUSED from the first run. The genome index is built once and shared.

### 4.4 canon get — Execute for DLPFC_001

```bash
canon get GeneCounts \
  --param "sample=ref:Sample{id=DLPFC_001}" \
  --param "genome_build=ref:GenomeBuild{name=GRCh38}" \
  --param "annotation=ref:GeneAnnotation{source=GENCODE,version=44}" \
  --param "aligner=ref:ToolVersion{tool.name=STAR,version=2.7.11a}" \
  --param "trimmer=ref:ToolVersion{tool.name=cutadapt,version=4.6}" \
  --param "counter=ref:ToolVersion{tool.name=HTSeq,version=2.0.5}" \
  --param strand_specific=reverse \
  --param quality_cutoff=20 \
  --param min_length=30
```

**Console output during execution:**

```
[INFO] Resolving GeneCounts (sample=DLPFC_001, ...)
[INFO] GeneCounts — MISS in Hippo, searching for rule
[INFO] Rule matched: count_genes
[INFO] Resolving AlignmentFile (sample=DLPFC_001, ...) — MISS, building
[INFO] Resolving TrimmedFastqFile (sample=DLPFC_001, ...) — MISS, building
[INFO] Resolving FastqFile (sample=DLPFC_001) — REUSE uuid:fastq-dlpfc001
[INFO] EXEC trim_reads → workflows/cutadapt.cwl [started]
[INFO] EXEC trim_reads → completed in 4m12s
[INFO] INGEST TrimmedFastqFile → uuid:trimmed-dlpfc001
[INFO] Resolving StarIndex (genome_build=GRCh38, aligner=STAR/2.7.11a) — MISS, building
[INFO] Resolving GenomeFasta (genome_build=GRCh38) — REUSE uuid:fasta-grch38
[INFO] EXEC build_star_index → workflows/star_index.cwl [started]
[INFO] EXEC build_star_index → completed in 38m51s
[INFO] INGEST StarIndex → uuid:staridx-grch38-2711a
[INFO] EXEC align_reads → workflows/star_align.cwl [started]
[INFO] EXEC align_reads → completed in 27m03s
[INFO] INGEST AlignmentFile → uuid:align-dlpfc001
[INFO] Resolving GeneAnnotationFile (annotation=GENCODE/44) — REUSE uuid:gtf-gc44
[INFO] EXEC count_genes → workflows/htseq_count.cwl [started]
[INFO] EXEC count_genes → completed in 6m44s
[INFO] INGEST GeneCounts → uuid:counts-dlpfc001

s3://lab-rnaseq-data/canon-outputs/GeneCounts/2026-03-24/count_genes-def456/DLPFC_001.counts.tsv
```

Canon prints the final URI to stdout. The exit code is 0 on success.

### 4.5 canon get — Second Call (Full REUSE)

Running the same command again immediately returns without any execution:

```bash
canon get GeneCounts \
  --param "sample=ref:Sample{id=DLPFC_001}" \
  [... same params ...]
```

```
[INFO] Resolving GeneCounts (sample=DLPFC_001, ...) — REUSE uuid:counts-dlpfc001

s3://lab-rnaseq-data/canon-outputs/GeneCounts/2026-03-24/count_genes-def456/DLPFC_001.counts.tsv
```

Total elapsed time: ~350ms (one Hippo query round-trip).

### 4.6 canon status — After Running All Three Samples

```bash
canon status --last 20
```

```
Canon workflow run status
──────────────────────────────────────────────────────────────────────────────
Status     Rule               Sample      Started              Duration
──────────────────────────────────────────────────────────────────────────────
✅ completed  count_genes     DLPFC_003   2026-03-24 14:52:01   6m38s
✅ completed  align_reads     DLPFC_003   2026-03-24 14:44:31   26m57s
✅ completed  trim_reads      DLPFC_003   2026-03-24 14:40:18   4m08s
✅ completed  count_genes     DLPFC_002   2026-03-24 11:31:42   6m51s
✅ completed  align_reads     DLPFC_002   2026-03-24 11:04:12   27m22s
✅ completed  trim_reads      DLPFC_002   2026-03-24 10:59:57   4m09s
✅ completed  count_genes     DLPFC_001   2026-03-24 09:53:24   6m44s
✅ completed  align_reads     DLPFC_001   2026-03-24 09:26:21   27m03s
✅ completed  build_star_index  GRCh38    2026-03-24 08:47:30   38m51s
✅ completed  trim_reads      DLPFC_001   2026-03-24 08:43:18   4m12s

10 runs shown. 10 completed, 0 failed, 0 running.
```

Note that `build_star_index` ran only once for all three samples — the GRCh38/STAR 2.7.11a index was REUSED for DLPFC_002 and DLPFC_003.

### 4.7 Hippo Queries After Completion

With all three samples processed, the produced entities are queryable in Hippo:

```bash
# All GeneCounts for GRCh38 / GENCODE v44 / STAR 2.7.11a
hippo query GeneCounts \
  --genome-build "ref:GenomeBuild{name=GRCh38}" \
  --annotation "ref:GeneAnnotation{source=GENCODE,version=44}" \
  --aligner "ref:ToolVersion{tool.name=STAR,version=2.7.11a}"

# → 3 entities: uuid:counts-dlpfc001, uuid:counts-dlpfc002, uuid:counts-dlpfc003

# All alignments using STAR 2.7.11a (across any genome build)
hippo query AlignmentFile \
  --aligner "ref:ToolVersion{tool.name=STAR,version=2.7.11a}"

# → 3 entities: uuid:align-dlpfc001, uuid:align-dlpfc002, uuid:align-dlpfc003

# Provenance for the DLPFC_001 counts file
hippo query WorkflowRun \
  --output-entity-id uuid:counts-dlpfc001

# → 1 entity: WorkflowRun{rule=count_genes, cwl=htseq_count.cwl,
#     runner=cwltool/3.1.20240112164112, env=singularity/sha256:...,
#     started_at=2026-03-24T09:53:24Z, status=completed}
```

---

## Summary

This example demonstrates the key Canon patterns in a realistic setting:

| Pattern | Where shown |
|---|---|
| Scalar wildcards (`{quality_cutoff}`) propagating through 4 rules | All rules in canon_rules.yaml |
| Entity references with wildcard fields (`ref:GenomeBuild{name={genome_build}}`) | `align_reads`, `build_star_index`, `count_genes` rules |
| Shared upstream artifact (StarIndex built once, reused 3×) | `build_star_index` rule + plan output |
| Passthrough CWL inputs for provenance capture | `cutadapt.cwl`, `star_align.cwl`, `htseq_count.cwl` |
| Sidecar `{outputs.<name>.entity_id}` cross-reference | `star_align.canon.yaml` AlignmentIndex output |
| Optional sidecar output | `AlignmentIndex` in `star_align.canon.yaml` |
| REUSE short-circuit on second call | Section 4.5 |
| Full provenance queryable in Hippo | Section 4.7 |
