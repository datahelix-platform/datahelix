#!/usr/bin/env python3
"""Resolve certification pins from composition.lock.json (or dispatch inputs).

Emits shell-eval'able assignments and, when run in CI, appends the same keys to
$GITHUB_OUTPUT. A pin whose digest is null/placeholder marks the composition
"unpublished" so the workflow skips the boot as an honest no-op (ADR-0001: never
certify an artifact that isn't published by digest).

The Mosaic component (ADR-0004, formerly Hippo) is emitted under the canonical
``mosaic_*`` keys. ``composition.lock.json`` itself is ledger/lock data and is
read as-is (never rewritten by this script): its component key is currently
"hippo" (matching the hippo repo's release pipeline, which still publishes
under "component": "hippo" until the repo itself is renamed — Phase R), but a
future "mosaic" key is tolerated too so this script keeps working once the
lock file's own bump bot switches spellings.

Usage:
    read_lock.py path/to/composition.lock.json
    read_lock.py --mosaic-version X --mosaic-digest D \
                 --aperture-version Y --aperture-digest D2 [--line frontier] \
                 [--mosaic-image IMG] [--aperture-image IMG] [--lock-file PATH]

In the manual-dispatch form the image paths default to the ``image`` recorded in
the lock file (``--lock-file``, default ``certification/composition.lock.json``
beside this script), so a re-certification boots the image the lock names rather
than a hard-coded path. Pass ``--mosaic-image`` / ``--aperture-image`` to override.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "composition.lock.json"


def _lock_image(lock_path: str, component: str) -> str:
    """The `image` the lock records for a component ("" if unreadable/absent)."""
    try:
        comps = json.loads(Path(lock_path).read_text())["components"]
    except (OSError, ValueError, KeyError):
        return ""
    if component == "mosaic":
        component = "mosaic" if "mosaic" in comps else "hippo"
    return comps.get(component, {}).get("image", "")


def _emit(pairs: dict[str, str]) -> None:
    for k, v in pairs.items():
        print(f"{k}={v}")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as fh:
            for k, v in pairs.items():
                fh.write(f"{k}={v}\n")


def _is_real_digest(d) -> bool:
    return isinstance(d, str) and (":" in d or d.startswith("sha256-")) and "placeholder" not in d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lock", nargs="?", help="composition.lock.json")
    ap.add_argument("--mosaic-version")
    ap.add_argument("--mosaic-digest")
    ap.add_argument("--aperture-version")
    ap.add_argument("--aperture-digest")
    ap.add_argument("--mosaic-image", help="image path (default: the lock file's mosaic image)")
    ap.add_argument("--aperture-image", help="image path (default: the lock file's aperture image)")
    ap.add_argument("--lock-file", default=str(DEFAULT_LOCK), help="lock to take default images from")
    ap.add_argument("--line")
    ap.add_argument("--fixture-version", default="1.0.0")
    args = ap.parse_args(argv)

    if args.lock:
        doc = json.loads(Path(args.lock).read_text())
        comps = doc["components"]
        # Tolerate either spelling in the lock data (decision 1.7 alias):
        # today's lock files still key the component "hippo" (matching the
        # not-yet-renamed upstream release pipeline); a future lock file may
        # key it "mosaic" once that pipeline moves too.
        mosaic_key = "mosaic" if "mosaic" in comps else "hippo"
        pins = {
            "line": doc.get("line", "frontier"),
            "fixture_version": doc.get("fixture_version", args.fixture_version),
            "mosaic_version": comps[mosaic_key]["version"],
            "mosaic_digest": comps[mosaic_key].get("digest") or "",
            "mosaic_image": comps[mosaic_key].get("image", ""),
            "aperture_version": comps["aperture"]["version"],
            "aperture_digest": comps["aperture"].get("digest") or "",
            "aperture_image": comps["aperture"].get("image", ""),
        }
    else:
        pins = {
            "line": args.line or "frontier",
            "fixture_version": args.fixture_version,
            "mosaic_version": args.mosaic_version or "",
            "mosaic_digest": args.mosaic_digest or "",
            # No hard-coded registry path: take the image from the argument,
            # else from the lock (so a manual run boots what the lock names).
            "mosaic_image": args.mosaic_image or _lock_image(args.lock_file, "mosaic"),
            "aperture_version": args.aperture_version or "",
            "aperture_digest": args.aperture_digest or "",
            "aperture_image": args.aperture_image or _lock_image(args.lock_file, "aperture"),
        }

    published = _is_real_digest(pins["mosaic_digest"]) and _is_real_digest(pins["aperture_digest"])
    pins["published"] = "true" if published else "false"
    if published:
        pins["mosaic_ref"] = f"{pins['mosaic_image']}@{pins['mosaic_digest']}"
        pins["aperture_ref"] = f"{pins['aperture_image']}@{pins['aperture_digest']}"
    _emit(pins)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
