# ADR-0004: The `ide` recipe develops Aperture and Mosaic live behind one gateway

- **Status:** Accepted
- **Date:** 2026-08-21
- **Deciders:** labadorf, design session
- **Tracking issue:** [#74](https://github.com/datahelix-platform/datahelix/issues/74) (deliberation; closed at ratification — implementation tracked in [#75](https://github.com/datahelix-platform/datahelix/issues/75))
- **Related:** [`proposals/deployment-recipes.md`](../../../proposals/deployment-recipes.md) decisions 1.9 / 1.10 / §2.2 / §4.3 (this ADR **amends 1.9**); [ADR-0001](./ADR-0001-certified-frontier-composition.md) (deploy gate — `ide` is exempt); Aperture ADR-0034 (runtime endpoint injection); [datahelix-platform/aperture#54](https://github.com/datahelix-platform/aperture/pull/54) (Node 26 toolchain pin)

## Context

The platform ships two container recipes today: `solo` (single-container production MVP) and
`demo` (`solo` plus a baked synthetic dataset). `proposals/deployment-recipes.md` decision 1.9
designed a third — `ide`, the development environment — and made it explicitly exempt from the
ADR-0001 deploy gate on the grounds that "ADR-0001 governs deployment, not development." It was
never implemented.

In its absence, front-end iteration was done by hand: build `aperture/web/dist` on the host,
then bind-mount it over the SPA baked into the `demo` image using an **untracked**
`docker-compose.dev-aperture.yml`. That loop has four seams, and three of them fail silently:

1. **Stale `dist/`** — the browser shows the last build, not the current edit.
2. **Container started without the overlay** — nginx serves the certified bundle instead of the
   local build, with no error anywhere.
3. **Host toolchain on an unpinned Node** — the container in that loop runs *only nginx*; it has
   no Node at all, so every build and test ran on whatever the host happened to have.
4. **`npm run build` deletes `config.js`**, which the image entrypoint only regenerates on
   container start, so a rebuild can leave the app with no data-plane endpoint.

All four were hit in a single session (2026-08-21). The visible cost was an afternoon and a
false diagnosis — a completed fix was believed lost because the running container was serving
the baked bundle — plus a 26-test failure that turned out to be host Node 25 shadowing jsdom's
`localStorage`, unrelated to the code under change.

Decision 1.9 as written would not have prevented any of it. Its service table lists `aperture`
as a **published image**, and the inner loop in §2.2 is schema iteration ending in "Reload
Aperture — introspection picks up the new types." The recipe addresses Mosaic and schema
iteration; front-end iteration is out of its scope by construction.

That gap matters more than it looks, because Aperture and Mosaic are developed as **one unit**:
a given defect may legitimately be fixed on either side of the GraphQL seam. When one side has a
sub-second loop and the other needs a rebuild, the loop quality — not the design — starts
deciding where code lands.

**The question:** what shape must `ide` take so that a change to *either* component is visible
immediately, without a rebuild, while still exercising the same-origin arrangement that
production uses?

## Decision

The platform will implement `deploy/recipes/ide/` as a **compose recipe in which both
components can run from source with live reload, behind a single nginx gateway**:

- **`gateway` (nginx)** publishes one port and routes exactly as `solo` does: `/` → Aperture,
  `/graphql` + REST + `/docs` → Mosaic. One URL for everything.
  (This originally also routed `/modeler/`; [ADR-0005](./ADR-0005-drop-linkml-modeler-from-recipes.md)
  removed the Modeler from every recipe. The rest of this ADR stands.)
- **Profile `dev-aperture` (new — this is the amendment):** `/` proxies to a **Vite dev server**
  running Aperture from the source checkout, with HMR. The gateway must proxy the HMR
  **websocket**, not only HTTP. Without the profile, the default remains the published Aperture
  image exactly as decision 1.9 specified.
- **Profile `dev-mosaic`:** Mosaic built from the source checkout with `--reload`, as 1.9
  already allowed.
- Aperture keeps **`VITE_HIPPO_GRAPHQL_URL=/graphql`** (relative). The browser therefore sees a
  same-origin data plane in development, identical to `solo` (decision 1.3), and no CORS is
  involved anywhere in the stack.

> **Note (2026-11-20, [ADR-0007](./ADR-0007-retire-hippo-data-contract-identifiers.md)):** The
> Aperture env var named here is renamed `VITE_HIPPO_GRAPHQL_URL` → `VITE_GRAPHQL_URL` (Q5;
> aperture#35), and the `ide` recipe sets the new name (datahelix#57). The decision itself is
> unchanged.

Everything else in decision 1.9 stands unchanged. This ADR adds the `dev-aperture` profile and
the obligation that the gateway carry the HMR websocket.

## Consequences

**What becomes true**

- Front-end changes appear in sub-second HMR; Mosaic Python changes reload in about a second;
  LinkML schema changes remain restart-on-migrate (`make migrate`). The three loops a platform
  developer actually uses are all live, and none requires a rebuild.
- The relative-`/graphql` contract is exercised **in development**, not only in production.
  Development stops being a topology special case, which is what allowed the `config.js` and
  overlay failures above to be invisible.
- The dev toolchain's Node version is pinned **by the recipe** rather than by whatever is on the
  host — the root cause of the 26-test failure. The Vite service tracks Aperture's `engines`
  floor (`>=26` as of aperture#54).

**New obligations**

- **The gateway must proxy Vite's HMR websocket.** This is the recipe's one fragile seam: with
  wrong upgrade headers the page still loads fine and HMR silently degrades to nothing, which is
  the same class of invisible failure this ADR exists to eliminate. The recipe's CI boot test
  must therefore assert the **websocket**, not merely an HTTP 200.
- `ide` remains **exempt from the deploy gate** (decision 1.10) and must never serve real data.
  It builds from source by design; nothing it produces is a certified artifact.
- `ide` is **local-development only** (decision 1.9, §4.3). The Modeler's File System Access
  loop requires browser and containers on one machine. Devcontainers stay deferred.

**Follow-on**

- The untracked `docker-compose.dev-aperture.yml` is **superseded** and should be deleted when
  `ide` lands, so there is one documented loop rather than a committed recipe plus a private
  overlay.
- The `dist/` bind-mount path retains one legitimate use — verifying the **production bundle**
  (minified, no dev-server semantics) before trusting it. That is a distinct job from
  iterating, and should be documented as such rather than as the default loop.

## Alternatives considered

**Vite as the entry point, no gateway.** Vite serves the app and proxies `/graphql` to the
Mosaic service directly. Genuinely simpler — no websocket proxying to get wrong — and verified
in session: Vite ready in 171 ms, proxied GraphQL returning real counts from the running `demo`
dataset. **Rejected** because the Modeler would not share the origin, making combined
schema-plus-frontend sessions clumsy, and because the recipe would stop "feeling identical to
`solo`", which is decision 1.9's stated goal for muscle-memory transfer. Retained as the
documented fallback if the websocket proxy proves troublesome in practice.

**Keep the bind-mounted `dist/` overlay as the loop.** **Rejected**: it *is* the loop whose four
silent seams caused the incident. It also requires a host toolchain, which reintroduces the Node
skew independently of anything else.

**Devcontainer.** **Rejected/deferred**, consistent with the proposal (§4.3, "devcontainer
deferred entirely"). It pins the toolchain only for tooling that actually runs inside it — the
session's failure came from a host terminal, which a devcontainer would not have intercepted —
and `docker-outside-of-docker` resolves bind-mount paths against the host, which would silently
break the recipes' relative mounts (an empty mount renders as a blank app, no error).

**Run the whole loop on the host, no containers.** **Rejected**: the Mosaic + SQLite + nginx
same-origin seam is what makes the stack behave like a deployment. Dropping it reintroduces CORS
and makes development diverge from production in exactly the way this ADR is closing.

## Notes / open sub-questions

Probes to run before the recipe is considered done:

- **`PYTHONPATH` shadowing for `dev-mosaic`.** Mounting `mosaic/src` over the pinned image's
  installed package should let the source win; the platform `Makefile` already uses
  `PYTHONPATH := mosaic/src:…`. Precedence over the image's `site-packages` must be boot-tested,
  not assumed.
- **File watching over bind mounts on WSL2.** Vite may require `usePolling`, which costs CPU and
  is a common cause of "HMR stopped working". Test on the real filesystem.
- **Seed data.** Decide whether `ide` seeds from the `demo` recipe's dataset generator or from
  `mosaic init` plus the `./project/seed/` convention 1.9 mentions.
- **Stale numbering in the proposal.** §1.11 predicted this recipe family would ratify as
  "platform ADR-0002"; that number is taken (metapackage + extras). The broader ratification of
  decisions 1.1 / 1.4 / 1.10 — recipe home, image-not-source for production recipes, gate
  applicability — remains outstanding and needs its own ADR. This ADR covers only the `ide`
  shape.
