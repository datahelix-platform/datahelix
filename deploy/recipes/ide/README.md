# DataHelix `ide` — the development environment

Aperture and Mosaic, either or both running **live from your source checkout**,
behind one nginx gateway on one port. Designed in
[`proposals/deployment-recipes.md`](../../../proposals/deployment-recipes.md)
§2.2 / decision 1.9, amended by
[platform ADR-0004](../../../platform/design/decisions/ADR-0004-ide-recipe-live-development-loop.md).

> **Not a deployment.** `ide` is exempt from the ADR-0001 deploy gate because it
> builds from source; nothing it produces is a certified artifact. No auth, no
> gate, no pins to honour. Never point it at real data — use `solo` for that.

## Quickstart

```bash
cd deploy/recipes/ide
make dev      # both components live from source
open http://localhost:8080
```

The first `make dev` installs Aperture's dependencies into a named volume
(30–60s, `make logs-web` to watch). Every start after that is immediate.

## The four ways to run it

| Command | Aperture | Mosaic | Use when |
|---|---|---|---|
| `make up` | pinned image | pinned image | you want a known-good baseline to compare against |
| `make dev` | **source, HMR** | **source, auto-reload** | changing either side, or both |
| `make dev-web` | **source, HMR** | pinned image | front-end only — the common case |
| `make dev-api` | published image | **source, auto-reload** | backend only |

All four serve the same URLs, so nothing in the browser changes when you switch:

```
:8080  /            → Aperture
       /graphql     → Mosaic GraphQL (bearer token injected by the gateway)
       /health      → liveness
       /docs /redoc /openapi.json → FastAPI docs
```

`make down` stops everything. `make clean` also drops the `node_modules`
volume, forcing a clean reinstall.

## The inner loops

**Front-end.** Edit anything under `aperture/web/src/` and the browser updates
without a reload — Vite HMR, sub-second. No build, no restart, no bind-mounted
`dist/`.

**Mosaic.** Edit anything under `mosaic/src/` and uvicorn reloads itself — no
command, no restart, about a second.

This works because the container runs the pinned Mosaic *image* — so every
runtime dependency is already installed — with your checkout mounted at `/src`
and `PYTHONPATH=/src` shadowing the installed package. `import mosaic` resolves
to `/src/mosaic/__init__.py`, not the image's `site-packages`, and
`--reload-dir /src` points the watcher at that same tree.

`make reload-api` remains as a manual restart for changes the watcher does not
see — `mosaic.yaml` itself, or anything outside `/src`.

> Getting here took two upstream fixes, both surfaced by this recipe.
> datahelix-platform/mosaic#171: `--reload` used to `exit(1)`, because `serve` handed
> uvicorn an app *object* where reload requires an import string.
> datahelix-platform/mosaic#174: with that fixed, uvicorn defaulted its watch
> directory to cwd — which must stay `/project`, since `mosaic.yaml` resolves
> `schema_path` and `database_url` against it — so the reloader watched a tree
> containing no `*.py` and silently never fired. **Both fixes are newer than
> the v0.13.0 image**, so auto-reload works only on the source profile, not
> `make up`.

**Schema.** Edit `project/schemas/*.yaml`, then:

```bash
make migrate      # additive DDL + restart the API so it re-reads the schema
```

Additive changes only (new classes, attributes, enums) — Mosaic's v0.1 model is
restart-on-migrate. Removals and renames are not auto-applied; plan those with
`mosaic schema safe-deploy` first. `make migrate` finds whichever mosaic
service is running, so it works in every mode.

**Seed data.** Drop LinkML-native instance bundles into `project/seed/`, then:

```bash
make seed         # ingests every *.yaml there; idempotent on `id`
```

Top-level keys are Mosaic's *ingest accessors* — snake_case of the class plus
"s" (`Project` → `projects`). Irregular plurals need a `mosaic_accessor`
annotation on the class; the `demo` recipe's `remap_accessors.py` shows the
general case.

Two sharp edges worth knowing, both of which cost time to find:

- **`ingest --config` is not the deployment config.** It means *loader* config
  (CSV/SQL column mappings). The schema comes from `--validate-schema`; without
  it, ingest validates against the bundled default schema and rejects your
  bundle with "Additional properties are not allowed". `make seed` passes it
  for you.
- **`ingest` writes identity to an `id` column**, not to the schema's declared
  identifier slot. A schema whose identifier is `project_id` browses fine but
  cannot be seeded ("table Project has no column named id"). Hence the example
  schema names its identifiers `id`. Reported upstream.

To edit schemas on a canvas instead of by hand, run the LinkML Modeler
separately against `project/schemas/` — it is deliberately not part of any
recipe (ADR-0005), and it reads your host filesystem either way.

## Verifying the production bundle

HMR is for iterating. It is not what ships: the dev server has different module
semantics, no minification, and no `tsc` gate. Before trusting a change, check
the real artifact:

```bash
cd ../../../aperture/web
docker run --rm -v "$PWD":/app -w /app node:26 npx vite build   # or npm run build
cd -
make up            # serves the published image...
```

...or build the Aperture image itself and point the recipe at it:

```bash
docker build -t aperture:local ../../../aperture/web
APERTURE_VERSION=local make up   # with the image retagged accordingly
```

These are two distinct jobs — iterate with `make dev`, verify with a real
build — and conflating them is what made the pre-`ide` loop unreliable: a
bind-mounted `dist/` looked like the production bundle but silently served
whatever was last built, by whatever toolchain happened to be on the host.

## Why the endpoint is relative

Aperture is configured with `VITE_GRAPHQL_URL=/graphql` — a **relative**
path, resolved by the browser against the gateway's origin. That is the same
seam `solo` uses in production, which means:

- No CORS configuration exists anywhere in the stack, in dev or in prod.
- Development is not a topology special case. The arrangement you debug is the
  arrangement you ship.

Overriding it with an absolute URL will reintroduce CORS, which Mosaic
deliberately does not serve.

## Ports

`IDE_PORT` (default 8080) changes the published port, and the Vite dev server
follows it automatically — Vite listens on `IDE_PORT` so its HMR client's port
assumption always matches the public origin, at any port:

```bash
IDE_PORT=9090 make dev
```

## Layout

```
docker-compose.yml                 profiles: {aperture,mosaic}-{image,source}
gateway/default.conf.template      envsubst'd; upstreams swap per profile
example-project/                   scaffold copied to ./project by `make init`
project/                           your deployment state (gitignored)
```

The **project directory** holds `mosaic.yaml`, `schemas/`, and
`data/mosaic.db`. `make init` creates it from the example on first run; point
`PROJECT_DIR` at any path to work on a different project. `MOSAIC_SRC` and
`APERTURE_WEB` override the source checkouts if yours live elsewhere.

## How the profile pairs work

Each component has two mutually exclusive compose profiles — `<component>-image`
and `<component>-source` — and the gateway's upstream is set to match by the
Makefile. Both variants of a component are interchangeable from the gateway's
point of view, so `gateway/default.conf.template` has no per-profile branching.

Two details worth knowing if you edit the gateway config:

- Upstreams resolve at **request** time through Docker's embedded DNS
  (`resolver 127.0.0.11`), not at startup. With a literal hostname in
  `proxy_pass`, nginx resolves once at boot and exits if the name is missing —
  the gateway could then only start with every profile running.
- The `/` block carries websocket upgrade headers and a 7-day read timeout.
  Both are required for HMR and inert for the static-image case. Get them wrong
  and the page still loads perfectly while HMR silently does nothing — which is
  exactly the class of invisible failure ADR-0004 exists to remove.

## CI

`.github/workflows/ide-recipe.yml` boots both jobs on every change to this
directory, plus nightly. The `live` job asserts the **HMR websocket upgrades
(101)** and that a source edit actually propagates — not merely that pages
return 200. A broken HMR proxy serves every path perfectly and just stops
updating, so only the websocket assertion catches it.

## Not included

- **LinkML Modeler** — not routed, and not coming: platform ADR-0005 removed it
  from every recipe (it was wired into nothing, was the only from-source build
  in a production recipe, and was the last pin on EOL Node 20). `solo` dropped
  it too. Run it yourself against `project/schemas/` if you want the canvas —
  it reads your host filesystem either way.
- **Deploy gate** — deliberately absent (decision 1.10). There is no
  `make gate` and no `check_pins.py` here by design.
