#!/usr/bin/env python3
"""Check every inverse-declared reverse edge against its forward slot, on real data.

For each exposed entity class and each reverse edge Mosaic reports on it
(``SchemaRegistry.inverse_reference_slots`` — ADR-0011, plus forward-side
declarations once ADR-0012 ships), every record must agree three ways:

1. the hydrated reverse list (``get(...)["data"][<reverse>]``) equals the set of
   target records whose forward slot points back at it (a plain filter query);
2. ``count_relationship`` equals the size of that set;
3. the ``some`` edge predicate returns exactly the records that have any link.

This is the parity check mosaic-demo-small passed for ADR-0011 ("reverse counts
match forward filters"), run against whatever dataset is loaded. Edges are
discovered from the schema, so a newly declared reverse (Donor -> samples) is
checked without editing this script. An edge with no links in the data passes
vacuously and is reported as such rather than counted as evidence.

Reads ``schema_path`` and ``database_url`` from ``<project>/mosaic.yaml`` (SQLite
only), the same config the recipe serves. Exit status 1 on any mismatch.

Usage: check_reverse_edges.py [<project-dir>]    (default: /project)
"""

import sys
from pathlib import Path

import yaml

from mosaic.core.client import MosaicClient
from mosaic.core.schema_typing import build_type_model
from mosaic.core.storage.adapters.sqlite_adapter import SQLiteAdapter
from mosaic.linkml_bridge import SchemaRegistry

PAGE = 100_000


def _ids(page) -> set[str]:
    return {e["id"] for e in page.items}


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else "/project")
    config = yaml.safe_load((project / "mosaic.yaml").read_text())
    if config.get("storage_backend", "sqlite") != "sqlite":
        sys.exit("check_reverse_edges: only the sqlite backend is supported")
    registry = SchemaRegistry.from_path(project / config["schema_path"])
    client = MosaicClient(
        storage=SQLiteAdapter(str(project / config["database_url"]), schema_registry=registry),
        bypass_validation=True,
    )

    checked = vacuous = failed = 0
    for owner in sorted(build_type_model(registry)):
        for edge in registry.inverse_reference_slots(owner):
            # `target_classes` (the range's concrete closure) arrived in mosaic
            # 0.15.0 (#224); older images expose only the single `target_class`.
            targets = tuple(getattr(edge, "target_classes", None) or (edge.target_class,))
            owner_ids = _ids(client.query(owner, limit=PAGE))
            mismatched, links, linked = [], 0, set()
            for oid in sorted(owner_ids):
                reverse = set(client.get(owner, oid)["data"].get(edge.name) or [])
                forward: set[str] = set()
                for target in targets:
                    forward |= _ids(client.query(
                        target, filters=[{"field": edge.forward_slot, "value": oid}], limit=PAGE,
                    ))
                count = client.count_relationship(owner, oid, edge.name)
                if reverse != forward or count != len(forward):
                    mismatched.append(oid)
                links += len(forward)
                if forward:
                    linked.add(oid)
            some = _ids(client.query(owner, limit=PAGE, where={
                "edge": edge.name, "quantifier": "some",
                "where": {"field": "id", "op": "neq", "value": ""},
            }))
            ok = not mismatched and some == linked
            checked += 1
            if not ok:
                failed += 1
                status = "FAIL"
            elif links == 0:
                vacuous += 1
                status = "EMPTY"
            else:
                status = "ok"
            print(
                f"{status:5} {owner}.{edge.name} <- "
                f"{'/'.join(targets)}.{edge.forward_slot}: "
                f"{len(owner_ids)} records, {links} links, {len(linked)} linked, "
                f"some={len(some)}"
                + (f", mismatched: {', '.join(mismatched[:5])}" if mismatched else "")
            )

    if checked == 0:
        print("no inverse-declared reverse edges in this schema")
    print(f"{checked} reverse edges checked: {checked - failed - vacuous} ok, "
          f"{vacuous} empty (no links in the data), {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
