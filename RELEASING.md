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
| major | A breaking deploy or config change for recipe consumers (env var removed or renamed, volume/port layout changed, operator action needed beyond restart-on-migrate). Pre-1.0, this bumps the minor. |
| minor | A new recipe or recipe feature, or a component bump (new certified pair in the recipe pins). |
| patch | Fixes that need no consumer action. |

## Check the preconditions on the exact commit

```bash
git fetch origin --tags
SHA=$(git rev-parse origin/main)       # or the specific main commit you mean to release
git checkout --detach "$SHA"

# 1. Certification passed on this commit
gh run list --workflow certify.yml --commit "$SHA"     # latest run must be green
for r in demo demo-reel solo; do make -C deploy/recipes/$r gate; done   # check-pins + ledger gate

# 2. Recipe pins match the lock (check-pins covers demo/demo-reel/solo; ide is checked by hand)
jq -r '.components | to_entries[] | "\(.key) \(.value.version)"' certification/composition.lock.json
grep -nE '(MOSAIC|APERTURE)_VERSION:-' deploy/recipes/ide/docker-compose.yml
```

If any of these fails, do not tag. Fix the pins in a PR first; see datahelix#139 for the usual
cause.

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
  `certification/composition.lock.json` at `$SHA`, and the matching `certified/*` tag.
- **Changes since the previous tag**, grouped as Breaking / Added / Fixed, with breaking changes
  first and the action a consumer must take.

## Never re-cut

A published `vX.Y.Z` is immutable (ADR-0008, after ADR-0001 rule 4). Don't delete, move or
re-create it, even minutes after publishing. If it is wrong, cut the next patch.
