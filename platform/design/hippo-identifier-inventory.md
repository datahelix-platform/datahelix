# Inventory: remaining `hippo` identifiers (2026-11-17)

Companion to [ADR-0007](./decisions/ADR-0007-retire-hippo-data-contract-identifiers.md) (datahelix#57;
mosaic#124, aperture#35). The ADR decides the names; this file lists every remaining `hippo`
identifier, where it appears, and whether it is a **contract** (crosses a process, wire, disk or
repo boundary, or is read from a user-authored file) or **prose / internal** (docs, comments,
and Python/TS names nobody outside the repo depends on).

## How this was produced

`git grep -i hippo` over each repo, excluding lock files (`uv.lock`, `package-lock.json`) and
excluding **`hippocampus` / `Hippocampus`**. That is a brain region in the brain-bank schema and
its data, not an identifier. Any automated sweep must exclude it too. Counts are **files**
matching each pattern, including prose mentions of that identifier. They are a rough size, not
an edit list.

| Repo | Commit read | Files mentioning `hippo` (code / Markdown) |
|---|---|---|
| datahelix (this repo, excluding submodules) | `ce71fa6` (origin/main) | 307 (165 / 142) |
| mosaic | `f7a741b` (origin/main, **includes #278 / mosaic#228**) | 531 (265 / 266) |
| aperture | `0eb455e` (origin/main) | 107 (58 / 49) |
| reel | `dc1855b` (origin/main) | 16 (1 / 15) |
| VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema | `a2b054c` | 115 (6 / 109); mostly generated `docs/gen/*` |
| BU-Neuromics/mosaic-demo-small | `7399694` | 68 (20 / 48); mostly `openspec/` |
| datahelix-platform/linkml-data-gen | `a34dc39` | 3 (repo-name mentions only) |
| datahelix-platform/linkml-modeler-app | `f716a3c` | 1 (a test fixture filename, `schema/hippo.yaml`) |
| VA-NCPTSDBB-Bioinformatics/ncptsdbb-db-app, datahelix-platform.github.io, datahelix-platform/.github | — | 0 |

## Files per identifier kind

Columns are files per repo. **C** = contract, **P** = prose/internal.

| Kind | Pattern (abridged) | datahelix | mosaic | aperture | reel | bbhs | demo-small | C/P |
|---|---|---|---|---|---|---|---|---|
| LinkML prefix / namespace | `hippo:` prefix, `w3id.org/hippo/`, `default_prefix: hippo` | 1 | 13 | 0 | 0 | 0 | 0 | C |
| Schema module names | `hippo_core`, `hippo_ext` | 7 | 127 | 3 | 10 | 2 | 5 | C (imports) |
| Annotation keys | `hippo_unique\|index\|index_partial\|search\|external_xref\|append_only\|accessor\|namespace\|anchor\|manifest` (+ historical `default`/`immutable`/`computed`) | 6 | 96 | 6 | 0 | 6 | 12 | C |
| Annotation constants | `HIPPO_UNIQUE`, `HIPPO_INDEX`, … `HIPPO_ANNOTATION_PREFIX` | 0 | 12 | 0 | 0 | 0 | 0 | P (code) |
| Tables | `hippo_meta`, `hippo_xref_index` (+ retired `hippo_summary_view`) | 2 | 51 | 0 | 0 | 1 | 1 | C (disk) |
| Entity-URI scheme | `hippo://` | 14 | 0 | 0 | 0 | 0 | 0 | C |
| GraphQL root fields | `hippoSchema`, `hippoEntityType` (+ Aperture `hasHippoSchema`) | 1 | 14 | 23 | 13 | 0 | 48 | C (wire) |
| Entry-point groups | `hippo.storage_adapters`, `.write_validators`, `.schema_packages`, `.reference_loaders`, `.reference_loader_cli` | 12 | 34 | 0 | 0 | 1 | 0 | C (plugin) |
| Env vars (ADR-0004 fallbacks + misc) | `HIPPO_DATABASE_URL`, `HIPPO_CACHE_DIR`, `HIPPO_TUI_TOKEN`, `HIPPO_RECIPE_CACHE`, `HIPPO_TOKEN`, `HIPPO_IMAGE`, … | 9 | 38 | 0 | 0 | 0 | 0 | C (config) |
| Aperture config vars | `VITE_HIPPO_GRAPHQL_URL`, `VITE_HIPPO_CONTROL_PLANE_URL` | 14 | 0 | 12 | 0 | 0 | 4 | C (config) |
| Error codes | `HIPPO_EXT_VALIDATION`, `HIPPO_TREE_ROOT_COLLISION`, `HIPPO_TREE_ROOT_SLOT_COLLISION`, `HIPPO_REQUIRES_UNSATISFIED`, `HIPPO_EXTERNAL_XREF_RANGE` | 0 | 5 | 0 | 0 | 0 | 0 | C (wire) |
| HTTP header | `X-Hippo-Actor` | 4 | 14 | 0 | 2 | 0 | 0 | C (wire) |
| Config files / dirs | `hippo.yaml`, `hippo.yml`, `~/.hippo/` | 5 | 44 | 3 | 0 | 0 | 0 | C (config) |
| Manifest / fixture keys | `hippo_version` (`recipe.yaml`), `schema_min_hippo_core` | 4 | 20 | 2 | 0 | 0 | 2 | C |
| Package / module / CLI / SDK names | `import hippo`, `src/hippo`, `hippo` console script, `hippo serve`, `hippo_client`, `HippoClient` | 82 | 207 | 9 | 0 | 0 | 0 | mostly P; see below |
| Canon / Cappella vocabulary | `hippo_fields`, `hippo_field`, `hippo_reference`, `hippo_poll` | 33 | 7 | 0 | 0 | 0 | 0 | C (rule/workflow YAML) |
| Tree-root class | `_HippoInstanceBundle` | 0 | 6 | 0 | 0 | 0 | 0 | P (synthetic) |
| Repo name | `brainbank-hippo-schema` | 8 | 5 | 0 | 0 | 7 | 4 | P (URL) |

## Contract identifiers, by kind

### Namespace / prefix

- **mosaic**: `src/mosaic/schemas/hippo_core.yaml`, `hippo_ext.yaml` and `recipe_manifest.yaml`
  declare `hippo: https://w3id.org/hippo/` and `default_prefix: hippo`, with schema ids
  `https://w3id.org/hippo/{hippo_core,hippo_ext,recipe_manifest}`. Every `class_uri` and slot
  URI in those schemas expands to `w3id.org/hippo/`. The other matches are design docs and tests.
- **datahelix**: `tests/conftest.py:138` builds an overlay with `"hippo": "https://w3id.org/hippo/"`.
- **brainbank-hippo-schema** uses its own prefix (`https://w3id.org/VA-NCPTSDBB/brainbank/`) and
  **does not use the hippo namespace**.
- `https://w3id.org/hippo/` is **not registered** with w3id (404). It never resolved.

### Schema module names (`hippo_core` / `hippo_ext`)

- **mosaic**: the two schema files, their loaders (`_hippo_core_resource_path`,
  `_HIPPO_CORE_IMPORT_SCHEMA`, `HIPPO_CORE_SCHEMA_URI`, `include_hippo_core_import`), and
  `reference_hippo_core.md` / `reference_hippo_ext.md` design docs; 127 files in total.
- **datahelix**: `certification/fixtures/bootstrap/schema/aperture_control_plane.yaml` and
  `portal_schema.yaml` (`imports: [hippo_core]`), `tests/conftest.py`, plus docs.
- **mosaic-demo-small**: `schemas/demo.yaml` imports `hippo_core`.
- **aperture / reel**: prose and fixture descriptions only (for example `certIntrospection.json`
  descriptions that mention `hippo_core`).

### Schema annotation keys

The runtime matches on the prefix `HIPPO_ANNOTATION_PREFIX = "hippo_"`
(`mosaic/src/mosaic/linkml_bridge.py:59`) and validates the keys against `hippo_ext.yaml`.
**Live keys** (declared in `hippo_ext.yaml` at `f7a741b`):

| Key | Level | Since |
|---|---|---|
| `hippo_unique` | slot | — |
| `hippo_index` | slot | — |
| `hippo_index_partial` | slot | — |
| `hippo_search` | slot | — |
| `hippo_external_xref` | slot | issue #48 |
| `hippo_append_only` | class | — |
| `hippo_accessor` | class | — |
| `hippo_anchor` | class | **new in #278 / mosaic#228** (ADR-0014 D5) |
| `hippo_manifest` | class | **new in #278 / mosaic#228** (ADR-0014 D5) |
| `hippo_namespace` | — | — |

Historical names that appear only in docs and the CHANGELOG: `hippo_default`, `hippo_immutable`,
`hippo_computed`, `hippo_summary_view`.

Where the keys are used: Mosaic tests and docs (96 files); datahelix certification fixtures
(`hippo_index`, `hippo_search`); mosaic-demo-small `schemas/demo.yaml` (`hippo_search: fts5`,
`hippo_index`, `hippo_accessor`); brainbank-hippo-schema prose only (for example
`person.yaml`: "Gets hippo_index later"); Aperture introspection fixture descriptions.

### Tables

- `hippo_meta`: version / provenance / installed recipes / reference versions. Created in the
  Postgres adapter (`postgres_adapter.py:1171`) and the SQLite adapter; 51 Mosaic files, mostly
  docs and tests.
- `hippo_xref_index`: external-reference side table (`core/storage/xref.py`, both adapters).
- `hippo_summary_view`: retired (Mosaic sec9 decision 9.4.A); docs only.

### Entity-URI scheme (`hippo://`)

**datahelix only, and no production code produces it:**

- Contract docs: `TESTING.md` (4 places including `CANON_URI_RE`) and
  `platform/design/sec5_integration_test_strategy.md`.
- Tests: `tests/contracts/test_cappella_expects_canon.py`; `tests/platform/{conftest,test_canon_platform,test_cli_integration,test_cross_component,test_mosaic_canon,test_round_trip}.py`
  (the shim in `tests/platform/conftest.py` synthesizes `hippo://<type>/<uuid>`);
  `canon/tests/integration/test_integration.py` (mock entities).
- Canon openplan/openspec docs (3 files).
- Mosaic, Aperture, Reel: **0 occurrences**. Mosaic's MCP resources already use `mosaic://`
  (`mosaic://capabilities`).

### GraphQL fields

- **mosaic** defines `hippoSchema` and `hippoEntityType` (`graphql/resolvers.py:1854,1860`). #278
  added `abstract` / `parent` / `kinds` to them.
- **aperture**: `web/src/data/introspection.ts` (`HIPPO_SCHEMA_QUERY`, `hasHippoSchema`),
  `capabilities.ts`, `schemaModel.ts`, and introspection fixtures (23 files).
- **reel**: `src/reel/planner/capabilities.py` (the only code file); design docs.
- **mosaic-demo-small**: evals and `exon/` queries (48 files, mostly openspec).
- **datahelix**: 1 doc.

### Entry-point groups

- **mosaic** `pyproject.toml` dual-registers all five `hippo.*` groups alongside `mosaic.*`
  (ADR-0004), and its discovery code reads both.
- **datahelix** `canon/pyproject.toml:49` registers `hippo.reference_loaders` (and
  `mosaic.reference_loaders`). The rest of the 12 datahelix files are docs.
- **brainbank-hippo-schema**: one doc mention.

### Env vars and config keys

- **mosaic**: `config/env.py` falls back from `MOSAIC_<X>` to `HIPPO_<X>` with a
  `DeprecationWarning`. Named in code and docs: `HIPPO_DATABASE_URL`, `HIPPO_CACHE_DIR`,
  `HIPPO_TUI_TOKEN`, `HIPPO_RECIPE_CACHE`, `HIPPO_DB_PASSWORD`, `HIPPO_CONFIG`, `HIPPO_DIR`.
  Config-file fallback: `LEGACY_CONFIG_FILENAMES = ("hippo.yaml", "hippo.yml")`
  (`config/loader.py:25`). Reference data dir: `~/.hippo/data` (`cli/commands/reference.py:145`).
- **aperture**: `VITE_HIPPO_GRAPHQL_URL`, `VITE_HIPPO_CONTROL_PLANE_URL` (`web/src/config`, App,
  ControlPlaneContext); default backend config path `./hippo.yaml` (`src/aperture/config/settings.py`,
  `backends/mosaic_sdk.py`).
- **datahelix**: `deploy/recipes/demo/entrypoint.sh` (VITE vars), `certification/compose/*`
  (VITE var; Postgres user/password/db `hippo`), Cappella `HIPPO_TOKEN` (docs and
  `tests/test_config.py`), `HIPPO_API_TOKEN` in docs, `HIPPO_IMAGE` in a comment noting its
  rename (`certification/scripts/run_composition.sh`).
- **Recipe manifest**: `hippo_version` key in Mosaic's `recipe_manifest.yaml` and
  `core/recipe/dataclasses.py`. **Certification**: `schema_min_hippo_core` in
  `certification/fixtures/bootstrap/manifest.yaml`. `certification/compatibility.json` carries
  `"hippo"` as a historical component-line name (ledger history, leave as is).

### Error codes

All five are in Mosaic: `linkml_bridge.py:341,481,513`, `core/loaders/discovery.py:384`, plus
`HIPPO_EXTERNAL_XREF_RANGE`. Other Mosaic codes are unprefixed (`INVERSE_SLOT`).

### HTTP header

`X-Hippo-Actor`: Mosaic `core/middleware.py:13` (`ACTOR_HEADER = "x-hippo-actor"`, while the
docstring already says `X-Mosaic-Actor`) and the CORS allow-list in `api/factory.py`. datahelix
`deploy/recipes/solo/nginx-auth.conf` (4 `proxy_set_header`), its README, platform `INDEX.md`
and ADR-0006. Mosaic design sec3/4/8 and appendix B; Reel `CLAUDE.md` and
`design/platform-alignment.md`.

### Canon / Cappella vocabulary (datahelix in-tree)

- Canon sidecar rule key `hippo_fields` (`canon/src/canon/ingestion/sidecar.py:24`,
  `pipeline.py`); docs and tests (33 files together with Cappella). `hippo_reference` appears
  only in Canon openplan YAML and a proposal.
- Cappella trigger type `hippo_poll` (`cappella/src/cappella/config.py:50`;
  `HippoPollHandler` / `HippoPollConfig` / `HippoPollState`), user guide and workflows docs.
- Cappella config section `hippo:` (`cappella/src/cappella/config.py:94`, a `MosaicConfig`
  holding the URL and `token: ${HIPPO_TOKEN}`; see `cappella/tests/test_config.py:69`), and the
  trigger event source string `hippo:<entity_type>` (`triggers/engine.py:295`).

### Package / module / CLI names

- **mosaic**: `src/hippo/__init__.py` (import-alias shim), the `hippo` console script
  (`mosaic.cli.compat:legacy_main`), and the wheel's `packages = ["src/mosaic", "src/hippo"]`.
  **Public SDK parameter:** `create_app(hippo_client=…)` (`api/factory.py:74`),
  `create_mcp_app(hippo_client=…)` / `create_mcp_server(hippo_client=…)`. The rest is internal
  (`hippo_client` locals and fixtures, `HippoError`, `HippoConfig`, `HippoTUIApp`,
  `HippoCollection`, `_hippo_*` helpers, `tmp_hippo` / `hippo_workspace` test fixtures).
- **datahelix** (internal): Canon `resolver/hippo_client.py`, `HippoHttpClient`,
  `HippoClientProtocol`, `_NullHippoClient`; test shims `_HippoShim`, `MockHippo`,
  `FakeHippoClient`, `hippo_shim`; `HippoQueryClient` and `HippoSdkBackend` in docs.
- **aperture** (internal): `HippoSource` / `hippoSource.ts` / `connectHippoSource`,
  `createHippoStore`, `HippoControlPlaneStore`, `HippoSchema` / `HippoSlotInfo` /
  `HippoReferenceInfo` / `HippoEntityTypeInfo` TS types, and `backend: 'hippo'` in the
  control-plane store. Check whether that last value is persisted before treating it as internal.

### Repo names

`VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema`: its own `mkdocs.yml` (site name and URL);
datahelix `deploy/recipes/{demo,demo-reel}/Dockerfile` (`SCHEMA_REPO`, the clone dir),
`build-dataset.sh`, and demo-reel evals; Mosaic docs (5); mosaic-demo-small (4);
linkml-data-gen `tests/test_generator.py:20` and CONTRIBUTING/README.

## Prose-only mentions, by repo

These need no coordination. Update them in the same PRs where convenient, or leave them as
history (CHANGELOGs, archived openspec changes, and dated design notes should stay as written).

- **datahelix**: Canon design/docs/openplan (~71 md), Cappella docs (~15 md), Bridge design/docs
  (12, "Hippo" as the old component name), `platform/` (19), `proposals/` (8, including
  `hippo-split.md`, which is history), README, CLAUDE.md, FABLE_HANDOFF.md, mkdocs.yml (nav
  label), Makefile and certify.yml comments.
- **mosaic**: `openspec/` (176 md, largely archived changes), `design/` (43), `docs/` (19),
  `plan/` (44), CHANGELOG. Many say "Hippo" for the component's past name.
- **aperture**: `design/` (42 md), web README, ONBOARDING, CLAUDE.md, and comments in
  `introspection.ts` / `store.ts` ("LinkML-on-Hippo").
- **reel**: design docs (12), README, proposals, CLAUDE.md.
- **brainbank-hippo-schema**: `docs/` (104, mostly generated `docs/gen/*` class pages plus
  `doc2-hippo-migration-extension.md`), DESIGN, README, CHANGELOG; schema comments in `core.yaml`
  and `brainbank.yaml` ("when we adopt hippo").
- **mosaic-demo-small**: `openspec/` (45), README, CONVERSATIONAL-QUERY.md,
  APERTURE_EXON_CONTRACT.md.
