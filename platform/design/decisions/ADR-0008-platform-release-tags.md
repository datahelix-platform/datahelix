# ADR-0008: Platform release tags: hand-cut semver `vX.Y.Z` on datahelix `main`, one tag for every recipe

- **Status:** Accepted
- **Date:** 2026-11-23 (proposed and ratified)
- **Deciders:** labadorf (ratified 2026-11-23)
- **Tracking issue:** [datahelix#142](https://github.com/datahelix-platform/datahelix/issues/142)
- **Related:** [ADR-0001](./ADR-0001-certified-frontier-composition.md) (certified-frontier ledger, `certified/*` tags, rule 4 immutability); [ADR-0006](./ADR-0006-authenticating-proxy-in-recipes.md) (the `solo` recipe the first consumer deploys); datahelix#139 (lock-only bumps leave recipe pins behind); datahelix#140 (first fix that has to land before the first tag); datahelix#35 (1.0 roadmap); ptsdbb-infrastructure#17 (the first consumer pinning a datahelix ref); [`RELEASING.md`](../../../RELEASING.md) (the cut steps)

## Context

The recipes under `deploy/recipes/` are consumed by building from a datahelix git ref. The first
real consumer, the ptsdbb-infrastructure deployment (ptsdbb-infrastructure#17), runs
`deploy/recipes/solo` on one EC2 host and rebuilds the image from a **pinned git ref**. Something
has to be that ref, and today there is no good candidate:

- **A branch (`main`)** moves. Pinning it means every deploy picks up whatever merged last.
- **A commit SHA** works but carries no meaning. Nothing says it was a good commit to deploy, and
  an operator can't tell from the SHA whether it is newer or riskier than the one before.
- **The `certified/*` tags** look like releases but are not. Per ADR-0001 they are **ledger
  facts**: each one records that an exact component pair (`certified/aperture-<X>+mosaic-<Y>`)
  passed certification, and it points at whatever commit certified it. They say nothing about the
  recipes. A `certified/*` tag can point at a commit whose recipe pins still lag the lock: in
  datahelix#139 a lock-only bump (mosaic 0.16.0 → 0.16.1) certified and merged while the `demo`,
  `demo-reel` and `solo` Dockerfiles and the `ide` compose default still pinned 0.16.0. A consumer
  who pinned that tag would have built 0.16.0 bundles from a commit "certified" for 0.16.1.
  `certified/*` tags are also keyed by component pair, not by the recipe bundle, so recipe-only
  fixes (like datahelix#140) never get one.

The platform needs a ref that means "this commit's recipes, as a whole, are a release you can
deploy".

## Decision

**DataHelix will publish platform-wide semver release tags `vX.Y.Z` on datahelix `main`, cut by
hand, each with a GitHub release.**

1. **One tag covers every recipe.** A `vX.Y.Z` tag versions the whole recipe bundle at that
   commit (`demo`, `demo-reel`, `solo`, `ide`), plus the platform docs and certification state
   that go with them. Recipes are not versioned separately.

2. **Semver meaning for a recipe bundle**, judged from the point of view of a recipe consumer
   (someone who builds a recipe from the tag and runs it):
   - **Major:** a breaking deploy or config change for recipe consumers. Examples: a removed or
     renamed environment variable, a changed volume layout or port, a schema or data-contract
     change that needs operator action beyond restart-on-migrate.
   - **Minor:** a new recipe or recipe feature, or a component bump (a new certified pair in the
     recipe pins).
   - **Patch:** fixes that need no consumer action.

   Pre-1.0 (`0.y.z`) follows the usual semver convention: a breaking change bumps the minor.
   1.0 is tied to the platform 1.0 roadmap (datahelix#35), not to this ADR.

3. **Cut preconditions.** A commit may be tagged only when all of these hold on that exact commit:
   - **Certification passed:** the certify workflow is green on the commit, and the locked pair
     has a passing ledger entry (`make gate` passes in each gated recipe).
   - **`make check-pins` passes for every recipe that has it** (`demo`, `demo-reel`, `solo`;
     `ide` is exempt from the gate by ADR-0004 and has no target).
   - **Recipe pins match `certification/composition.lock.json`.** This includes the `ide`
     compose defaults, which `check-pins` does not cover. This is the check that would have
     caught the datahelix#139 drift.

4. **Tags are immutable.** A `vX.Y.Z` tag is never moved, deleted and re-created, or re-cut onto
   another commit. A bad release is fixed by cutting the next patch. This is ADR-0001 rule 4
   ("never re-cut under the same number") applied to platform releases.

5. **Release notes** on the GitHub release list the certified pair (component versions and image
   digests, as recorded in the lock at the tagged commit) and summarise the changes since the
   previous tag under the semver headings above, with breaking changes first.

6. **Cut by hand.** A maintainer cuts the tag with `gh release create` on the chosen `main`
   commit, following [`RELEASING.md`](../../../RELEASING.md). There is no release automation for
   now. The steps are short and releases are rare. If automation is added later, it must enforce
   the same preconditions.

**First tag:** `v0.1.0`, cut on `main` after datahelix#140 (the `solo` Mosaic bind-host fix) merges,
so the first consumer's pinned ref includes it.

## Consequences

- Consumers pin `vX.Y.Z` and read the release notes to decide whether an upgrade needs action.
  The ptsdbb-infrastructure deployment moves from a SHA to `v0.1.0`.
- `certified/*` tags keep their ADR-0001 meaning (ledger facts about component pairs) and are not
  a deploy ref. The two tag families coexist; release notes link the one that applies.
- A release needs a commit where the recipe pins agree with the lock. Until datahelix#139 makes
  bump PRs update the pins, someone has to check this by hand before cutting.
- No bundle image is published. Consumers still build from the tag; the tag pins the inputs (the
  Dockerfile's digest-pinned component images), so the build is reproducible.

## Alternatives considered

- **Use `certified/*` tags as the deploy ref.** Rejected. They are keyed by component pair, they
  can sit on commits whose recipe pins lag the lock (datahelix#139), and recipe-only fixes never
  get one. Overloading them would also blur ADR-0001's ledger.
- **Per-recipe tags (`solo/vX.Y.Z`, …).** Rejected. The recipes share the lock, the certification
  state and much of their wiring, so one version describes them better. Per-recipe tags would
  multiply ceremony for little gain while there is one real consumer.
- **CalVer or SHA-only pinning.** Rejected. Neither tells a consumer whether an upgrade is
  breaking, and that is the information an operator needs.
- **Automated tagging on every certified merge.** Deferred, not rejected. Releases are rare, and
  the preconditions include a judgement call (the semver level). Revisit when the cadence makes
  hand-cutting a burden.
