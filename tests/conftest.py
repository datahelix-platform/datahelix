"""Shared pytest configuration for DataHelix contract and platform tests.

After the hippo split (PTS-282), :class:`mosaic.core.storage.adapters.sqlite_adapter.SQLiteAdapter`
requires a ``schema_registry`` argument. DataHelix-side tests previously called
the legacy single-arg form; this module provides a shared helper and fixture
that build a minimal :class:`mosaic.linkml_bridge.SchemaRegistry` covering
every entity type referenced by the contract and platform suites.

Mirrors ``mosaic/tests/conftest.py``'s ``_build_minimal_schema_registry``
helper but extends it with cross-component user-domain classes
(``Subject``, ``AlignedDatafile``, ``GenomeBuild``, etc.) used by DataHelix
integration tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Ensure component packages are importable regardless of how pytest is invoked.
_repo_root = Path(__file__).parent.parent
for _pkg in ("mosaic/src", "canon/src", "cappella/src"):
    _p = str(_repo_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

if TYPE_CHECKING:
    from mosaic.linkml_bridge import SchemaRegistry


# User-domain entity classes referenced by the contract and platform suites.
# Extend this set if a new test writes a previously-unused entity_type.
_TEST_ENTITY_CLASSES: tuple[str, ...] = (
    "Sample",
    "SampleEntity",
    "Subject",
    "Document",
    "Collection",
    "Donor",
    "Project",
    "Study",
    "TestEntity",
    "OtherType",
    "ErrorEntity",
    "Foo",
    "WrongType",
    "EntityA",
    "EntityB",
    "EntityC",
    "SelfEntity",
    "AlignedDatafile",
    "AlignedReads",
    "AlignmentFile",
    "GenomeBuild",
    "RawReads",
    "TrimmedReads",
    "ToolVersion",
)

# Permissive attribute set covering every field name tests write.
_TEST_ATTRIBUTES: dict[str, dict[str, str]] = {
    name: {"range": "string"}
    for name in (
        "name",
        "tissue",
        "tissue_type",
        "title",
        "description",
        "notes",
        "content",
        "value",
        "stage",
        "category",
        "diagnosis",
        "external_id",
        "label",
        "status",
        "species",
        "subject_id",
        "subject_external_id",
        "sample_id",
        "batch",
        "uri",
        "build",
        "version",
        "release",
        "source_uri",
        "source",
        "source_file",
        "raw_uri",
        "trimmed_uri",
        "fastq_uri",
        "reads_fastq",
        "input_uri",
        "output_uri",
        "genome_build",
        "tool",
        "reference",
        "ref",
        "checksum",
        "size",
        "owner",
        "kind",
        "target",
        "extra",
        "num",
        "x",
        "field1",
        "field2",
        "bam",
        "run_id",
        "workflow",
    )
}


def build_test_schema_registry() -> "SchemaRegistry":
    """Return a ``SchemaRegistry`` covering all DataHelix test entity classes.

    Built from an in-memory LinkML overlay that imports ``mosaic_core`` and
    declares the user-domain classes used by DataHelix contract and platform
    tests. Each declared class extends ``Entity`` and carries the union of
    string-typed attributes those tests write.
    """
    import yaml
    from linkml_runtime.utils.schemaview import SchemaView

    from mosaic.linkml_bridge import SchemaRegistry, _bundled_importmap

    overlay = {
        "id": "https://example.org/datahelix/tests_minimal",
        "name": "datahelix_tests_minimal",
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "mosaic": "https://w3id.org/datahelix/mosaic/",
        },
        "imports": ["linkml:types", "mosaic_core"],
        "default_range": "string",
        "classes": {
            cls: {"is_a": "Entity", "attributes": _TEST_ATTRIBUTES}
            for cls in _TEST_ENTITY_CLASSES
        },
    }
    return SchemaRegistry(
        SchemaView(yaml.safe_dump(overlay), importmap=_bundled_importmap())
    )


@pytest.fixture()
def test_schema_registry() -> "SchemaRegistry":
    """Pytest fixture wrapping :func:`build_test_schema_registry`."""
    return build_test_schema_registry()
