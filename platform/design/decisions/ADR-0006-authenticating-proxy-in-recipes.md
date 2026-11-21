# ADR-0006: Recipes authenticate at an OIDC reverse proxy, not in a component

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** labadorf, design session
- **Related:** [`sec6_security_model.md`](../sec6_security_model.md) §6.3 (Bridge as sole PEP/PDP); [ADR-0001](./ADR-0001-certified-frontier-composition.md) (digest pinning); [ADR-0005](./ADR-0005-drop-linkml-modeler-from-recipes.md) (no Node in `solo`); Aperture [ADR-0038](https://github.com/datahelix-platform/aperture/blob/main/design/decisions/ADR-0038-identity-is-presentation-not-enforcement.md) (the identity Aperture presents), Aperture ADR-0016/0032; Mosaic [`design/sec8_auth_integration.md`](../../../mosaic/design/sec8_auth_integration.md) §8.3, [datahelix-platform/mosaic#178](https://github.com/datahelix-platform/mosaic/issues/178)

## Context

The `solo` recipe ships with no authentication. Its README is blunt about it: *"Run it on
localhost, behind a VPN/SSH tunnel, or on a trusted network only."* The first real deployment —
the VA National Center for PTSD Brain Bank, in VAEC GovCloud — cannot accept that. VA IAM policy
requires internal applications to integrate with **SSOi** (PIV/CAC smart-card single sign-on),
and the current control is a security-group CIDR allowlist.

Two constraints shape the answer.

**No component can hold the session.** Aperture is a static bundle; ADR-0005 removed the last
Node from the `solo` image. Mosaic holds *zero* authn/authz by design — `graphql/router.py` says
so in as many words, and `PassThroughAuthMiddleware` extracts an actor for provenance only. An
OIDC relying party needs a confidential client and a server-side session; **no component in the
recipe has anywhere to put one.**

**Bridge is not the answer here, and is not close.** `sec6` §6.3 decomposes Bridge into four
steps: (1) validate the credential and resolve the viewer, (2) decide record-level predicates and
slot-level field masks, (3) build the capability-scoped client, (4) forward with a verified
identity. **PIV/CAC needs only (1) and (4).** Steps (2)–(3) — the PDP — are the large, unbuilt
part, and are unrelated to how a user proves who they are. Blocking a deployment on them trades
an achievable control for an indefinite wait.

There is also a schedule problem worth designing around: SSOi onboarding is queue-driven through
VIPR and a ServiceNow ticket to VA IAM, twice (pre-prod, then prod), and obtaining test PIV cards
is the single most common schedule risk. A design that can only be exercised once IAM answers
leaves the entire integration unvalidated for months.

## Decision

**Authentication in DataHelix recipes is performed by an OIDC-capable reverse proxy occupying the
recipe's existing nginx position.** Components remain auth-unaware. The recipe gains an
`AUTH_MODE` with three values:

| `AUTH_MODE` | Credential | Purpose |
|---|---|---|
| `none` *(default)* | — | Today's posture, unchanged. Trusted network only. |
| `htpasswd` | username + password | Testing and pre-SSOi deployment. |
| `oidc` | whatever the IdP asserts — PIV/CAC at VA | Production. |

The proxy is **`oauth2-proxy`, digest-pinned**, run under the existing supervisord alongside
mosaic and nginx. nginx gates every route with `auth_request`; the proxy holds the session in an
httpOnly cookie. **No token ever reaches the browser.**

Three properties make this a seam rather than a detour:

1. **`htpasswd` and `oidc` differ only in credential source.** Same binary, same session cookie,
   same `auth_request` wiring, same endpoints, same headers, same Aperture configuration.
   Switching to SSOi is a change of flags. **Everything except the identity provider is exercised
   from day one**, which converts the IAM wait into parallel progress.
2. **The proxy speaks the identity contract the platform already designed.** Mosaic `sec8` §8.3
   specifies components trusting a proxy-injected actor header. nginx injects
   `X-Hippo-Actor: actor:<user>` — the format `mosaic.core.middleware` already parses — so
   **provenance is attributed to the real user**, replacing the `Bearer solo` under which every
   write today is attributed to nobody.
3. **It is a partial Bridge, not a competitor.** It implements `sec6` §6.3 steps (1) and (4) and
   leaves (2)–(3) unimplemented. Bridge, when built, takes the same position and adds the PDP.

> **Note (2026-11-20, [ADR-0007](./ADR-0007-retire-hippo-data-contract-identifiers.md)):** The
> actor header named in this ADR is renamed `X-Hippo-Actor` → `X-DataHelix-Actor` (Q2), matching
> Bridge's `X-DataHelix-*` header family. Mosaic v0.16.0 reads only the new name, and the `solo`
> recipe's `nginx-auth.conf` sets it (datahelix#57). The decision itself is unchanged.

**Authorization stays coarse and honest.** `--allowed-group` against a released group claim gives
one binary decision: may this person use this deployment. Per-record predicates and slot-level
masks remain Bridge's, unbuilt, and are not simulated.

## Consequences

- **`solo` stays single-container and unauthenticated by default.** `AUTH_MODE=none` changes
  nothing; the certification stack is unaffected because it drives the Aperture image directly,
  not this recipe.
- **TLS becomes a prerequisite, not future work.** Session cookies must be `Secure`, SSOi
  redirect URIs must be HTTPS, and IAM registers them **exactly, with no wildcards** — so the
  hostname must be settled before the IAM ticket, not after. For the VA stack that means the ALB
  + ACM certificate + DNS name land before onboarding starts. A `htpasswd` deployment over plain
  HTTP is passwords in cleartext on the VA network and is worse than the current no-auth posture;
  the recipe refuses to start in that configuration unless explicitly overridden.
- **The proxy's own port must never be published.** Only nginx is exposed. Mosaic's REST port
  (8001) is outside the auth boundary entirely — it is unproxied by construction — and any
  deployment enabling auth must keep it closed or route it through the proxy too. This is called
  out because it is the obvious hole and the recipe cannot close it for the operator.
- **A new runtime dependency in the image.** `oauth2-proxy` is digest-pinned like the certified
  pair, though it is **not** part of the certified frontier: it is infrastructure, not a DataHelix
  component, and ADR-0001's ledger governs component composition. Air-gapped and GovCloud
  deployments must mirror it into their own registry.
- **`X-Hippo-Actor` is now security-relevant.** nginx sets it from the auth_request response,
  overriding anything a client sends. Mosaic trusts it unconditionally, so **the proxy must be
  the only path to Mosaic**. Once mosaic#178 lands, this header also carries ownership
  enforcement for Aperture's control-plane documents.
- **Aperture needs no code change per deployment** — `VITE_AUTH_*` values are runtime config
  (Aperture ADR-0034/0038), so one digest-addressed image serves all three modes.

## Alternatives considered

- **Implement Bridge first.** The honest blocker: it is unbuilt, and the part of it that is
  irreducible (the PDP) is not what PIV/CAC needs. Rejected on sequencing — this ADR builds the
  half that is needed and leaves the position open for the rest.
- **Add an OIDC relying party to Aperture.** No server to hold it (ADR-0005 removed the last Node
  from the image), and it would put enforcement in the component that Aperture ADR-0008/0016
  forbids holding any. Rejected.
- **Add authentication to Mosaic.** Contradicts the auth-unaware invariant `sec6` rests on, and
  would put a second enforcement point in the platform — the exact splitting §6.3 rejects.
- **nginx `auth_basic` (HTTP Basic).** Three lines, and it exercises none of the eventual path: a
  browser credential dialog rather than a page, no session, no logout, no `auth_time`, no groups,
  and no identity endpoint for Aperture to read. It would be built, thrown away, and every
  behaviour tested twice. Rejected — the cost of `htpasswd` through the real proxy is nearly
  identical and everything downstream is then already proven.
- **A separate `secure` recipe.** Duplicates `solo` entirely to vary one axis, and guarantees the
  two drift. Rejected in favour of a mode.
- **Dex (or Keycloak) with static passwords instead of `htpasswd`.** Higher fidelity — a real
  discovery document, a real ID token, and a real `groups` claim, so `--allowed-group` and the
  "valid credential, wrong group → 403" case become testable before IAM answers. Rejected as the
  *default* because it doubles the moving parts for a testing rig; recorded here as the
  recommended next step for anyone who needs to exercise the authorization half early. `htpasswd`
  cannot test group-based denial, and that limit is real.

## Notes / open sub-questions

- **Resolved (2026-08-28): the pinned `oauth2-proxy` does require provider settings alongside
  `--htpasswd-file`.** Verified against the pinned v7.13.0 image, which exits 1 with
  `provider missing setting: client-id`. The recipe therefore passes stub
  `--client-id`/`--client-secret` values in `htpasswd` mode. They are never reached: the htpasswd
  form is the only credential surface, and `--skip-provider-button=false` is what renders it.
  The flow was exercised end to end — unauthenticated `/oauth2/auth` → 401, valid credentials →
  302 + session cookie, authenticated `/oauth2/auth` → 202 with `X-Auth-Request-User`, wrong
  password → 401.
- **`/oauth2/userinfo` returns `{"user": ..., "email": ...}` in `htpasswd` mode** — no
  `preferredUsername`. Aperture's identity probe (ADR-0038) includes `user`, so it resolves
  correctly without configuration. An `oidc` deployment will carry richer claims, and
  `VITE_AUTH_IDENTITY_CLAIM` should be pinned there **before** the deployment accumulates
  control-plane documents, since the claim becomes their `owner`. Note that the two modes will
  therefore resolve *different* identity strings for the same human — migrating an `htpasswd`
  deployment to `oidc` re-owns nothing automatically.
- The VA-specific answers — SSOi's OIDC-vs-SAML availability, exact claim names, whether PIV/CAC
  group membership is released in the assertion — are open with VA IAM and tracked outside this
  repo. If SSOi turns out to be SAML-only for new applications, the proxy position is unchanged
  but the software in it may not be `oauth2-proxy`; that would be an amendment here, not a
  redesign.
