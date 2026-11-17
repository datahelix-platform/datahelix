# ADR-0007: Retire the `hippo` data-contract identifiers: per-component namespaces under `w3id.org/datahelix/`, `dhlx://` entity URIs, `mosaic_*` runtime identifiers

- **Status:** Accepted
- **Date:** 2026-11-17 (proposed and ratified)
- **Deciders:** labadorf (ratified 2026-11-17, including rulings on Q1–Q9)
- **Related:** Mosaic [ADR-0004](https://github.com/datahelix-platform/mosaic/blob/main/design/decisions/ADR-0004-rename-hippo-to-mosaic.md) (Hippo → Mosaic rename and its deprecation window); Mosaic [ADR-0014](https://github.com/datahelix-platform/mosaic/blob/main/design/decisions/ADR-0014-polymorphic-graphql-types-for-abstract-ranges.md) Decision 5 (`hippo_anchor` / `hippo_manifest`); Mosaic `design/sec10_recipes.md` (the recipe manifest, Q9); [ADR-0001](./ADR-0001-certified-frontier-composition.md) (certified frontier); [ADR-0006](./ADR-0006-authenticating-proxy-in-recipes.md) (the `X-Hippo-Actor` header); Bridge [`sec3_api_unification.md`](../../../bridge/design/sec3_api_unification.md) §3.3.2 and [`sec4_auth.md`](../../../bridge/design/sec4_auth.md) §4.5 (the `X-DataHelix-*` headers, Q2); datahelix#57 (umbrella), datahelix#49 (where these were deferred), datahelix#2 (linkml-store); mosaic#124 and aperture#35 (companions), aperture#32; the inventory in [`../hippo-identifier-inventory.md`](../hippo-identifier-inventory.md)

## Context

Mosaic was called Hippo until Mosaic ADR-0004. The rename moved the package, CLI, entry-point
groups, env vars and config file to `mosaic`, and kept `hippo` as deprecated aliases. Then
datahelix#49 adopted Mosaic naming across docs, CI, config and the submodule path, but
deliberately left the **data-contract identifiers** on `hippo`:

> Data-contract identifiers keep the `hippo` spelling: `hippo_core` / `hippo_ext` schemas,
> `hippo_*` annotation keys, the `hippo_meta` table, and legacy `hippo.*` entry-point groups.

The reasons were sound at the time. These identifiers are baked into LinkML schemas, the wire
format and persisted data, and they span several repos. Renaming them is a breaking change, and
it seemed to need a migration path and a compatibility window. datahelix#57 was opened to do it
later, with dual-read aliases and a forward migration of stored data.

Those reasons no longer hold:

1. **There are no users to migrate.** Every deployment is a dev deployment built from demo
   synthetic data (`deploy/recipes/demo`, `demo-reel`, `solo`, `ide`, and the certification
   fixtures). Each one is already rebuilt from source data when it changes; the demo images bake
   the SQLite database at build time. Nothing holds a `hippo_meta` table or a stored `hippo://`
   URI that can't be regenerated.
2. **Waiting makes it more expensive.** New `hippo_*` names keep arriving. Mosaic#228 / #278
   (ADR-0014 Decisions 2–6, merged 2026-11-17 as `f7a741b`) added two class annotations,
   `hippo_anchor` and `hippo_manifest`. Its ADR already says they "become `mosaic_*` under
   datahelix#57". Every feature that adds a key also adds a future rename.
3. **The next Mosaic release is breaking anyway.** Mosaic's `[Unreleased]` section (v0.16.0)
   already contains a breaking change: the raw `*_id(s)` fallback fields are removed for
   references into a family. Landing the rename in the same release means consumers take one
   breaking upgrade instead of two.
4. **1.0 should not ship with a retired product name in its contract.** After 1.0, the same
   rename would need the full deprecation machinery that #57 originally planned.

The inventory turned up two more facts:

- **No production code emits `hippo://`.** The entity-URI scheme exists only in the contract
  docs (`TESTING.md`, `platform/design/sec5_integration_test_strategy.md`), the Canon/Cappella
  contract tests, and a synthetic URI that the platform test shim builds
  (`tests/platform/conftest.py`). Mosaic never produces it, and Aperture neither parses nor
  renders it. Renaming it changes docs and tests only.
- **`brainbank-hippo-schema` does not use the contract.** Its schema imports no `hippo_core`,
  uses no `hippo_*` annotation, and declares its own prefix
  (`https://w3id.org/VA-NCPTSDBB/brainbank/`). `hippo` appears only in the repo name and in
  prose.

The question: **what should each `hippo` identifier become, who owns it, and when do we switch?**

## Decision

**Finish the rename now, before 1.0, in one coordinated breaking change, with no compatibility
window.** Each identifier takes the name of its owner.

### Namespace convention

- **Platform namespace root:** `https://w3id.org/datahelix/`.
- **Each component that defines a vocabulary gets its own path under the root, with its own
  CURIE prefix.** Mosaic's terms go to `https://w3id.org/datahelix/mosaic/` with the prefix
  `mosaic:`. That covers everything now in `hippo_core` and `hippo_ext`: `Entity`,
  `ProvenanceRecord`, the annotation definitions, and so on. Mosaic's schema ids become
  `https://w3id.org/datahelix/mosaic/<schema name>`.
- **Other components follow the same pattern when they first define a schema:**
  `https://w3id.org/datahelix/reel/` with `reel:`, `https://w3id.org/datahelix/cappella/` with
  `cappella:`, and so on. No component defines terms under another component's path.
- **The root stays empty for now. No `dhlx:` CURIE prefix is defined.** Today, every vocabulary
  term has exactly one defining component.
- **Promotion rule:** a term moves into the root only when a second component needs to define
  or use it on equal terms. "Using" here means more than consuming the owner's output. Each move
  gets its own ADR, which defines the root prefix the first time one is needed. Candidates that
  might one day qualify:
  - **Shared provenance terms.** Mosaic's `ProvenanceRecord` and its activity/agent links, if
    Canon or Cappella start writing provenance as peers rather than through Mosaic. Mosaic
    already maps `Entity` to `prov:Entity` and the activity links to `prov:` slots. Promotion
    would most likely add a thin platform profile over PROV rather than move Mosaic's terms.
  - **Workflow-run ↔ entity links** between Cappella (runs) and Mosaic (entities). This
    qualifies if both sides need to assert the relationship rather than only Mosaic storing it.
  - **The deployment-recipe manifest**, if a manifest that composes several components (for
    example the `deploy/recipes/*` stacks, which have no schema today) gets a schema. This is
    separate from Mosaic's schema-recipe manifest; see Q9.

### Where `dhlx` still appears

`dhlx` (from DataHelix) appears **only in the entity-URI scheme**:
`hippo://<EntityType>/<uuid>` → `dhlx://<EntityType>/<uuid>`.

The other cross-component wire contract, the actor header, is platform-owned but takes Bridge's
existing header family instead of `dhlx`: `X-Hippo-Actor` → **`X-DataHelix-Actor`** (Q2, ruled
2026-11-17).

### Mosaic runtime identifiers

Identifiers that only the Mosaic runtime reads or writes become `mosaic_*` / `mosaic.*`:

- the `hippo_*` schema annotation keys the runtime reads (`hippo_index` → `mosaic_index`, …,
  including the new `hippo_anchor` / `hippo_manifest`);
- the internal tables `hippo_meta` and `hippo_xref_index`;
- the legacy `hippo.*` entry-point groups, which are removed because `mosaic.*` already exists;
- the GraphQL `hippoSchema` / `hippoEntityType` queries → `mosaicSchema` /
  `mosaicEntityType` (Q3, ruled 2026-11-17; listed as "probably" before ratification).

**Identifiers whose split was unclear were raised as open questions Q1–Q9.** All nine were
ruled on 2026-11-17; the rulings are recorded under each question below and reflected in the
naming table.

**Migration is "rebuild from the demo data."** There is no dual-read, no read-time alias, no
`hippo_meta` → `mosaic_meta` migration step, and no deprecation window. After the change,
Mosaic reads only the new names. A schema that still uses a `hippo_*` annotation key fails
validation with an error that names the replacement key, so a stale schema fails loudly instead
of being silently ignored.

### Naming table

"Owner" is the component that defines the name. Consumers update when the owner releases.

| Kind | Old | New | Owner | Consumers / where it appears |
|---|---|---|---|---|
| Entity-URI scheme | `hippo://<EntityType>/<uuid>` | `dhlx://<EntityType>/<uuid>` | **Platform** | Canon (the producer per the contract), Cappella (parser), contract tests, `TESTING.md`, `sec5` |
| Actor header | `X-Hippo-Actor` | `X-DataHelix-Actor` (Q2, Bridge's existing name) | **Platform** (Bridge's `X-DataHelix-*` family) | written by recipe nginx / Bridge; read by Mosaic middleware |
| Platform namespace root | — | `https://w3id.org/datahelix/` (**empty; no `dhlx:` prefix**) | **Platform** | none yet; see the promotion rule |
| LinkML CURIE prefix | `hippo:` → `https://w3id.org/hippo/` | `mosaic:` → `https://w3id.org/datahelix/mosaic/` | Mosaic | `hippo_core.yaml`, `hippo_ext.yaml`, `recipe_manifest.yaml` (`default_prefix`); `tests/conftest.py` |
| Schema ids | `https://w3id.org/hippo/hippo_core`, `…/hippo_ext`, `…/recipe_manifest` | `https://w3id.org/datahelix/mosaic/<schema name>` | Mosaic | the `recipe_manifest` id follows Q9 |
| Core schema module | `hippo_core` (the `imports:` name) | `mosaic_core` (Q1) | Mosaic | every user schema's `imports:`; certification fixtures; `tests/conftest.py`; demo-small schema |
| Annotation-vocabulary module | `hippo_ext` | `mosaic_ext` (Q1) | Mosaic | Mosaic only |
| Schema annotation keys | `hippo_unique`, `hippo_index`, `hippo_index_partial`, `hippo_search`, `hippo_external_xref`, `hippo_append_only`, `hippo_accessor`, `hippo_anchor`, `hippo_manifest`, `hippo_namespace` | `mosaic_unique`, `mosaic_index`, … `mosaic_namespace` (same suffixes) | Mosaic | user schemas (certification fixtures, demo-small, recipe overlays), docs |
| Annotation prefix constant | `HIPPO_ANNOTATION_PREFIX = "hippo_"` (and the `HIPPO_*` key constants) | `MOSAIC_ANNOTATION_PREFIX = "mosaic_"` | Mosaic | Mosaic only |
| Metadata table | `hippo_meta` | `mosaic_meta` | Mosaic | Mosaic only (SQLite and Postgres DDL) |
| Xref side table | `hippo_xref_index` | `mosaic_xref_index` | Mosaic | Mosaic only |
| Entry-point groups | `hippo.storage_adapters`, `hippo.write_validators`, `hippo.schema_packages`, `hippo.reference_loaders`, `hippo.reference_loader_cli` | removed (`mosaic.*` is already canonical) | Mosaic | Q4 |
| GraphQL root fields | `hippoSchema`, `hippoEntityType` | `mosaicSchema`, `mosaicEntityType` (Q3) | Mosaic | Aperture (`HIPPO_SCHEMA_QUERY`), Reel (`planner/capabilities.py`), demo-small evals, certification introspection fixtures |
| Error codes | `HIPPO_EXT_VALIDATION`, `HIPPO_TREE_ROOT_COLLISION`, `HIPPO_TREE_ROOT_SLOT_COLLISION`, `HIPPO_REQUIRES_UNSATISFIED`, `HIPPO_EXTERNAL_XREF_RANGE` | drop the prefix (`EXT_VALIDATION`, …) (Q6) | Mosaic | error payloads |
| Recipe-manifest key | `hippo_version` (in `recipe.yaml`) | `mosaic_version` | Mosaic (Q9) | recipe authors, e.g. Aperture's `recipes/aperture-control-plane/recipe.yaml` |
| Tree-root class | `_HippoInstanceBundle` | `_MosaicInstanceBundle` | Mosaic | Mosaic only (synthetic) |
| Aperture config vars | `VITE_HIPPO_GRAPHQL_URL`, `VITE_HIPPO_CONTROL_PLANE_URL` | `VITE_GRAPHQL_URL`, `VITE_CONTROL_PLANE_URL` (Q5) | Aperture | datahelix recipes (`entrypoint.sh`, compose files) |
| Canon / Cappella config vocabulary | `hippo_fields` (sidecar rule key), `hippo_poll` (trigger type), Cappella's `hippo:` config section and `hippo:<type>` event source | `mosaic_fields`, `mosaic_poll`, `mosaic:` (Q7) | Canon / Cappella (in-tree) | rule and workflow YAML, docs |
| Certification fixture key | `schema_min_hippo_core` | `schema_min_mosaic_core` | datahelix | `certification/fixtures/bootstrap/manifest.yaml` |
| ADR-0004 aliases | `import hippo`, the `hippo` console script, the `HIPPO_*` env fallback, the `hippo.yaml` config fallback | removed, in the same release (Q4) | Mosaic | recorded in a short Mosaic ADR |
| Repo name | `VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema` | `brainbank-schema`, later, as a separate owner-approved step (Q8) | VA-NCPTSDBB | datahelix recipe Dockerfiles, evals, linkml-data-gen |

Not in scope: Python identifiers that are not part of a contract (`hippo_client` parameters,
`HippoPollHandler`, `HippoSource`, test fixtures). Rename them when the code around them changes;
the inventory lists them. One exception: `mosaic.api.factory.create_app(hippo_client=…)` and
`create_mcp_app(hippo_client=…)` are public SDK parameters, so they are renamed in the same
Mosaic release. **`hippocampus` is a brain region, not an identifier.** Exclude it from every
sweep.

## Why a separate contract name, and why not "hippo"

A name separate from any one component is warranted only for **contracts that several
components speak as peers**:

- **The entity-URI scheme.** Canon produces entity URIs, Cappella parses them, and Aperture is
  meant to render them. None of these is Mosaic. If another runtime ever implements the
  contract, the URI must not carry the first implementation's name.
- **The actor header** (Q2). The recipe proxy or Bridge sets it; Bridge is the platform's sole
  PEP (`sec6`). Whichever component sits behind them reads it.

The URI scheme takes `dhlx`. The actor header takes the name Bridge's design already gives it,
`X-DataHelix-Actor`, in the `X-DataHelix-*` family that Bridge injects (`-Actor`, `-Roles`,
`-Request-Id`) and strips from inbound requests. So `dhlx` appears only in `dhlx://`. **Vocabulary
terms take neither**, because today each term has exactly one
defining component:

- Mosaic is the only component that defines the core and annotation vocabulary. datahelix#2
  puts `linkml-store` *under* Mosaic as a storage backend, so Mosaic stays the only runtime that
  reads the annotations. Other components consume Mosaic's terms; they don't define them.
- A namespace path per component (`datahelix/mosaic/`, later `datahelix/reel/`, …) states who
  owns each term. Each term can still be promoted to the root, under its own ADR, if a second
  component ever needs it on equal terms. Defining `dhlx:` now would claim a shared vocabulary
  that doesn't exist.
- All the paths sit under one root, so the platform can later register a single w3id directory
  that covers every component.

A separate contract name is **not** warranted for "hippo" specifically:

- "Hippo" is the retired name of one component, not the platform. Keeping it on the contract
  implies that Mosaic owns the contract, and it confuses every reader who meets a "hippo" that
  no longer exists anywhere else.
- `hippo` collides with domain vocabulary in the platform's first deployment, a brain bank
  (`hippocampus`). Every sweep needs a manual exclusion.
- `w3id.org/hippo/` was never registered. It returns 404 today, so the existing namespace never
  resolved, and there is no persistent identifier to preserve.

## Consequences

- One coordinated breaking release per component, then a certified-frontier entry for the new
  pair (ADR-0001). Every dev deployment is rebuilt from demo data, and the new code never opens
  an old database.
- After the change, Mosaic reads only `mosaic_*` keys and `mosaic_meta`. A `hippo_*` key in a
  schema is a validation error that names the replacement, so stale schemas fail loudly.
- Mosaic's terms expand under `https://w3id.org/datahelix/mosaic/`. The root has no terms and no
  prefix until a promotion ADR adds one.
- When Reel, Cappella or another component first defines a schema, it takes
  `https://w3id.org/datahelix/<component>/` and its own prefix. No new ADR is needed for that.
- ADR-0004's deprecation window ends (Q4). The `hippo` CLI, `import hippo` and
  the `HIPPO_*` / `hippo.yaml` fallbacks go away, which removes a class of "which spelling won?"
  bugs.
- Future features name new annotations `mosaic_*` from the start.
- **w3id registration is deferred.** At the user's direction, `https://w3id.org/datahelix/` is
  registered only after a real deployment has been running for a while. Until then, the
  namespace URIs are used unregistered and do not resolve, as `w3id.org/hippo/` never did. This
  is acceptable because LinkML and the runtime treat them as identifiers and never dereference
  them. Registration is an external step for the user, not part of any PR (see Notes).
- datahelix#57's original plan (dual-read aliases, a `hippo_meta` forward migration, a
  deprecation window) is dropped. If any of it is needed after 1.0, it would be a new ADR.

### Per-repo work

| Repo | Work |
|---|---|
| **mosaic** (mosaic#124) | Rename `hippo_core.yaml` / `hippo_ext.yaml` (Q1). Set their ids to `https://w3id.org/datahelix/mosaic/<name>` and the prefix to `mosaic:`, and do the same for `recipe_manifest.yaml` (Q9). Rename the annotation keys and the `HIPPO_*` constants. Rename `hippo_meta` / `hippo_xref_index` in both adapters' DDL. Rename `hippoSchema` / `hippoEntityType` (Q3), the error codes (Q6), `recipe.yaml`'s `hippo_version`, `_HippoInstanceBundle`, and the `create_app` / `create_mcp_app` `hippo_client` parameter. Switch the actor header to `X-DataHelix-Actor` (Q2). Remove the ADR-0004 aliases (Q4). Reject `hippo_*` keys with a hint. Update `design/`, `docs/`, examples and tests. Record a Mosaic ADR that ends ADR-0004's window (Q4), and note on ADR-0014 that Decision 5's keys are now `mosaic_anchor` / `mosaic_manifest`. Add a CHANGELOG `### Upgrading` entry: "rebuild from source data". |
| **aperture** (aperture#35) | Point `HIPPO_SCHEMA_QUERY` and the `hasHippoSchema` capability check at the new GraphQL fields (Q3). Rename the `VITE_HIPPO_*` config vars (Q5). Change the default config path `./hippo.yaml` → `./mosaic.yaml`. Rename `hippo_version` in `recipes/aperture-control-plane/recipe.yaml` (Q9). Regenerate the `web/src/data/testing/*Introspection.json` fixtures. `HippoSource`, `createHippoStore` and `backend: 'hippo'` are internal names, so rename them opportunistically; if `backend: 'hippo'` is persisted in control-plane documents, rename it in the same change. |
| **reel** | Point the `hippoSchema` query in `planner/capabilities.py` at Q3's new name; update docs. |
| **datahelix** (#57) | Move the `TESTING.md` URI contract and `CANON_URI_RE`, `sec5`, `tests/contracts/test_cappella_expects_canon.py` and `tests/platform/*` (synthetic URIs) to `dhlx://`. Update the `tests/conftest.py` prefix (`mosaic:` → `https://w3id.org/datahelix/mosaic/`) and its core import. Update the certification fixtures: `aperture_control_plane.yaml` and `portal_schema.yaml` (annotations and imports), and `manifest.yaml`'s `schema_min_hippo_core`. Change the recipe `nginx-auth.conf` header to `X-DataHelix-Actor` (Q2) and the recipe and compose `VITE_HIPPO_*` vars (Q5). Rename Canon's `hippo_fields` and Cappella's `hippo_poll` / `hippo:` (Q7), and drop Canon's `hippo.reference_loaders` entry-point block (Q4). Rename the compose Postgres user/db `hippo` (cosmetic). Bump the Mosaic and Aperture pins and record the new certified pair. ADR-0006 mentions `X-Hippo-Actor`; add a dated note there pointing here rather than editing the decision. |
| **mosaic-demo-small** (BU-Neuromics) | Update the annotations and core import in `schemas/demo.yaml`, and the GraphQL queries in the evals and `exon/` (Q3). Prose in `openspec/` can stay. |
| **brainbank-hippo-schema** | No contract change, since it uses none. The repo rename is Q8. Prose ("when we adopt hippo") can be updated at any time. |
| **linkml-data-gen**, **linkml-modeler-app** | Nothing beyond Q8 (data-gen's test path points at `brainbank-hippo-schema`). The modeler's `hippo.yaml` is only a test filename. |

### Sequencing

1. **Ratified 2026-11-17**, with Q1–Q9 ruled.
2. **Mosaic#228 is done.** It merged as #278 (`f7a741b`, 2026-11-17) and introduced
   `hippo_anchor` / `hippo_manifest`. Those two keys are in the inventory and the naming table
   like any other annotation. From ratification on, new keys are named `mosaic_*`.
3. **Land the Mosaic rename in v0.16.0, or in a release immediately before it.** v0.16.0 is
   already breaking (it removes the raw `*_id(s)` fallback), so consumers take one breaking
   upgrade instead of two. Recommendation: **in v0.16.0**, as the last PR before the release
   is cut. Mosaic ADR-0008 (Postgres per-class tables) is scheduled right after v0.16.0;
   renaming `hippo_meta` first means the new `mosaic migrate` code isn't written against a table
   that is about to be renamed.
4. **Aperture and Reel** follow in their next release, against Mosaic v0.16.0.
5. **datahelix:** one PR that bumps the pins, updates fixtures, tests, recipes and contract docs,
   and records the certified pair. Rebuild every dev deployment.
6. **Later, outside this change:** register the w3id path once a real deployment has been
   running for a while (deferred); rename `brainbank-hippo-schema` → `brainbank-schema` once its
   owners approve (Q8).

## Alternatives considered

- **Keep `hippo` for the contract forever** (the #49 status quo). Rejected for the reasons in
  "why not hippo" above: it names a retired component, it collides with domain vocabulary, and
  its namespace never resolved.
- **Rename with a compatibility window** (the original #57 plan: dual-read aliases, a
  `hippo_meta` forward migration, accepting both spellings). Rejected: there is no data to keep
  and no users to protect. The window would add code that only ever runs against fixtures, and
  that code would have to be removed again later.
- **A flat platform vocabulary: `dhlx:` → `https://w3id.org/datahelix/`, with Mosaic minting
  `dhlx:Entity`.** This was the first draft of this ADR. Rejected: nothing is shared today, so a
  flat `dhlx:` prefix would put one component's terms in the platform's name. Every later
  component would also mint into the same flat space with no record of who owns what.
  Per-component paths under one root keep ownership explicit, and the promotion rule keeps the
  root for terms that really are shared.
- **Rename everything to `mosaic`**, including the URI scheme. Rejected: it repeats the mistake
  that made this rename necessary, by naming a shared contract after one component. Canon
  produces the URI and Cappella parses it, and neither is Mosaic.
- **Rename everything to `dhlx`**, including the runtime-only annotation keys and tables.
  Rejected: `mosaic_meta` and `mosaic_index` are read only by Mosaic. Putting them under the
  platform name would claim a platform contract that doesn't exist, and would make an annotation
  key look portable to other runtimes when it isn't.
- **`X-Dhlx-Actor` for the actor header** (this ADR's own Q2 recommendation before ratification).
  Rejected 2026-11-17: Bridge's design already names the header `X-DataHelix-Actor`, as part of
  the `X-DataHelix-*` family it injects and strips. A second spelling of the same platform name
  would split that family.
- **Per-component actor headers** (`X-Mosaic-Actor`, `X-Cappella-Actor`, …). Rejected
  2026-11-17: components tell callers apart by the actor *value* (Bridge's `service:` prefix
  convention, e.g. `service:cappella-runner`, sec4 §4.5.2), not by which header carries it. One
  platform header, written only by the PEP, is what lets every component trust it. Per-component
  headers would multiply the names Bridge must strip without carrying any extra information.
- **A namespace outside w3id** (for example a GitHub Pages URL). Rejected: it ties identifiers to
  hosting. The w3id root can be registered later with no identifier changes.
- **Wait until after mosaic#228.** That has now happened. It added two more keys, which is the
  cost this ADR is meant to stop.

## Open questions (ruled 2026-11-17)

Each question is kept as it was asked, with the recommendation made before ratification. The
ruling (labadorf, 2026-11-17) follows each one and is binding.

- **Q1. Module names for Mosaic's schemas.** The namespace is settled above: Mosaic's terms live
  under `datahelix/mosaic/` with `mosaic:`. What remains open is the `imports:` name of the two
  modules, and with it their ids. The candidates are `mosaic_core` / `mosaic_ext` (ids
  `…/mosaic/mosaic_core`, which repeat "mosaic") or `core` / `ext` (ids `…/mosaic/core`).
  **Recommendation:** `mosaic_core` / `mosaic_ext`. The `imports:` name is resolved in the user's
  schema directory, and a bare `core` collides with user files; brainbank-hippo-schema already
  has its own `schema/core.yaml`. The repeated "mosaic" in the id is cosmetic.
  **Ruling (2026-11-17):** `mosaic_core` / `mosaic_ext`, as recommended.
- **Q2. Who owns the actor header?** Today it is `X-Hippo-Actor`, read by Mosaic's middleware
  (whose docstring already says `X-Mosaic-Actor`) and written by the recipe nginx per ADR-0006.
  Under `sec6`, Bridge is the sole PEP, and every component behind it trusts the identity it
  injects. **Recommendation:** the platform owns it, as `X-Dhlx-Actor`. Mosaic reads it; Bridge
  and the recipe proxy write it; Canon and Cappella read it when they gain auth.
  **Ruling (2026-11-17):** **changed.** The header is platform-owned, as recommended, but named
  **`X-DataHelix-Actor`**, not `X-Dhlx-Actor`, to match Bridge's existing design
  (`bridge/design/sec3_api_unification.md` §3.3.2, `sec4_auth.md` §4.5). Bridge injects
  `X-DataHelix-Actor`, `X-DataHelix-Roles` and `X-DataHelix-Request-Id`, and strips every inbound
  `X-DataHelix-*` header from external clients. Components distinguish callers by the actor
  value (for example a `service:` actor such as `service:cappella-runner`), not by
  per-component headers; per-component headers were considered and rejected for that reason
  (see Alternatives). Mosaic's middleware switches from `x-hippo-actor` to
  `x-datahelix-actor`; adopting `-Roles` and `-Request-Id` is Bridge-integration work outside this
  ADR. **Future work, not addressed here:** the on-behalf-of case, where a service (Aperture's
  backend-for-frontend, a Cappella run) acts for a human user. One actor value can name only one
  of them; how both are carried into provenance needs its own decision.
- **Q3. GraphQL `hippoSchema` / `hippoEntityType`.** These expose Mosaic's own LinkML type model
  (Mosaic ADR-0009). Aperture already treats them as an optional, Mosaic-specific enrichment on
  top of any conformant endpoint (Aperture ADR-0017), and Reel reads them for grounding.
  **Recommendation:** `mosaicSchema` / `mosaicEntityType`. A neutral name like `schema` reads
  badly next to GraphQL's own `__schema`, and a `dhlx` name would claim a platform contract that
  Aperture deliberately doesn't depend on.
  **Ruling (2026-11-17):** `mosaicSchema` / `mosaicEntityType`, as recommended.
- **Q4. End ADR-0004's deprecation window now?** ADR-0004 kept `import hippo`, the `hippo` CLI,
  the `hippo.*` entry-point groups, the `HIPPO_*` env fallback and the `hippo.yaml` fallback, and
  left their removal to "a future ADR". **Recommendation:** remove all of them in the same Mosaic
  release, for the same no-users reason. Record the removal as a short Mosaic ADR that cites
  this one, because the window is Mosaic's decision. Outside Mosaic's own `pyproject.toml`, only
  one registration uses the legacy groups: Canon's `pyproject.toml` registers under both
  `hippo.reference_loaders` and `mosaic.reference_loaders`. Drop its `hippo.*` block in the
  datahelix PR. Cappella registers none.
  **Ruling (2026-11-17):** remove the ADR-0004 aliases in the same release, recorded in a short Mosaic ADR,
  as recommended.
- **Q5. Aperture's `VITE_HIPPO_*` config vars.** Aperture is backend-agnostic (it works with any
  conformant GraphQL endpoint), so `VITE_MOSAIC_*` would be wrong too. **Recommendation:**
  `VITE_GRAPHQL_URL` / `VITE_CONTROL_PLANE_URL`, matching Aperture's other unprefixed vars
  (`VITE_WORKFLOWS`, `VITE_NAV`).
  **Ruling (2026-11-17):** `VITE_GRAPHQL_URL` / `VITE_CONTROL_PLANE_URL`, as recommended.
- **Q6. Mosaic error codes.** Five codes carry `HIPPO_`; Mosaic's other codes are unprefixed
  (`INVERSE_SLOT`, `NOT_PREDICATE_FILTERABLE`). **Recommendation:** drop the prefix rather than
  renaming it to `MOSAIC_`.
  **Ruling (2026-11-17):** drop the `HIPPO_` prefix, as recommended.
- **Q7. Canon `hippo_fields`, and Cappella `hippo_poll` and its `hippo:` config section.** Each
  is that component's own config vocabulary, naming the system it writes to or polls.
  **Recommendation:** `mosaic_fields` / `mosaic_poll`, and `mosaic:` for Cappella's config
  section (whose type is already `MosaicConfig`), since they target Mosaic specifically. Both
  components are in-tree and undeployed, so the cost is the same either way.
  **Ruling (2026-11-17):** `mosaic_fields` / `mosaic_poll` / `mosaic:`, as recommended.
- **Q8. Rename `brainbank-hippo-schema`?** Its schema doesn't use the contract, so this is
  cosmetic, and the repo belongs to VA-NCPTSDBB-Bioinformatics. GitHub redirects renamed repos,
  but the recipe Dockerfiles, the evals and the published docs-site URL would change.
  **Recommendation:** rename it to `brainbank-schema` as a separate step that the owner
  approves; it doesn't block this ADR. Update the datahelix recipe `SCHEMA_REPO` args in the same
  datahelix PR or the next one.
  **Ruling (2026-11-17):** rename `brainbank-hippo-schema` → `brainbank-schema` later, as a separate step
  approved by the repo's owners. It doesn't block this ADR.
- **Q9. Who owns the recipe manifest schema (`recipe_manifest.yaml` / `recipe.yaml`, with
  `hippo_version`): Mosaic or datahelix?** The schema lives in Mosaic today, which validates it
  closed and is its only reader. Other components author recipes against it: Aperture ships
  `recipes/aperture-control-plane/recipe.yaml` with `hippo_version: ">=0.11.0"`. Note that
  Mosaic's "recipe" (sec10) is a content-addressed bundle of a LinkML **schema fragment**,
  installed into one Mosaic instance and recorded in `hippo_meta.installed_recipes`. It is not a
  datahelix deployment recipe (`deploy/recipes/*`, the compose stacks), which has no manifest
  schema at all. The two share only a word. **Recommendation:** Mosaic owns it, with id
  `https://w3id.org/datahelix/mosaic/recipe_manifest` and the key `hippo_version` →
  `mosaic_version`. Another component *authoring* a Mosaic recipe is consuming the schema, not
  defining it on equal terms, so the promotion rule doesn't apply. If datahelix later wants a
  manifest for its deployment recipes, that is a new schema. It would sit in the root, under the
  promotion rule and its own ADR, since it would describe several components. It should not
  grow out of Mosaic's schema-recipe manifest. As a lower-priority follow-up, consider renaming
  Mosaic's concept (for example "schema pack") to end the overloaded word. That is outside this
  ADR.
  **Ruling (2026-11-17):** Mosaic owns the recipe manifest schema, as recommended.

## Notes

**w3id registration is deferred** (confirmed at ratification, 2026-11-17). At the user's direction, registering
`https://w3id.org/datahelix/` waits until a real deployment has been running for a while. Until
then, the namespace URIs (`https://w3id.org/datahelix/mosaic/…`) are used unregistered, as
`w3id.org/hippo/` was. When the time comes, registration is a PR to `perma-id/w3id.org` adding
`datahelix/.htaccess`, with one directory covering every component path, plus optionally a
bioregistry entry for each prefix in use. This is an external step for the user, not part of
any PR here.

**Prefix and w3id availability checks (2026-11-17; nothing registered).** These checks were run
while `dhlx` was proposed as a CURIE prefix. That is no longer proposed, but the results still
apply to the scheme and to the root:

- **bioregistry.io:** `dhlx` and `datahelix` have no record (`/api/registry/<prefix>` → 404),
  and a search returns no prefix, name or synonym match (`/api/search?q=…` → `[]`). `hippo` has
  no record either.
- **prefix.cc:** `dhlx` and `datahelix` returned 404 ("not found") pages, as did `hippo`. The
  site's TLS certificate has expired, so this result came from a request that skipped
  certificate verification and was not checked against a known-good prefix. Treat it as
  probably free, but unconfirmed.
- **Note:** `dhlx` is now used only as a URI scheme (`dhlx://`), never as a CURIE prefix, so the
  registry checks below matter only if a root prefix is ever defined (promotion rule).
- **w3id.org:** `https://w3id.org/datahelix/` returns 404, and `perma-id/w3id.org` has no
  `datahelix/` directory. The existing `https://w3id.org/hippo/…` namespace also returns 404,
  with no `hippo/` directory, so it never resolved.
- The `mosaic:` prefix was not checked against bioregistry or prefix.cc. Collisions there
  matter only for identifiers that are published, and nothing is published until registration.
