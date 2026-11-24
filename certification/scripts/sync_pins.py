#!/usr/bin/env python3
"""Copy one component's lock pin into every recipe that pins it (issue #139).

    sync_pins.py COMPONENT [--lock PATH] [--recipes DIR]

``bump_lock.py`` moves the pin in ``composition.lock.json``; this script then
applies that same delta everywhere else the component is pinned under
``deploy/recipes/``, so one release lands as one PR (platform ADR-0001: one
release = one delta — one component's delta, applied everywhere it's pinned)
and the gated recipes' ``make check-pins`` passes without a follow-up PR:

- ``ARG <COMPONENT>_IMAGE=<image>@<digest>`` in each recipe ``Dockerfile``
  (the certified-pair build ARGs ``check_pins.py`` compares to the lock);
- ``${<COMPONENT>_VERSION:-X.Y.Z}`` defaults in each recipe
  ``docker-compose.yml`` (the ``ide`` recipe's tag defaults; ``ide`` is exempt
  from the gate, but a stale default is the same drift).

The component's git submodule pointer is moved by the workflow, not here: it
needs a fetch of the release tag.

Exit 0 whether or not anything changed; prints and (when ``GITHUB_OUTPUT`` is
set) writes ``files`` — the space-separated repo-relative paths it rewrote.
Exit 2 if the component is not in the lock.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPO / "certification" / "composition.lock.json"
DEFAULT_RECIPES = REPO / "deploy" / "recipes"


def sync_text(text: str, kind: str, component: str, entry: dict) -> str:
    """Return ``text`` with ``component``'s pins rewritten to ``entry``."""
    name = re.sub(r"[^A-Za-z0-9]", "_", component).upper()
    if kind == "Dockerfile":
        pinned = f"{entry['image']}@{entry['digest']}"
        return re.sub(
            rf"^(ARG\s+{name}_IMAGE=)\S+",
            lambda m: m.group(1) + pinned,
            text,
            flags=re.MULTILINE,
        )
    return re.sub(
        rf"(\$\{{{name}_VERSION:-)[^}}]+(\}})",
        lambda m: m.group(1) + entry["version"] + m.group(2),
        text,
    )


def sync(component: str, lock: dict, recipes: Path) -> list[Path]:
    components = lock.get("components") or {}
    if component not in components:
        raise KeyError(f"unknown component {component!r}; the lock pins {sorted(components)}")
    entry = components[component]
    changed: list[Path] = []
    for path in sorted(recipes.glob("*/Dockerfile")) + sorted(recipes.glob("*/docker-compose.yml")):
        old = path.read_text(encoding="utf-8")
        new = sync_text(old, path.name, component, entry)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("component")
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    ap.add_argument("--recipes", type=Path, default=DEFAULT_RECIPES)
    args = ap.parse_args(argv)

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    try:
        changed = sync(args.component, lock, args.recipes)
    except KeyError as e:
        print(f"refused: {e.args[0]}", file=sys.stderr)
        return 2
    rel = []
    for p in changed:
        try:
            rel.append(str(p.resolve().relative_to(REPO)))
        except ValueError:
            rel.append(str(p))
    for r in rel:
        print(f"synced {args.component} pin: {r}")
    if not rel:
        print(f"recipes already pin {args.component} as the lock does; nothing to do")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"files={' '.join(rel)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
