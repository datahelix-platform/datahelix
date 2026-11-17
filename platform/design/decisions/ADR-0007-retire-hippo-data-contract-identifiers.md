# ADR-0007: Retire the `hippo` data-contract identifiers: `dhlx` for platform contracts, `mosaic_*` for runtime identifiers

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** labadorf (to ratify)
- **Related:** Mosaic [ADR-0004](https://github.com/datahelix-platform/mosaic/blob/main/design/decisions/ADR-0004-rename-hippo-to-mosaic.md) (Hippo → Mosaic rename and its deprecation window); Mosaic [ADR-0014](https://github.com/datahelix-platform/mosaic/blob/main/design/decisions/ADR-0014-polymorphic-graphql-types-for-abstract-ranges.md) Decision 5 (`hippo_anchor` / `hippo_manifest`); [ADR-0001](./ADR-0001-certified-frontier-composition.md) (certified frontier); [ADR-0006](./ADR-0006-authenticating-proxy-in-recipes.md) (the `X-Hippo-Actor` header); datahelix#57 (umbrella), datahelix#49 (where these were deferred), datahelix#2 (linkml-store); mosaic#124 and aperture#35 (companions), aperture#32; the inventory in [`../hippo-identifier-inventory.md`](../hippo-identifier-inventory.md)

## Context

Mosaic was called Hippo until Mosaic ADR-0004. The rename moved the package, CLI, entry-point
groups, env vars and config file to `mosaic`, with `hippo` kept as deprecated aliases. Then
datahelix#49 adopted Mosaic naming across docs, CI, config and the submodule path, but
deliberately left the **data-contract identifiers** on `hippo`:

> Data-contract identifiers keep the `hippo` spelling: `hippo_core` / `hippo_ext` schemas,
> `hippo_*` annotation keys, the `hippo_meta` table, and legacy `hippo.*` entry-point groups.

The reasons were sound at the time. These names are baked into LinkML schemas, the wire format
and persisted data, and they span several repos. Renaming them is a breaking change that seemed
to need a migration path and a compatibility window. datahelix#57 was opened to do that later,
with dual-read aliases and a forward migration of stored data.

Those reasons no longer hold:

1. **There are no users to migrate.** Every deployment is a dev deployment built from demo
   synthetic data (`deploy/recipes/demo`, `demo-reel`, `solo`, `ide`, and the certification
   fixtures). Each one is already rebuilt from source data when it changes: the demo images bake
   the SQLite database at build time. Nothing holds a `hippo_meta` table or a stored `hippo://`
   URI that can't be regenerated.
2. **Waiting makes it more expensive.** New `hippo_*` names keep arriving. Mosaic#228 / #278
   (ADR-0014 Decisions 2–6, merged 2026-11-17 as `f7a741b`) added two class annotations,
   `hippo_anchor` and `hippo_manifest`, and its ADR already says they "become `mosaic_*` under
   datahelix#57". Every feature that adds a key also adds a future rename.
3. **The next Mosaic release is breaking anyway.** Mosaic's `[Unreleased]` section (v0.16.0)
   already has a breaking change: the raw `*_id(s)` fallback fields are removed for references
   into a family. A rename landed in the same release costs consumers one breaking upgrade
   instead of two.
4. **1.0 should not ship with a retired product name in its contract.** After 1.0 the same
   rename would need the full deprecation machinery that #57 originally planned.

The inventory turned up two more facts:

- **No production code emits `hippo://`.** The entity-URI scheme exists only in the contract
  docs (`TESTING.md`, `platform/design/sec5_integration_test_strategy.md`), the Canon/Cappella
  contract tests, and a synthetic URI built by the platform test shim
  (`tests/platform/conftest.py`). Mosaic never produces it, and Aperture neither parses nor
  renders it. Renaming it changes docs and tests only.
- **`brainbank-hippo-schema` does not use the contract.** Its schema imports no `hippo_core`,
  uses no `hippo_*` annotation, and declares its own prefix (`https://w3id.org/VA-NCPTSDBB/brainbank/`).
  `hippo` appears only in the repo name and in prose.

The question: **what should each `hippo` identifier become, who owns it, and when do we switch?**

## Decision

**Finish the rename now, before 1.0, in one coordinated breaking change, with no compatibility
window.** Each identifier gets the name of whoever owns it:

- **Platform-wide contract parts take the platform namespace `dhlx`** (from DataHelix). These are
  the parts that more than one component produces or consumes, or that a second implementation
  of the contract would have to speak:
  - the entity-URI scheme: `hippo://<EntityType>/<uuid>` → `dhlx://<EntityType>/<uuid>`;
  - the LinkML namespace: CURIE prefix `hippo` → `dhlx`, expanding to
    `https://w3id.org/datahelix/` instead of `https://w3id.org/hippo/`.
- **Mosaic-runtime-only identifiers become `mosaic_*` / `mosaic.*`.** These are the names that
  only the Mosaic runtime reads or writes:
  - the `hippo_*` schema annotation keys the runtime reads (`hippo_index` → `mosaic_index`, …,
    including the new `hippo_anchor` / `hippo_manifest`);
  - the internal tables `hippo_meta` and `hippo_xref_index`;
  - the legacy `hippo.*` entry-point groups. These are removed, because `mosaic.*` already
    exists;
  - probably the GraphQL `hippoSchema` / `hippoEntityType` queries → `mosaicSchema` /
    `mosaicEntityType` (open question Q3).
- **Identifiers whose owner is unclear are open questions below**, each with a recommendation.
  This ADR does not decide them. Ratifying this ADR means also answering Q1–Q8 (or accepting
  their recommendations).

**Migration is "rebuild from the demo data."** There is no dual-read, no read-time alias, no
`hippo_meta` → `mosaic_meta` migration step, and no deprecation window. After the change,
Mosaic reads only the new names. A schema that still uses a `hippo_*` annotation key fails
validation with an error naming the replacement key, so a stale schema fails loudly instead of
being silently ignored.

### Naming table

"Owner" is the component that defines the name. Consumers update when the owner releases.

| Kind | Old | New | Owner | Consumers / where it appears |
|---|---|---|---|---|
| Entity-URI scheme | `hippo://<EntityType>/<uuid>` | `dhlx://<EntityType>/<uuid>` | **Platform** | Canon (producer per contract), Cappella (parser), contract tests, `TESTING.md`, `sec5` |
| LinkML CURIE prefix | `hippo:` | `dhlx:` | **Platform** | `hippo_core.yaml`, `hippo_ext.yaml`, `recipe_manifest.yaml` (`default_prefix`), `tests/conftest.py` |
| LinkML namespace URI | `https://w3id.org/hippo/` | `https://w3id.org/datahelix/` | **Platform** | same files; needs a w3id registration (external step, see Notes) |
| Schema ids | `https://w3id.org/hippo/hippo_core`, `…/hippo_ext`, `…/recipe_manifest` | `https://w3id.org/datahelix/<schema name>` | Platform namespace, Mosaic-authored | Q1 |
| Core schema name | `hippo_core` (the `imports:` name) | `mosaic_core` (recommended, Q1) | Mosaic | every user schema's `imports:`; certification fixtures; `tests/conftest.py`; demo-small schema |
| Annotation-vocabulary schema | `hippo_ext` | `mosaic_ext` | Mosaic | Mosaic only |
| Schema annotation keys | `hippo_unique`, `hippo_index`, `hippo_index_partial`, `hippo_search`, `hippo_external_xref`, `hippo_append_only`, `hippo_accessor`, `hippo_anchor`, `hippo_manifest`, `hippo_namespace` | `mosaic_unique`, `mosaic_index`, … `mosaic_namespace` (same suffix) | Mosaic | user schemas (certification fixtures, demo-small, recipe overlays), docs |
| Annotation prefix constant | `HIPPO_ANNOTATION_PREFIX = "hippo_"` (and `HIPPO_*` key constants) | `MOSAIC_ANNOTATION_PREFIX = "mosaic_"` | Mosaic | Mosaic only |
| Metadata table | `hippo_meta` | `mosaic_meta` | Mosaic | Mosaic only (SQLite + Postgres DDL) |
| Xref side table | `hippo_xref_index` | `mosaic_xref_index` | Mosaic | Mosaic only |
| Entry-point groups | `hippo.storage_adapters`, `hippo.write_validators`, `hippo.schema_packages`, `hippo.reference_loaders`, `hippo.reference_loader_cli` | removed (`mosaic.*` already canonical) | Mosaic | Q4 |
| GraphQL root fields | `hippoSchema`, `hippoEntityType` | `mosaicSchema`, `mosaicEntityType` (recommended, Q3) | Mosaic | Aperture (`HIPPO_SCHEMA_QUERY`), Reel (`planner/capabilities.py`), demo-small evals, certification introspection fixtures |
| Error codes | `HIPPO_EXT_VALIDATION`, `HIPPO_TREE_ROOT_COLLISION`, `HIPPO_TREE_ROOT_SLOT_COLLISION`, `HIPPO_REQUIRES_UNSATISFIED`, `HIPPO_EXTERNAL_XREF_RANGE` | drop the prefix (`EXT_VALIDATION`, …), recommended (Q6) | Mosaic | error payloads |
| Recipe-manifest key | `hippo_version` (in `recipe.yaml`) | `mosaic_version` | Mosaic | recipe authors |
| Tree-root class | `_HippoInstanceBundle` | `_MosaicInstanceBundle` | Mosaic | Mosaic only (synthetic) |
| Actor header | `X-Hippo-Actor` | `X-Dhlx-Actor` (recommended, Q2) | Platform (Q2) | written by recipe nginx / Bridge; read by Mosaic middleware |
| Aperture config vars | `VITE_HIPPO_GRAPHQL_URL`, `VITE_HIPPO_CONTROL_PLANE_URL` | `VITE_GRAPHQL_URL`, `VITE_CONTROL_PLANE_URL` (recommended, Q5) | Aperture | datahelix recipes (`entrypoint.sh`, compose files) |
| Canon / Cappella config vocabulary | `hippo_fields` (sidecar rule key), `hippo_poll` (trigger type), Cappella's `hippo:` config section and `hippo:<type>` event source | `mosaic_fields`, `mosaic_poll`, `mosaic:` (recommended, Q7) | Canon / Cappella (in-tree) | rule and workflow YAML, docs |
| Certification fixture key | `schema_min_hippo_core` | `schema_min_mosaic_core` | datahelix | `certification/fixtures/bootstrap/manifest.yaml` |
| ADR-0004 aliases | `import hippo`, `hippo` console script, `HIPPO_*` env fallback, `hippo.yaml` config fallback | removed | Mosaic | Q4 |
| Repo name | `VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema` | not decided here (Q8) | VA-NCPTSDBB | datahelix recipe Dockerfiles, evals, linkml-data-gen |

Not in scope: Python identifiers that are not part of a contract (`hippo_client` parameters,
`HippoPollHandler`, `HippoSource`, test fixtures). Rename them when the code around them changes;
the inventory lists them. One exception: `mosaic.api.factory.create_app(hippo_client=…)` and
`create_mcp_app(hippo_client=…)` are public SDK parameters, so rename them in the same Mosaic
release. **`hippocampus` is a brain region, not an identifier.** Exclude it from every sweep.

## Why a separate contract name, and why not "hippo"

A name separate from the runtime is warranted for the parts that outlive any one implementation:

- **Parts several components share.** Canon produces entity URIs, Cappella parses them, and
  Aperture is meant to render them. The actor header is set by the recipe proxy or Bridge (the
  platform's sole PEP, `sec6`) and read by whichever component sits behind it. None of these
  belongs to Mosaic.
- **A second implementation of the contract.** datahelix#2 plans to put `linkml-store` under
  Mosaic as a storage backend. As written, that keeps Mosaic as the only runtime, so the
  annotation keys stay runtime-owned (`mosaic_*`). If another runtime ever implements the
  contract itself, the URI scheme and the namespace must not carry the first implementation's
  name. Those two are the parts that a second implementation would have to speak.
- **Vocabularies on a persistent identifier.** A LinkML namespace URI should resolve and should
  outlive renames. A platform-level w3id path does that; a component-level one doesn't.

A separate contract name is **not** warranted for "hippo" specifically:

- "Hippo" is the retired name of one component, not the platform. Keeping it on the contract
  implies Mosaic owns the contract, and it confuses every reader who meets a "hippo" that no
  longer exists anywhere else.
- `hippo` collides with domain vocabulary in the platform's first deployment, a brain bank
  (`hippocampus`). Every sweep needs a manual exclusion.
- `w3id.org/hippo/` was never registered. It returns 404 today, so the existing namespace never
  resolved. There is no persistent identifier to preserve.

## Consequences

- One coordinated breaking release per component, then a certified-frontier entry for the new
  pair (ADR-0001). Every dev deployment is rebuilt from demo data. No old database is opened
  by the new code.
- After the change, Mosaic reads only `mosaic_*` keys and `mosaic_meta`. A `hippo_*` key in a
  schema is a validation error that names the replacement, so stale schemas fail loudly.
- ADR-0004's deprecation window ends (if Q4 is accepted). The `hippo` CLI, `import hippo` and
  the `HIPPO_*` / `hippo.yaml` fallbacks go away, which removes a class of "which spelling won?"
  bugs.
- Future features name new annotations `mosaic_*` from the start.
- **New obligation:** register `https://w3id.org/datahelix/` with w3id.org, so the `dhlx`
  namespace resolves (see Notes). This is an external step for the user, not part of any PR.
- datahelix#57's original plan (dual-read aliases, a `hippo_meta` forward migration, and a
  deprecation window) is dropped. If it is ever needed after 1.0, it would be a new ADR.

### Per-repo work

| Repo | Work |
|---|---|
| **mosaic** (mosaic#124) | Rename `hippo_core.yaml` / `hippo_ext.yaml` (Q1) and their ids and prefix; rename the annotation keys and `HIPPO_*` constants; rename `hippo_meta` / `hippo_xref_index` in both adapters' DDL; rename `hippoSchema` / `hippoEntityType` (Q3), error codes (Q6), `recipe.yaml` `hippo_version`, `_HippoInstanceBundle`, the `create_app` / `create_mcp_app` `hippo_client` parameter; switch the actor header (Q2); remove the ADR-0004 aliases (Q4); reject `hippo_*` keys with a hint; update `design/`, `docs/`, examples, tests; record a Mosaic ADR that ends ADR-0004's window (Q4); CHANGELOG `### Upgrading` entry: "rebuild from source data". Wants a Mosaic ADR-0014 note that Decision 5's keys are now `mosaic_anchor` / `mosaic_manifest`. |
| **aperture** (aperture#35) | `HIPPO_SCHEMA_QUERY` → the new GraphQL fields (Q3) and the `hasHippoSchema` capability check; rename the `VITE_HIPPO_*` config vars (Q5); default config path `./hippo.yaml` → `./mosaic.yaml`; regenerate `web/src/data/testing/*Introspection.json` fixtures. `HippoSource` / `createHippoStore` / `backend: 'hippo'` are internal names (rename opportunistically; if `backend: 'hippo'` is persisted in control-plane documents, rename it in the same change). |
| **reel** | `planner/capabilities.py` query `hippoSchema` → Q3's new name; docs. |
| **datahelix** (#57) | `TESTING.md` URI contract and `CANON_URI_RE`, `sec5`, `tests/contracts/test_cappella_expects_canon.py`, `tests/platform/*` (synthetic URIs) → `dhlx://`; `tests/conftest.py` prefix + `hippo_core` import; certification fixtures (`aperture_control_plane.yaml`, `portal_schema.yaml` annotations and imports, `manifest.yaml` `schema_min_hippo_core`); recipe `nginx-auth.conf` header (Q2); recipe and compose `VITE_HIPPO_*` (Q5); Canon `hippo_fields` and Cappella `hippo_poll` (Q7); Canon's `hippo.reference_loaders` entry-point block (Q4); compose Postgres user/db `hippo` (cosmetic); bump the Mosaic + Aperture pins and record the new certified pair. ADR-0006 mentions `X-Hippo-Actor`; add a dated note pointing here rather than editing the decision. |
| **mosaic-demo-small** (BU-Neuromics) | `schemas/demo.yaml` annotations and `hippo_core` import; evals and `exon/` GraphQL queries (Q3). Prose in `openspec/` can stay. |
| **brainbank-hippo-schema** | No contract change (it uses none). Repo rename is Q8. Prose ("when we adopt hippo") can be updated whenever. |
| **linkml-data-gen**, **linkml-modeler-app** | Nothing beyond Q8 (data-gen's test path points at `brainbank-hippo-schema`). Modeler's `hippo.yaml` is a test filename. |

### Sequencing

1. **Ratify this ADR** and answer Q1–Q8.
2. **Mosaic#228 is done.** It merged as #278 (`f7a741b`, 2026-11-17) and introduced
   `hippo_anchor` / `hippo_manifest`. Those two keys are now in the inventory and naming table
   like any other annotation. Nothing else should add a `hippo_*` name. From ratification on, new
   keys are named `mosaic_*`.
3. **Land the Mosaic rename in v0.16.0, or in a release immediately before it.** v0.16.0 is
   already breaking (raw `*_id(s)` fallback removal), so consumers take one breaking upgrade
   instead of two. Recommendation: **in v0.16.0**, as the last PR before the release is cut.
   Mosaic ADR-0008 (Postgres per-class tables) is scheduled right after v0.16.0. Renaming
   `hippo_meta` before that work avoids writing the new `mosaic migrate` code against a table
   that is about to be renamed.
4. **Aperture and Reel** follow in their next release, against Mosaic v0.16.0.
5. **datahelix**: one PR that bumps the pins, updates fixtures, tests, recipes and contract docs,
   and records the certified pair. Rebuild every dev deployment.
6. **External, any time:** register the w3id path; decide the repo rename (Q8).

## Alternatives considered

- **Keep `hippo` for the contract forever** (the #49 status quo). Rejected for the reasons in
  "why not hippo" above: it names a retired component, it collides with domain vocabulary, and
  its namespace never resolved.
- **Rename with a compatibility window** (the original #57 plan: dual-read aliases, a
  `hippo_meta` forward migration, accepting both spellings). Rejected: there is no data to keep
  and no users to protect. The window would add code that only ever runs against fixtures, and
  it would have to be removed again later.
- **Rename everything to `mosaic`**, including the URI scheme and namespace. Rejected: it
  repeats the mistake that made this rename necessary, by naming shared contracts after one
  component. The URI is produced by Canon and parsed by Cappella, and neither is Mosaic.
- **Rename everything to `dhlx`**, including runtime-only annotation keys and tables. Rejected:
  `mosaic_meta` and `mosaic_index` are read only by Mosaic. Putting them under the platform name
  would claim a platform contract that does not exist, and it would make an annotation key look
  portable to other runtimes when it isn't.
- **Use `datahelix` as the CURIE prefix instead of `dhlx`.** A reasonable alternative: it is
  self-explanatory. `dhlx` is shorter in CURIEs (`dhlx:Entity`) and in the URI scheme, and the
  expansion `https://w3id.org/datahelix/` keeps the full name where it matters. Either is
  unregistered today (see Notes).
- **Wait until after mosaic#228.** That has now happened. It added two more keys, which is the
  cost this ADR is meant to stop.

## Open questions

Each has a recommendation. Ratifying accepts the recommendation unless the answer says otherwise.

- **Q1. Is `hippo_core` platform or Mosaic?** It defines `Entity`, `ProvenanceRecord` and the
  other primitives every user schema imports. A second runtime would need the same base.
  However, it ships in the Mosaic wheel, is versioned with Mosaic (`version: 0.6.0`), and the
  certification fixtures track it per Mosaic release (`schema_min_hippo_core`).
  **Recommendation:** name the module `mosaic_core` (and `hippo_ext` → `mosaic_ext`), but mint
  its terms under the platform namespace: `id: https://w3id.org/datahelix/mosaic_core`,
  `default_prefix: dhlx`, classes as `dhlx:Entity`. The term IRIs stay stable if the module ever
  moves to a platform package, and only the `imports:` name would change.
- **Q2. Who owns the actor header?** Today it is `X-Hippo-Actor`, read by Mosaic middleware
  (whose docstring already says `X-Mosaic-Actor`) and written by the recipe nginx per ADR-0006.
  Under `sec6`, Bridge is the sole PEP and every component behind it trusts the identity it
  injects. **Recommendation:** platform-owned, `X-Dhlx-Actor`. Mosaic reads it; Bridge and the
  recipe proxy write it; Canon and Cappella read it when they gain auth.
- **Q3. GraphQL `hippoSchema` / `hippoEntityType`.** These expose Mosaic's own LinkML type model
  (Mosaic ADR-0009). Aperture already treats them as an optional, Mosaic-specific enrichment
  over a conformant endpoint (Aperture ADR-0017), and Reel reads them for grounding.
  **Recommendation:** `mosaicSchema` / `mosaicEntityType`. A neutral name like `schema` reads
  badly next to GraphQL's own `__schema`, and a `dhlx` name would claim a platform contract
  that Aperture deliberately doesn't depend on.
- **Q4. End ADR-0004's deprecation window now?** ADR-0004 kept `import hippo`, the `hippo` CLI,
  `hippo.*` entry-point groups, the `HIPPO_*` env fallback and the `hippo.yaml` fallback, and
  gated removal on "a future ADR". **Recommendation:** remove all of them in the same Mosaic
  release, for the same no-users reason. Record it as a short Mosaic ADR that cites this one,
  because the window is Mosaic's decision. Besides Mosaic's own `pyproject.toml`, one
  registration outside Mosaic uses the legacy groups: Canon's `pyproject.toml` registers under
  both `hippo.reference_loaders` and `mosaic.reference_loaders`. Drop its `hippo.*` block in the
  datahelix PR. Cappella registers none.
- **Q5. Aperture's `VITE_HIPPO_*` config vars.** Aperture is backend-agnostic (any conformant
  GraphQL endpoint), so `VITE_MOSAIC_*` would be wrong too. **Recommendation:**
  `VITE_GRAPHQL_URL` / `VITE_CONTROL_PLANE_URL`, matching Aperture's other unprefixed vars
  (`VITE_WORKFLOWS`, `VITE_NAV`).
- **Q6. Mosaic error codes.** Five codes carry `HIPPO_`; the rest of Mosaic's codes are
  unprefixed (`INVERSE_SLOT`, `NOT_PREDICATE_FILTERABLE`). **Recommendation:** drop the prefix
  instead of renaming it to `MOSAIC_`.
- **Q7. Canon `hippo_fields` and Cappella `hippo_poll` / `hippo:` config section.** These are each component's own config
  vocabulary, naming the system they write to or poll. **Recommendation:** `mosaic_fields` /
  `mosaic_poll`, and `mosaic:` for Cappella's config section (whose type is already
  `MosaicConfig`), since they target Mosaic specifically. Both are in-tree and undeployed, so the
  cost is the same either way.
- **Q8. Rename `brainbank-hippo-schema`?** Its schema doesn't use the contract, so this is
  cosmetic, and the repo belongs to VA-NCPTSDBB-Bioinformatics. GitHub redirects renamed repos,
  but the recipe Dockerfiles, evals and the published docs site URL would change.
  **Recommendation:** rename to `brainbank-schema` as a separate, owner-approved step, not a
  blocker for this ADR. Update the datahelix recipe `SCHEMA_REPO` args in the same datahelix PR
  or the next one.

## Notes

**Prefix and w3id checks (2026-11-17, nothing registered):**

- **bioregistry.io:** `dhlx` and `datahelix` have no record (`/api/registry/<prefix>` → 404),
  and a search returns no prefix, name or synonym match (`/api/search?q=…` → `[]`). `hippo` also
  has no record.
- **prefix.cc:** `dhlx` and `datahelix` returned 404 ("not found") pages, as did `hippo`. The
  site's TLS certificate has expired, so this result came from a request that skipped
  certificate verification and was not checked against a known-good prefix. Treat it as
  probably free, unconfirmed.
- **w3id.org:** `https://w3id.org/datahelix/` returns 404, and `perma-id/w3id.org` has no
  `datahelix/` directory. The existing `https://w3id.org/hippo/…` namespace also returns 404,
  with no `hippo/` directory, so it never resolved.
- **Registering** `https://w3id.org/datahelix/` is an external step for the user: a PR to
  `perma-id/w3id.org` adding `datahelix/.htaccess`, with redirects to the published schema docs
  (for example the mkdocs site). Optionally register `dhlx` in bioregistry once the namespace
  resolves.
