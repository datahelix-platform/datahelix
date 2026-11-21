"""Platform integration tests: Aperture CLI (datahelix) → Hippo.

Tests validate that `datahelix` CLI commands correctly interact with entities
created by the upstream pipeline (Cappella → Hippo → Canon).

These tests use the HippoSdkBackend directly (no HTTP server) to exercise
the same code paths as the CLI commands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mosaic.core.client import MosaicClient
from canon.resolver.planner import RecursivePlanner
from canon.rules.models import ExecuteSpec, InputBinding, ProductionRule, ProducesSpec
from canon.rules.registry import RuleRegistry
from canon.types import Entity
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_planner(hippo_shim, rules, executor, tmp_path) -> RecursivePlanner:
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = Entity(
        id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
    )
    return RecursivePlanner(
        hippo_client=hippo_shim,
        rule_registry=RuleRegistry(rules),
        entity_ref_resolver=ref_resolver,
        executor=executor,
        ingestion_pipeline=None,
        work_dir_base=str(tmp_path / "work"),
    )


def _align_rule() -> ProductionRule:
    return ProductionRule(
        name="align_sample",
        description="Align a sample",
        produces=ProducesSpec(
            entity_type="AlignedDatafile",
            match={"sample_id": "{sample_id}"},
        ),
        requires=[
            InputBinding(
                bind="sample_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="tests/fixtures/align.cwl",
            inputs={"sample_id": "{sample_id}"},
        ),
    )


# ---------------------------------------------------------------------------
# CLI-equivalent operations: list, get, search
#
# These tests simulate what `datahelix list`, `datahelix get`, `datahelix search`, and
# `datahelix history` do internally — they call the MosaicClient SDK directly,
# which is the same code path used by HippoSdkBackend.
# ---------------------------------------------------------------------------


@pytest.mark.platform
class TestCLIListEntities:
    """Simulate `datahelix list` — list entities of a given type."""

    def test_list_returns_all_entities(self, hippo_client, seed_cohort):
        """datahelix list Sample returns all 3 seeded samples."""
        result = hippo_client.query("Sample")
        assert len(result.items) == 3

    def test_list_returns_empty_for_unknown_type(self, hippo_client):
        """datahelix list NonExistent returns empty results."""
        result = hippo_client.query("NonExistent")
        assert len(result.items) == 0

    def test_list_after_canon_build(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """datahelix list AlignedDatafile returns entity created by Canon BUILD."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile")
        assert len(aligned.items) == 1
        assert aligned.items[0]["data"]["sample_id"] == "s001"


@pytest.mark.platform
class TestCLIGetEntity:
    """Simulate `datahelix get` — fetch a single entity by UUID."""

    def test_get_returns_entity_by_id(self, hippo_client, seed_sample):
        """datahelix get Sample <uuid> returns the correct entity."""
        fetched = hippo_client.get("Sample", seed_sample["id"])
        assert fetched["id"] == seed_sample["id"]
        assert fetched["data"]["sample_id"] == "s001"
        assert fetched["data"]["tissue_type"] == "brain"

    def test_get_canon_built_entity(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """datahelix get AlignedDatafile <uuid> returns Canon-built entity."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile").items
        entity_id = aligned[0]["id"]
        fetched = hippo_client.get("AlignedDatafile", entity_id)
        assert fetched["data"]["uri"] == uri
        assert fetched["data"]["sample_id"] == "s001"


@pytest.mark.platform
class TestCLISearchEntities:
    """Simulate `datahelix search` — search entities by field value."""

    def test_search_by_query_finds_matching(self, hippo_client, seed_cohort):
        """Search for entities with tissue_type='brain' returns matching samples."""
        result = hippo_client.query("Sample")
        matching = [
            item for item in result.items
            if item["data"].get("tissue_type") == "brain"
        ]
        assert len(matching) == 1
        assert matching[0]["data"]["sample_id"] == "s001"

    def test_search_by_sample_id(self, hippo_client, seed_cohort):
        """Search for a specific sample_id returns exactly one result."""
        result = hippo_client.query("Sample")
        matching = [
            item for item in result.items
            if item["data"].get("sample_id") == "s002"
        ]
        assert len(matching) == 1
        assert matching[0]["data"]["tissue_type"] == "liver"


@pytest.mark.platform
class TestCLIHistory:
    """Simulate `datahelix history` — view entity provenance/version history."""

    def test_entity_has_version_after_create(self, hippo_client, seed_sample):
        """Newly created entity has version=1."""
        fetched = hippo_client.get("Sample", seed_sample["id"])
        assert fetched.get("version") == 1

    def test_entity_version_increments_on_update(self, hippo_client, seed_sample):
        """Entity version increments after an update."""
        hippo_client.update(
            "Sample", seed_sample["id"],
            {**seed_sample["data"], "tissue_type": "cortex"},
        )
        fetched = hippo_client.get("Sample", seed_sample["id"])
        assert fetched.get("version") == 2

    def test_canon_built_entity_has_version(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """Canon-built AlignedDatafile has version=1."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile").items
        entity_id = aligned[0]["id"]
        fetched = hippo_client.get("AlignedDatafile", entity_id)
        assert fetched.get("version") == 1


# ---------------------------------------------------------------------------
# End-to-end: ingest data → query via CLI-equivalent operations
# ---------------------------------------------------------------------------


@pytest.mark.platform
class TestCLIEndToEnd:
    """Full flow: ingest → Canon resolution → CLI queries."""

    def test_ingest_resolve_then_query(
        self, hippo_client, hippo_shim, mock_executor, seed_subject, tmp_path
    ):
        """Ingest sample, resolve via Canon, then query all entities via CLI ops.

        Covers the full Cappella → Hippo → Canon → Aperture (CLI) path.
        """
        # Step 1: Ingest (Cappella → Hippo)
        sample = hippo_client.create(
            "Sample",
            {"subject_id": seed_subject["id"], "tissue_type": "brain", "sample_id": "s001"},
        )

        # Step 2: Resolve (Hippo → Canon → Hippo)
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        # Step 3: CLI queries (Aperture → Hippo)
        # datahelix list Sample
        samples = hippo_client.query("Sample")
        assert len(samples.items) == 1

        # datahelix list AlignedDatafile
        aligned = hippo_client.query("AlignedDatafile")
        assert len(aligned.items) == 1

        # datahelix get Sample <uuid>
        fetched_sample = hippo_client.get("Sample", sample["id"])
        assert fetched_sample["data"]["tissue_type"] == "brain"

        # datahelix get AlignedDatafile <uuid>
        aligned_id = aligned.items[0]["id"]
        fetched_aligned = hippo_client.get("AlignedDatafile", aligned_id)
        assert fetched_aligned["data"]["uri"] == uri
        assert fetched_aligned["data"]["sample_id"] == "s001"

        # Verify the full chain is queryable
        assert fetched_sample["data"]["subject_id"] == seed_subject["id"]
