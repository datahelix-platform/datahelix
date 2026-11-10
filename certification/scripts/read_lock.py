#!/usr/bin/env python3
"""Resolve certification pins from composition.lock.json (or dispatch inputs).

Emits shell-eval'able assignments and, when run in CI, appends the same keys to
$GITHUB_OUTPUT. A pin whose digest is null/placeholder marks the composition
"unpublished" so the workflow skips the boot as an honest no-op (ADR-0001: never
certify an artifact that isn't published by digest).

The Mosaic component (ADR-0004, formerly Hippo) is emitted under the canonical
``mosaic_*`` keys. ``composition.lock.json`` itself is ledger/lock data and is
read as-is (never rewritten by this script): its component key is "mosaic"
now that Phase R is done, but the older "hippo" key is still tolerated so lock
files on older lines (and their ledger history) keep resolving.

Usage:
    read_lock.py path/to/composition.lock.json
    read_lock.py --mosaic-version X --mosaic-digest D \
                 --aperture-version Y --aperture-digest D2 [--line frontier] \
                 [--mosaic-image I] [--aperture-image I2] [--image-lock LOCK]

Image paths are never hard-coded here. The lock-file form reads each
component's ``image`` from the lock. The explicit-pin form (manual
workflow_dispatch backfill) takes ``--mosaic-image`` / ``--aperture-image``,
each defaulting to that component's ``image`` in ``--image-lock`` (default:
the ``composition.lock.json`` next to this script's parent directory), so a
registry move (e.g. the datahelix-platform org move, #117) is a lock edit, not
a code change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


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


DEFAULT_LOCK = Path(__file__).resolve().parent.parent / "composition.lock.json"


def _mosaic_key(comps: dict) -> str:
    # Tolerate either spelling in the lock data (decision 1.7 alias):
    # older lock files key the component "hippo" (matching the then
    # not-yet-renamed upstream release pipeline); current ones key it "mosaic".
    return "mosaic" if "mosaic" in comps else "hippo"


def lock_images(lock: Path) -> dict[str, str]:
    """The ``image`` path of each component in ``lock`` ("" if absent)."""
    comps = json.loads(Path(lock).read_text())["components"]
    return {
        "mosaic": comps.get(_mosaic_key(comps), {}).get("image", ""),
        "aperture": comps.get("aperture", {}).get("image", ""),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lock", nargs="?", help="composition.lock.json")
    ap.add_argument("--mosaic-version")
    ap.add_argument("--mosaic-digest")
    ap.add_argument("--aperture-version")
    ap.add_argument("--aperture-digest")
    ap.add_argument("--line")
    ap.add_argument("--mosaic-image", help="default: the lock's mosaic image")
    ap.add_argument("--aperture-image", help="default: the lock's aperture image")
    ap.add_argument(
        "--image-lock",
        default=str(DEFAULT_LOCK),
        help="lock file supplying default image paths for the explicit-pin form",
    )
    ap.add_argument("--fixture-version", default="1.0.0")
    args = ap.parse_args(argv)

    if args.lock:
        doc = json.loads(Path(args.lock).read_text())
        comps = doc["components"]
        mosaic_key = _mosaic_key(comps)
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
        if args.mosaic_image and args.aperture_image:
            images = {}
        else:
            images = lock_images(Path(args.image_lock))
        pins = {
            "line": args.line or "frontier",
            "fixture_version": args.fixture_version,
            "mosaic_version": args.mosaic_version or "",
            "mosaic_digest": args.mosaic_digest or "",
            "mosaic_image": args.mosaic_image or images["mosaic"],
            "aperture_version": args.aperture_version or "",
            "aperture_digest": args.aperture_digest or "",
            "aperture_image": args.aperture_image or images["aperture"],
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
