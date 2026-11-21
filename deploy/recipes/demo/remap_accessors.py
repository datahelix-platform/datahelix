#!/usr/bin/env python3
"""Remap a linkml-data-gen bundle's top-level keys to Mosaic's ingest accessors.

linkml-data-gen keys its output by the schema's own tree-root slot names
(``processes:``, ``analyses:``). Mosaic's ingest bundle instead recognizes an
accessor per class, derived from the class name — and for irregular plurals
the naive derivation differs (``Process`` -> ``processs``, ``Analysis`` ->
``analysiss``) unless the class carries a ``mosaic_accessor`` annotation.

We compute the mapping straight from the schema, reusing the running image's
OWN accessor helper so the remap always matches whatever version does the
ingest. Each tree-root slot is mapped to Mosaic's accessor for that slot's
range class; only differing keys are rewritten.

Usage: remap_accessors.py <schema.yaml> <in-bundle.yaml> <out-bundle.yaml>
"""

import sys

import yaml
from linkml_runtime import SchemaView

# Reuse the installed runtime's accessor helper; fall back to the documented
# default (snake_case + "s", or a `mosaic_accessor` override) if it is absent.
try:
    from mosaic.linkml_bridge import class_accessor_name  # type: ignore
except Exception:  # pragma: no cover - version-dependent
    import re

    def class_accessor_name(class_name, cls_obj):  # noqa: ANN001
        ann = getattr(cls_obj, "annotations", None) or {}
        override = None
        if hasattr(ann, "get"):
            a = ann.get("mosaic_accessor")
            override = getattr(a, "value", a) if a is not None else None
        if isinstance(override, str) and override:
            return override
        s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", class_name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower() + "s"


def main() -> int:
    schema_path, in_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    sv = SchemaView(schema_path)
    tree_root = next(
        (c for c in sv.all_classes().values() if c.tree_root), None
    )
    if tree_root is None:
        print("remap: schema has no tree_root class", file=sys.stderr)
        return 1

    remap = {}
    for slot_name in sv.class_slots(tree_root.name):
        slot = sv.induced_slot(slot_name, tree_root.name)
        rng = slot.range
        if rng in sv.all_classes():
            accessor = class_accessor_name(rng, sv.get_class(rng))
            if accessor != slot_name:
                remap[slot_name] = accessor

    data = yaml.safe_load(open(in_path))
    out = {remap.get(k, k): v for k, v in data.items()}
    with open(out_path, "w") as fh:
        yaml.safe_dump(out, fh, sort_keys=False)

    total = sum(len(v) for v in out.values() if isinstance(v, list))
    print(f"remap: keys rewritten {remap or '(none)'}; {total} instances")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
