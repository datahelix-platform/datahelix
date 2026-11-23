# Releasing DataHelix

Platform releases are hand-cut semver tags `vX.Y.Z` on `main`, each with a GitHub release.
One tag covers every recipe under `deploy/recipes/`. Recipe consumers pin this tag. The rules
are in [platform ADR-0008](platform/design/decisions/ADR-0008-platform-release-tags.md); this
page is the procedure.

`certified/*` tags are **not** releases. They are ADR-0001 ledger facts about a component pair.
Never pin a deployment to one.

## Choose the version

Judge the change from a recipe consumer's point of view, comparing against the previous `v*` tag
(`git describe --tags --match 'v*' --abbrev=0`):

| Bump | When |
|---|---|
| major | A breaking deploy or config change for recipe consumers (env var removed or renamed, volume/port layout changed, operator action needed beyond restart-on-migrate). |
| minor | A new recipe or recipe feature, or a component bump (new certified pair in the recipe pins). |
| patch | Fixes that need no consumer action. |

**Pre-1.0 (`0.y.z`) there is no major bump.** Breaking changes *and* new recipes, features or
component bumps all go to the **minor** (`0.y` → `0.y+1`). Fixes go to the **patch**. The
version alone doesn't show a breaking change before 1.0, so the release notes must call it out.

## Check the preconditions on the exact commit

Work in a throwaway worktree, so the submodules match the commit and your own checkout is left
alone:

```bash
git fetch origin --tags
SHA=$(git rev-parse origin/main)       # or the specific main commit you mean to release
git worktree add --detach ../dh-release "$SHA"
cd ../dh-release
git submodule update --init mosaic aperture
```

**1. The locked pair is certified.** `make gate` at `$SHA` is the ADR-0001 ledger check: the
lock's versions and digests have a passing `certified/*` entry. The tagged commit usually has no
certify run of its own, because `certify.yml` runs on `main` only when certification inputs
change. So also check the `push` run on the commit that last changed the lock:

```bash
for r in demo demo-reel solo; do make -C deploy/recipes/$r gate; done   # check-pins + ledger gate

L=$(git log -1 --format=%H "$SHA" -- certification/composition.lock.json)
gh run list --repo datahelix-platform/datahelix --workflow certify.yml \
  --commit "$L" --event push --json conclusion        # must be [{"conclusion":"success"}]
git tag --points-at "$L" 'certified/*'                 # the pair's ledger tag, for the notes
```

**2. Every pin matches the lock.** `check-pins` (run by `make gate` above) covers the `demo`,
`demo-reel` and `solo` Dockerfiles. Check the rest by hand: the `ide` compose defaults and the
`mosaic` and `aperture` submodule pointers, each of which must sit exactly on the lock version's
tag.

```bash
jq -r '.components | to_entries[] | "\(.key) \(.value.version)"' certification/composition.lock.json
grep -nE '(MOSAIC|APERTURE)_VERSION:-' deploy/recipes/ide/docker-compose.yml
git submodule status mosaic aperture
git -C mosaic describe --tags --exact-match      # must print v<lock mosaic version>
git -C aperture describe --tags --exact-match    # must print v<lock aperture version>
```

If any of these fails, do not tag. Fix the pins in a PR first; see datahelix#139 for the usual
cause. When you're done, `cd -` and `git worktree remove ../dh-release`.

## Cut

```bash
VERSION=v0.1.0
gh release create "$VERSION" --repo datahelix-platform/datahelix \
  --target "$SHA" --title "DataHelix $VERSION" --notes-file notes.md
```

`--target` must be the full SHA you checked, not `main`. `main` may have moved on since you
checked it.

`notes.md` contains:

- **Certified pair:** each component's version and image digest from
  `certification/composition.lock.json` at `$SHA`, and the `certified/*` tag found above
  (`git tag --points-at "$L" 'certified/*'`).
- **Changes since the previous tag**, grouped as Breaking / Added / Fixed, with breaking changes
  first and the action a consumer must take.

## Never re-cut

A published `vX.Y.Z` is immutable (ADR-0008, after ADR-0001 rule 4). Don't delete, move or
re-create it, even minutes after publishing. If it is wrong, cut the next patch.

GitHub enforces this: repository ruleset 27943686, "Immutable release tags (ADR-0008)", blocks
deletion, update and non-fast-forward of any `refs/tags/v*` tag. Repository admins can bypass it.
If you are an admin, don't: a bypass is not a way to fix a release. Cut the next patch instead.
