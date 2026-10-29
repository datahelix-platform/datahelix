# ADR-0001: Certified-frontier ledger — composition is certified per exact version pair, and deployment is gated on the ledger

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** labadorf, aperture dev agent, DataHelix dev agent (DataHelix integration-testing design handoff)
- **Related:** platform `sec5_integration_test_strategy.md` (extends it to independently-versioned submodules), `TESTING.md` (three-tier model); Aperture ADR-0028 (workflow atomicity → `batch_put` seam), ADR-0032 (control-plane document store seam), ADR-0030 (frontend stack — the SPA under test); Hippo [#84](https://github.com/datahelix-platform/mosaic/issues/84) (batch unit-of-work), Hippo ADR-0001 (graph-level as-of)

## Context

The DataHelix components (currently **aperture** and **hippo**, referenced by this monorepo as git
submodules; the in-tree components are expected to follow) **version and ship independently**.
Each component repo keeps its own CI, its own semver releases, and publishes an **immutable
artifact per release** (container image and/or package, addressed by digest). Component CI is
never re-run here — Hippo's suite alone is 10–20 min; that cost stays in Hippo.

DataHelix is the integration point: its submodule pins declare exactly **one composed version
pair at a time**, and its job is to certify that pair boots and works together. The question
this ADR settles: *how do we keep independent shipping safe without ever testing the full
version matrix?*

Testing the matrix is the trap. With two components at N releases each it is N² pairs; with
three it is N³. The matrix is combinatorially hopeless and mostly uninteresting — almost every
cell is a pair no deployment will ever run. What matters is the handful of pairs that are
actually on the release path, and *proof* that each one composes.

The relevant invariants:

- **Semver is a claim; a digest is evidence.** "This is 1.2.4" is intent. What was actually
  booted and tested is a specific image digest. A rebuilt "1.2.4" is a different artifact.
- **A behavior change is a behavior change.** "Patches can't break anything" is intent, not
  evidence — a bug fix is by definition a behavior change. Semver may decide *ceremony*; it
  must never decide *whether to test*.
- **Aperture's assumptions about Hippo's transport are isolated into four seams** —
  introspection enrichment, filter SDL, the `batchPut` batch unit-of-work shape (ADR-0028,
  Hippo #84), and the Aperture control-plane document type (ADR-0032). These form a
  machine-checkable contract; the certification suite exercises one golden-path scenario per
  product loop across them.

What breaks if we get this wrong: either CI cost explodes (matrix testing), or components drift
apart silently and a deployment composes an untested pair that fails in production (no gate).

## Decision

The platform adopts a **certified-frontier ledger**. We never test the version matrix; we walk a
single path through it and record each result append-only. Concretely:

1. **Certify exact pairs, never ranges.** A certification run pins **exact versions AND artifact
   digests** and boots that one composition. A ledger entry is the triple *(aperture X @ digest,
   hippo Y @ digest, suite S @ sha)* plus pass/fail, the failing-check name on fail, and a
   timestamp. Semver ranges are never certified.

2. **The ledger is append-only and never expires.** Facts are about immutable artifacts, so a
   certified pair is certified forever and is **never re-tested**. **Failures are recorded too** —
   an incompatible pair is paid-for information (it prevents retries and lets ranges be inferred
   later). Storage is **repo-global and branch-independent**: one **annotated git tag per
   certification** (`certified/aperture-<X>+hippo-<Y>`) carrying a small JSON document, plus a
   CI-assembled `compatibility.json` built from the tags for easy querying. Tags survive branch
   deletion and are visibly append-only.

3. **Deployment is gated on the ledger.** Deploy tooling **must refuse** any component pair (and
   digest) not present as a **passing** ledger entry. This is the mechanism that makes independent
   shipping safe. Matrix holes are fine — off-path pairs are simply uncertified; a deployment that
   needs one triggers a lazy, targeted **on-demand backfill** (`workflow_dispatch` over two
   version inputs, ~10 min) whose result joins the ledger. Backfills are never a standing matrix.

4. **Release artifacts are immutable.** A version, once certified, is **never re-cut under the
   same number** — no moving tags, no rebuilt artifacts. Recording the digest enforces this: a
   rebuilt tag mismatches its certified digest and is refused by deploy tooling.

5. **The certification always runs; semver only decides ceremony.** Each component release opens
   **one bump PR moving one submodule pin** (one release = one delta, so a failure attributes to
   a single version change — releases are never batched). CI pulls both artifacts by digest, boots
   the composition, and runs the golden-path suite under a hard wall-clock budget (~10 min).
   **Patch-level bumps auto-merge on green; minor/major bumps require human review.** The test runs
   either way.

6. **On the frontier, the consumer adapts; on a maintenance line, the producer adapts.** A red
   bump PR is a **cross-team pager, not backlog** — a stalled frontier batches future releases and
   destroys failure attribution. Resolution differs by line:
   - **Frontier (latest):** the consumer normally adapts (e.g. aperture ships a version compatible
     with the new hippo), then the bot bumps both pins and certifies the new pair.
   - **Maintenance line:** if a backport certification fails against the line's **frozen**
     partners, the **backport is wrong** (it smuggled a behavior change beyond the fix) and must be
     revised until green. **Never resolve a red LTS certification by upgrading the pinned
     consumer** — consumers on a maintenance line stay frozen.

7. **Keep the supported set small: latest + at most one older (LTS) line.** Every additional line
   is a standing cost (a release branch in the component, a maintenance branch in DataHelix,
   occasional certifications). A maintenance line freezes **both its code and its contracts**: its
   DataHelix maintenance branch pins the era-appropriate integration suite and the component
   maintenance branch runs its era-pinned contract file — the `main` suite may assert
   newer-only behavior and must not be used to certify an older line.

The three-layer test architecture this sits in:

| Layer | Where it runs | What it proves |
|---|---|---|
| Component CI | each component repo, every PR | the component works in isolation |
| **Contract checks** | consumer-published, run in the **producer's** CI | the seam shapes hold (aperture's contract file booted against `hippo serve` in hippo's PR CI) |
| **Composition certification** | DataHelix, on submodule-bump PRs | one exact pair boots and passes the golden-path scenarios |

Contract checks catch seam breakage on the producer's PR at authorship time, so the DataHelix
certification becomes a near-formality that certifies the pair. Until aperture's contract file
exists, **the DataHelix certification suite is the only seam check** — it is built first and does
not wait on the contract file.

## Consequences

- **Cost is O(releases on the path), not O(matrix).** Each release is one ~10-min certification;
  certified facts never re-run. The N² / N³ blow-up never happens.
- **Independent shipping is safe by construction.** A deployment can only compose a pair the ledger
  has certified green (with matching digests), or it must first backfill one.
- **Failure attribution is exact.** One-release-per-bump-PR means a red certification names a
  single version delta. Batching (a stalled frontier, or a bump bot that groups releases) is
  explicitly disallowed because it destroys this property.
- **New obligations on components:** publish an immutable, digest-addressed artifact per release;
  never re-cut a released number; cut a `release/<line>` branch for any supported LTS line and run
  the era-pinned contract file there. Aperture additionally owes a **contract file** (introspection
  assertions + golden request/response pairs for the four seams) that hippo CI runs — tracked in
  aperture, consumed by DataHelix' fixture package. This dependency is cross-referenced from Aperture
  ADR-0028/0032 and Hippo #84 per the two-sided-dependency rule.
- **New obligations on DataHelix:** a reusable certification workflow (main + maintenance branches +
  a `workflow_dispatch` backfill), ledger tooling (tag+JSON on green, `compatibility.json`
  assembly, a partners-of-a-line query), a bump-bot config (one PR per release, patch auto-merge),
  a versioned bootstrap fixture package (seed schema + data + the control-plane document recipe),
  and a deploy-side gate that verifies the pair against the ledger.
- **The scenario suite stays small by policy:** one golden-path scenario per product loop
  (browse/filter, single-entity write, atomic multi-entity workflow, control-plane
  saved-views/drafts) under a hard ~10-min budget. A new scenario that would blow the budget must
  merge with or replace another, or move to the non-blocking nightly tier (full suite, failure
  injection, upgrade tests of old persisted control-plane documents against a new app, and a run
  against component `main` heads to surface drift before the next release).

## Alternatives considered

- **Test the version matrix (or a sampled grid).** Combinatorially hopeless (N² / N³), and most
  cells are pairs no deployment will run. Rejected — the frontier walk certifies exactly the pairs
  on the release path and backfills the rare off-path pair on demand.
- **Certify semver ranges ("aperture 1.4.x works with hippo 1.2.x").** A range is a claim about
  untested artifacts; a patched build inside the range can break the seam. Rejected in favor of
  exact-version+digest facts. Ranges may be *inferred* from the ledger later, but are never
  *certified*.
- **Skip certification for patch bumps ("patches can't break anything").** That is intent, not
  evidence; a bug fix is a behavior change. Rejected — the certification always runs; patch semver
  only buys auto-merge-on-green, not a test skip.
- **Store the ledger as a file on the default branch.** Branch-scoped and mutable; loses history on
  branch deletion and invites silent edits. Rejected in favor of annotated tags (repo-global,
  branch-independent, visibly append-only) with `compatibility.json` assembled from them.
- **Rebuild component artifacts from source in DataHelix.** Re-runs component CI cost here and, worse,
  tests an artifact that is not the one shipped. Rejected — pull published artifacts by digest.
- **Support every released line.** Each line is a standing maintenance cost. Rejected in favor of
  latest + ≤1 LTS; older deployments upgrade to a supported line or accept being uncertified.

## Notes / open sub-questions

- **Artifact registry & digest source of truth.** The certification and deploy gate read digests
  from the component release (registry image digest / package hash). The exact registry and the
  attestation format (e.g. cosign/SLSA provenance) are deployment concerns to confirm when the
  first real artifacts ship; the ledger schema already carries the digest field.
- **Contract-file handoff.** Aperture owes the contract file (aperture-tracked). Until it lands,
  DataHelix' fixture package is the shared source of the seed schema + control-plane recipe for both
  the DataHelix suite and (later) hippo CI. Revisit the fixture package's packaging (pip vs. vendored)
  once a component repo consumes it.
- **Multi-component frontier (>2 components).** The frontier walk generalizes to a tuple; one
  bump PR per release still holds. Confirm the ledger key/label scheme when a third component (e.g.
  Cappella, Bridge) starts publishing artifacts.
</content>
</invoke>

## Implementation note (2026-10-27) — the bump bot is a release-driven dispatch, not Renovate

Decided by labadorf. The Consequences above oblige DataHelix to run "a bump-bot config (one PR per
release, patch auto-merge)". The config that shipped with this ADR (`renovate.json`, #33) was
**never activated**: the Renovate app was not installed on the org, no Renovate PR or dashboard has
ever existed, and every lock bump to date was a hand-written PR (#64, #65, #69, #70, #97, #101,
#109, #111, mosaic#218). The one-delta-per-PR property this ADR depends on has therefore rested on
discipline, not automation, for four months.

**Decision.** The bot is implemented as a **`repository_dispatch` from each component's release
workflow**, carrying the `image-digest.json` that workflow already publishes, into a DataHelix
workflow that writes `composition.lock.json`, opens one PR per release in the existing title
convention, and enables auto-merge for a patch delta. Certification runs on that PR as on any lock
change. `renovate.json` is removed. Tracking: [#121](https://github.com/datahelix-platform/datahelix/issues/121)
(DataHelix side); [mosaic#237](https://github.com/datahelix-platform/mosaic/issues/237),
[aperture#90](https://github.com/datahelix-platform/aperture/issues/90),
[reel#15](https://github.com/datahelix-platform/reel/issues/15) (the component-side step).

**Why not Renovate.** It polls the registry rather than reading the release, so the image-path
move (#117) would have hidden every new release from it; `config:recommended` would open PRs for
every Python, npm and submodule dependency in this repo; and it is a third-party app with
org-wide write access, for one file that moves about once a fortnight. **Why not stay manual.**
The attribution guarantee in Consequences should not depend on two people remembering to move
one pin at a time. **Dependabot** has no custom-file manager and cannot read the lock.

**Two obligations this note adds.** The bump PR must be opened with a token other than
`GITHUB_TOKEN`, or `certify.yml` never runs on it; and patch auto-merge needs *Allow auto-merge*
enabled on the repository, which it is not today. Both are maintainer acts recorded in #121.
