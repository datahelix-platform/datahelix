# DataHelix `solo` — single-container production MVP

One container, one port: **Aperture** (data explorer) at `/` and **Mosaic**
(`serve --graphql`, SQLite) proxied same-origin at `/graphql` — with a
migrate-on-restart loop for iterating your schema. Designed in
`proposals/deployment-recipes.md` (§2.1).

> **The LinkML Modeler is no longer bundled** (platform ADR-0005). It was
> served at `/modeler/` with a `/cors-proxy/` git relay; both are gone. It was
> wired into nothing — a purely client-side app that reads your *host*
> filesystem, never the container's — while being the only from-source build in
> a production recipe and the last pin on EOL Node 20. **There is now no Node
> in this image at all.** Run the Modeler yourself against your `schemas/`
> directory if you want the canvas; nothing about how it reaches those files
> has changed.

> **Auth is opt-in** (platform ADR-0006). `AUTH_MODE=none` is the default and
> is the posture described above: run it on localhost, behind a VPN/SSH
> tunnel, or on a trusted network only. Set `AUTH_MODE=htpasswd` or
> `AUTH_MODE=oidc` to put an authenticating proxy in front — see
> [Authentication](#authentication-platform-adr-0006). Bridge (the platform's
> PEP/PDP) is still not in this bundle: the proxy authenticates and decides
> *whether you may use this deployment*; per-record and per-slot access
> control remain Bridge's, unbuilt.

## Quickstart

```bash
cd deploy/recipes/solo
make init     # scaffold ./project (mosaic.yaml, schemas/, data/) from the example
make gate     # certified-frontier pre-flight (platform ADR-0001)
make up       # build the bundle image and start it
```

Then open <http://localhost:8080> (Aperture) and <http://localhost:8080/docs>
(API docs). `SOLO_PORT=9090 make up` to publish elsewhere.

The **project directory** is the whole deployment state: `mosaic.yaml`,
`schemas/*.yaml`, `data/mosaic.db`. Put it under git; back it up with
`make backup`. Point `PROJECT_DIR` at any path to run a different project.

## Authentication (platform ADR-0006)

No component in this bundle can hold a session — Aperture is a static bundle and Mosaic holds
zero authn/authz by design. So authentication happens in an **`oauth2-proxy`** sitting in the
recipe's nginx position. nginx gates every route with `auth_request`; the proxy holds the session
in an httpOnly cookie. **No token ever reaches the browser.**

| `AUTH_MODE` | Credential | Use |
|---|---|---|
| `none` *(default)* | — | Unchanged. Trusted network only. |
| `htpasswd` | username + password | Testing, and deployment before SSO onboarding completes. |
| `oidc` | whatever the IdP asserts — PIV/CAC at VA | Production. |

**`htpasswd` and `oidc` differ only in credential source.** Same proxy, same session cookie, same
nginx wiring, same headers, same Aperture config. Everything except the identity provider is
exercised by the password mode, so a long SSO onboarding does not block validating the rest.

### Password mode (testing)

```bash
mkdir -p auth
htpasswd -B -c auth/users.htpasswd alice          # bcrypt; -B matters

export AUTH_MODE=htpasswd
export AUTH_COOKIE_SECRET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
export AUTH_COOKIE_SECURE=false                   # ONLY for localhost — see below
make up
```

Open <http://localhost:8080>; the proxy presents a sign-in form, and Aperture then shows who you
are with a sign-out link in the header.

> **`AUTH_COOKIE_SECURE=false` sends the session cookie over plain HTTP.** That is acceptable on
> `localhost` and nowhere else — passwords in cleartext on a shared network are *worse* than the
> no-auth posture this replaces. The recipe warns loudly. Terminate TLS before anyone else can
> reach it.

### OIDC mode (production)

```bash
export AUTH_MODE=oidc
export AUTH_COOKIE_SECRET=...
export AUTH_OIDC_ISSUER_URL=https://<idp>/...     # discovery base
export AUTH_OIDC_CLIENT_ID=... AUTH_OIDC_CLIENT_SECRET=...
export AUTH_REDIRECT_URL=https://<your-host>/oauth2/callback
export AUTH_ALLOWED_GROUPS="<group>"              # space-separated; optional
export AUTH_OIDC_GROUPS_CLAIM=groups              # if the IdP names it differently
export AUTH_PROVIDER_CA_FILE=/path/to/ca.pem      # TLS-inspecting networks
```

`AUTH_REDIRECT_URL` must match what the IdP registered **exactly** — VA IAM registers no
wildcards, and changing it later is another ticket. Settle your hostname and TLS *before*
starting SSO onboarding, not after.

### What you get, and what you don't

**You get:** a real session with an expiry; sign-out that ends the IdP session, not just a
cookie; one coarse authorization decision (`--allowed-group`); and — the quiet win —
**provenance attributed to the real user**. nginx injects `X-DataHelix-Actor: actor:<user>`, the
format `mosaic.core.middleware` already parses, replacing the `Bearer solo` under which every
write is currently attributed to nobody.

**You don't get:** per-record or per-slot access control. Everyone who gets in sees the same
data. That is Bridge's job (`sec6` §6.3 steps 2–3) and it is unbuilt. If some users must see
less than others, this recipe does not deliver it and does not pretend to.

Password mode also cannot test group-based denial — an htpasswd user has no groups. If you need
to exercise that before your IdP is available, run a local OIDC provider with static users (Dex)
in `oidc` mode instead.

### Two things this cannot close for you

- **Mosaic's REST port (8001) is outside the auth boundary** — it is unproxied by construction.
  If you enable auth, keep that port closed or route it through the proxy.
- **The proxy must be the only path to Mosaic.** nginx overrides `X-DataHelix-Actor` on every
  proxied request, which is what makes it trustworthy; anything reaching Mosaic directly bypasses
  that.

## Iterating your schema

Additive changes (new classes, attributes, enums) are a restart away
(restart-on-migrate, Mosaic v0.1 model). Removals/renames are **not**
auto-applied — plan those with `mosaic schema safe-deploy` first.

If your schema splits across multiple files using local cross-file
`imports:` (a tree-root file importing sibling files in the same
`schemas/` directory), point `mosaic.yaml`'s `schema_path` at the
tree-root file itself (e.g. `schemas/model.yaml`), not just the
`schemas/` directory — required for `mosaic serve`, and also relevant
when debugging a `migrate` failure, since the entrypoint's migrate step
runs with its working directory set to `schemas/` so those relative
imports resolve.

**Mode L — you and the container on the same machine.** Edit
`./project/schemas/*.yaml` directly — that directory is bind-mounted into the
container — then:

```bash
make migrate   # = restart: applies additive DDL, Aperture re-introspects
```

Any editor works, including the LinkML Modeler run separately: it uses the
browser's File System Access API to open a directory on *your* disk, which is
the same directory the container mounts. That was always true — the bundled
copy never had server-side access either.

**Mode R — container on a remote host.** The loop goes through git:

1. Make `project/` (or just its `schemas/`) a git repo with a remote.
2. Edit and push from wherever you work.
3. Configure the container with `SCHEMA_GIT_REMOTE=<url>` (optionally
   `SCHEMA_GIT_REF`, and `SCHEMA_GIT_PATH` if the schemas aren't at `schemas/`
   in that repo), then `make migrate`.

On every (re)start with `SCHEMA_GIT_REMOTE` set, the entrypoint fetches the
remote into a staging directory, **dry-runs the migration before touching
anything**, then swaps the schemas in and applies. A failed plan aborts the
boot with the old schemas and database untouched.

> Editing in a browser-based tool on a *remote* deployment used to be served by
> the bundled `/cors-proxy/` git relay, which let the Modeler clone and push
> same-origin. That is gone with the Modeler (ADR-0005); in-browser git now
> needs a CORS-enabled git host or your own proxy.

Escape hatch: `scp` the YAML into `project/schemas/` and `make migrate`.

## How it fits together

```
:8080 nginx ── /            → Aperture SPA   (from the certified aperture image)
          ├── /graphql      → mosaic serve --graphql (localhost:8001)  [+ bearer]
          └── /health /docs /redoc /openapi.json → mosaic serve
supervisord: nginx + mosaic ─ entrypoint: [pull] → migrate → serve
volume: ./project → /project   (workdir; mosaic.yaml auto-discovered)
```

Same-origin proxying is the certification-proven seam (the certify stack runs
the identical topology): Aperture is runtime-configured with the **relative**
endpoint `/graphql`, so there is no CORS anywhere. Override any Aperture
runtime var (`VITE_GRAPHQL_URL`, `VITE_CONTROL_PLANE_URL`,
`VITE_WORKFLOWS`, `VITE_NAV`) via compose environment (ADR-0034).

## Certification (platform ADR-0001)

The bundle is **built from the certified pair**: the Dockerfile pins the
mosaic and aperture images by digest, and `make check-pins` fails if they
drift from `certification/composition.lock.json` (this is the recipe's own
invariant, enforced in CI). The pins are recorded as OCI labels
(`org.datahelix.solo.*`) on the bundle image for provenance.

`make gate` is the **deploy-time pre-flight**: it runs `check-pins` and then
the ADR-0001 ledger gate (`deploy_gate.sh`), which refuses to proceed unless
the pinned pair has a passing ledger entry. Run it before deploying to a real
environment. Note the gate depends on ledger state maintained by the certify
workflow — a freshly-bumped frontier may need an on-demand certification run
before it passes; that is expected and separate from whether the recipe
builds. (The recipe smoke CI therefore treats the gate as informational.)
Promoting the bundle itself to a certified ledger artifact is the Phase-3
follow-on (proposal §4.4).

## Upgrading

1. The certification frontier advances (new certified pair in the lock).
2. Update the Dockerfile's `MOSAIC_IMAGE` / `APERTURE_IMAGE` ARGs to match
   (`make check-pins` confirms).
3. `make gate && make up` — the image rebuilds, migrate-on-boot handles
   additive schema evolution, SQLite data carries over in `project/`.

## Limitations (deliberate, MVP)

- **Single-user, no auth** (see banner above). Multi-user lands with Bridge
  and the `team` recipe.
- **No bundled schema-editing GUI** (ADR-0005) — edit YAML directly, or run the
  LinkML Modeler yourself against `project/schemas/`.
- Only `/graphql`, `/health`, `/docs`, `/redoc`, `/openapi.json` are proxied;
  Mosaic's full REST surface needs the optional `8001` port mapping
  (commented in `docker-compose.yml`).
- Container processes run as root (bind-mount ownership simplicity); harden
  in `team`.
- Migrations are additive-only; breaking changes are a manual
  `schema safe-deploy` operation.
- The certified frontier pins are in `certification/composition.lock.json`.
  Mosaic's data-contract identifiers (`mosaic_core`, the `mosaic_*` annotation
  keys, the `X-DataHelix-Actor` header) follow platform ADR-0007; schemas that
  still use `hippo_*` keys fail validation on Mosaic v0.16.0+.
