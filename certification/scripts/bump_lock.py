#!/usr/bin/env python3
"""Move exactly one component pin in ``composition.lock.json`` (platform ADR-0001).

    bump_lock.py COMPONENT VERSION DIGEST [--image IMAGE] [--lock PATH]

One release, one delta: this rewrites the ``version``/``digest`` (and, when
given, ``image``) of ONE entry under ``components`` and nothing else, preserving
key order and the ``_comment`` block, so a red certification on the resulting
PR attributes to a single version change.

Exit status 0 in two cases: the pin moved (``changed=true``), or the lock
already carries exactly this version and digest (``changed=false`` — a
re-dispatch of the same release is a no-op, not an error). Anything else is a
refusal with a message naming the field:

- unknown component (not a key under ``components``);
- ``VERSION`` not ``X.Y.Z`` or ``DIGEST`` not ``sha256:<64 hex>``;
- ``IMAGE`` outside ``ghcr.io/datahelix-platform/`` — the dispatch payload is
  data from whoever holds the token, so the registry namespace is pinned here;
- a downgrade (the lock is ahead of the release);
- a re-cut: same version, different digest. ADR-0001: never re-cut a released
  number.

When ``GITHUB_OUTPUT`` is set, writes ``changed``, ``delta`` (``patch`` |
``minor`` | ``major`` | ``none``), ``previous``, ``version`` and ``image`` for
the workflow (``.github/workflows/bump-lock.yml``).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "composition.lock.json"
ALLOWED_IMAGE_PREFIX = "ghcr.io/datahelix-platform/"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class Refusal(Exception):
    """A payload this script will not act on. The message names the field."""


def parse_version(text: str) -> tuple[int, int, int]:
    m = SEMVER.match(text)
    if not m:
        raise Refusal(f"version {text!r} is not X.Y.Z (no v prefix, no pre-release)")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def delta(previous: str, new: str) -> str:
    a, b = parse_version(previous), parse_version(new)
    if b == a:
        return "none"
    if b < a:
        raise Refusal(f"version {new} is a downgrade from the pinned {previous}")
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


def bump(lock: dict, component: str, version: str, digest: str, image: str | None = None) -> dict:
    """Mutate ``lock`` in place; return the outputs the workflow reads."""
    components = lock.get("components")
    if not isinstance(components, dict) or component not in components:
        known = sorted(components) if isinstance(components, dict) else []
        raise Refusal(f"unknown component {component!r}; the lock pins {known}")
    if not DIGEST.match(digest):
        raise Refusal(f"digest {digest!r} is not sha256:<64 hex>")
    if image is not None and not image.startswith(ALLOWED_IMAGE_PREFIX):
        raise Refusal(f"image {image!r} is outside {ALLOWED_IMAGE_PREFIX}")
    entry = components[component]
    previous = str(entry.get("version"))
    kind = delta(previous, version)
    if kind == "none":
        if entry.get("digest") == digest and (image is None or entry.get("image") == image):
            return {
                "changed": "false", "delta": "none", "previous": previous,
                "version": version, "image": entry.get("image", ""),
            }
        raise Refusal(
            f"{component} {version} is already pinned at digest {entry.get('digest')}; "
            f"a different digest for the same version is a re-cut, which ADR-0001 forbids"
        )
    entry["version"] = version
    entry["digest"] = digest
    if image is not None:
        entry["image"] = image
    return {
        "changed": "true", "delta": kind, "previous": previous,
        "version": version, "image": entry.get("image", ""),
    }


def write_outputs(outputs: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("component")
    ap.add_argument("version", help="X.Y.Z, no v prefix")
    ap.add_argument("digest", help="sha256:...")
    ap.add_argument("--image", default=None, help=f"image path under {ALLOWED_IMAGE_PREFIX}")
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = ap.parse_args(argv)

    text = args.lock.read_text(encoding="utf-8")
    lock = json.loads(text)
    try:
        outputs = bump(lock, args.component, args.version, args.digest, args.image)
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if outputs["changed"] == "true":
        # Same serialization as the hand-written file: 2-space indent, ASCII
        # escapes, trailing newline — so the diff is the pin and nothing else.
        args.lock.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"{args.component}: {outputs['previous']} -> {args.version} ({outputs['delta']}) {args.digest}")
    else:
        print(f"already at {args.component} {args.version}@{args.digest}; nothing to do")
    write_outputs(outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
