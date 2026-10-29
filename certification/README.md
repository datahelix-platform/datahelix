# Composition certification & the certified-frontier ledger

This directory implements the cross-component **version-compatibility strategy**
for the DataHelix platform. Components (aperture, mosaic — formerly hippo,
ADR-0004) version and ship independently; DataHelix certifies that **one exact
version pair at a time** boots and passes the golden-path scenarios, and
records each result in an append-only **ledger**. Deployment is gated on that
ledger.

**The decision of record is [platform ADR-0001](../platform/design/decisions/ADR-0001-certified-frontier-composition.md).**
This README is the runbook.

## The one-paragraph model

Never test the version matrix — walk a single path through it. Each green
certification of the current pins appends one immutable fact
*(aperture X @ digest, mosaic Y @ digest, suite S @ sha → pass)* to the ledger.
Facts are about immutable artifacts, so they never expire and are never
re-tested. Deploy tooling refuses any pair not present as a passing ledger
entry. Matrix holes are fine: an off-path pair a deployment needs is filled by a
lazy, targeted **backfill** (`workflow_dispatch`), never a standing matrix.

## Layout

| Path | What it is |
|---|---|
| `composition.lock.json` | The current pins for this branch's line (versions + digests + fixture). The bump workflow ([`../.github/workflows/bump-lock.yml`](../.github/workflows/bump-lock.yml)) moves one component per PR; certification reads this. |
| `ledger/` | The ledger tooling (`datahelix-ledger`): `certify`, `assemble`, `query`, `gate`. Pure stdlib + git. |
| `fixtures/bootstrap/` | Versioned seed schema + data + the Aperture control-plane recipe. One source, consumed by DataHelix CI **and** (later) mosaic CI for the aperture contract file. |
| `compose/` | `docker-compose.certify.yml` + `mosaic.certify.yaml` — boots the pinned pair (mosaic serve --graphql over the fixture + the aperture SPA). |
| `scenarios/` | The golden-path Playwright suite — **one scenario per product loop**, under a hard ~10-min budget. |
| `scripts/` | `read_lock.py` (resolve pins), `run_composition.sh` (boot + seed + run under budget), `deploy_gate.sh` (deploy pre-flight). |
| `compatibility.json` | CI-assembled view of the ledger tags, for easy querying. Tags are the source of truth. |

## The three test layers (where this sits)

| Layer | Runs in | Proves |
|---|---|---|
| Component CI | each component repo | the component works in isolation |
| **Contract checks** | the **producer's** CI (aperture's contract file booted against `mosaic serve` in mosaic's PR CI) | the seam shapes hold, at authorship time |
| **Composition certification** | here, on bump PRs | one exact pair boots and passes the golden path |

The four seams the golden path exercises (isolated in aperture `web/src/data/`):
introspection enrichment, filter SDL, the `batchPut` batch unit-of-work
(Aperture ADR-0028 ↔ Hippo #84), and the control-plane document type (Aperture
ADR-0032). The aperture contract file (aperture#16) does not exist yet — **until
it does, this suite is the only seam check.**

## Golden-path scenarios (one per product loop)

| Loop | Scenario | Seam |
|---|---|---|
| Browse / filter | `scenarios/tests/01-browse-filter.spec.ts` | introspection + filter SDL |
| Single-entity write | `scenarios/tests/02-single-entity-write.spec.ts` | create mutation |
| Atomic multi-entity workflow | `scenarios/tests/03-atomic-workflow.spec.ts` | batch unit-of-work |
| Control-plane saved views / drafts | `scenarios/tests/04-control-plane.spec.ts` | control-plane document type |
| Query result table (referenced-class columns, structured values, CSV/JSON export, saved query view) | `scenarios/tests/06-result-table.spec.ts` | ADR-0041 traversal columns over nested reference selections |

`05-reference-traversal.spec.ts` is a fixture capability check at the GraphQL
seam, not a product loop; 06 certifies the same edges through the UI.

The numeric prefixes pin Playwright's execution order (01→06): browse/filter
asserts the pristine seeded fixture (5 Books), so it must run before the write
and workflow loops add rows; 06 asserts only on named seeded rows and counts it
reads off the page, so it tolerates the rows they add.

Budget is enforced twice: `playwright.config.ts` (`globalTimeout`) and
`run_composition.sh` (`BUDGET_SECONDS`, which also covers artifact pull + boot +
seed). A new scenario that would blow the budget must merge with or replace
another, or move to the non-blocking nightly tier.

## The frontier flow

1. A component releases → its release workflow dispatches the published
   `image-digest.json` to DataHelix as a `component-release` event → the **bump workflow**
   ([`../.github/workflows/bump-lock.yml`](../.github/workflows/bump-lock.yml)) opens one
   DataHelix PR moving that one pin. One release = one delta. (ADR-0001 implementation note,
   2026-10-27: the Renovate config that originally stood here was never activated.)
2. The certification workflow ([`../.github/workflows/certify.yml`](../.github/workflows/certify.yml))
   reads the lock, pulls both artifacts by digest, boots the composition, runs
   the suite under budget.
3. **Green:** merge. **Patch bumps auto-merge on green**; minor/major need
   review. On the merge (push) the workflow appends the ledger tag and refreshes
   `compatibility.json`.
4. **Red:** the PR is a cross-team pager, not backlog. The ledger records the
   failing pair. On the frontier the consumer adapts (aperture ships a compatible
   version); the bot then bumps both pins and certifies the new pair.

## Maintenance lines & backports

Supported set = **latest + at most one LTS line**. A maintenance line freezes
both its code and its contracts: its DataHelix branch (`release/lts-*`) carries its
own `composition.lock.json` and pins the era-appropriate fixture version. If a
backport certification fails against the line's frozen partners, **the backport
is wrong** — revise it, never upgrade the pinned consumer. See ADR-0001 §4 and
the failure-asymmetry rule.

## Common commands

```bash
# ledger tooling tests (runnable anywhere)
make ledger-test

# which mosaics are certified with aperture's LTS line 1.4.*? ("mosaic" and the
# legacy "hippo" name are the same component line — decision 1.7)
make ledger-query ANCHOR=aperture LINE='1.4.*' PARTNER=mosaic

# rebuild compatibility.json from the tags
make ledger-assemble

# deploy pre-flight — refuse an uncertified pair
make deploy-gate

# boot the pinned pair + run the golden path locally (needs published images)
MOSAIC_IMAGE=ghcr.io/bu-neuromics/mosaic@sha256:... \
APERTURE_IMAGE=ghcr.io/bu-neuromics/aperture@sha256:... \
  make certify-local

# on-demand backfill of an off-path pair (CI): run the "Certify composition"
# workflow via workflow_dispatch with the two versions + digests.
```

## Current status (2026-09)

The tooling, fixtures, compose, scenarios, workflow, and gate are in place, and
**both components now publish digest-addressed artifacts** —
`ghcr.io/bu-neuromics/mosaic` (mosaic's `release.yml`, which also attaches an
`image-digest.json` asset carrying the digest for the bump) and
`ghcr.io/bu-neuromics/aperture`. The certification workflow boots the pinned
pair for real, and the ledger carries a passing frontier entry for every pin
moved since. Note the direction of the seam: **Mosaic is the GraphQL provider**
(`mosaic serve --graphql`); **Aperture is the client/consumer** — its SPA
queries Mosaic's autogenerated transport, and the consumer contract file
(aperture#16), which would be the second seam check, is still unstarted.

Known gaps, each tracked where it belongs:

- The **fixture is the limit on what the frontier can certify** — less so since
  **v1.1.0** (#92, closed). `fixtures/bootstrap/schema/portal_schema.yaml` now
  carries both a stored multivalued forward reference (`Book.co_authors`) and an
  `inverse:`-declared reverse edge (`Author.books`), so mosaic 0.14.0's
  reverse-edge capability is certifiable and `05-reference-traversal.spec.ts`
  checks it at the GraphQL seam. Since **v1.2.0** (#107) the fixture also carries
  an inlined value object (`Book.dimensions`), and `06-result-table.spec.ts`
  certifies Aperture's **result-table UI** for referenced columns (Aperture
  ADR-0041) and structured values (aperture#82), including CSV/JSON export and a
  saved query view. The **MCP boundary** is still unexercised, because the
  compose boots `mosaic serve --graphql`, not `--mcp`.
- The aperture consumer contract file (aperture#16) does not exist, so this
  suite remains the only seam check.
