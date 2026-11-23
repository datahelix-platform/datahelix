"""Cross-component integration tests: Cappella → Hippo → Canon → Aperture.

This test suite validates the full data flow across all four DataHelix components,
exercising real in-process instances with mocked CWL execution.

## Test categories

1. CSV ingest via Cappella adapter → entity created in Hippo → Canon resolution
2. Entity relationships maintained across the pipeline
3. Provenance chain: Cappella ingest → Hippo entity → Canon resolution
4. Webhook trigger → Cappella adapter → Hippo entity creation
5. CLI (datahelix) commands query entities created by the pipeline
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src", "cappella/src", "aperture/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canon.exceptions import CanonNoRuleError
from canon.resolver.planner import RecursivePlanner
from canon.rules.models import ExecuteSpec, InputBinding, ProductionRule, ProducesSpec
from canon.rules.registry import RuleRegistry
from canon.types import Entity

from cappella.adapters.csv_adapter import CSVAdapter
from cappella.types import RawRecord, TransformedRecord
from cappella.triggers.models import WebhookConfig, TriggerProvenance

# conftest.py provides: hippo_client, hippo_shim, canon_config, mock_executor,
# seed_subject, seed_sample, seed_cohort, sample_csv_path, fixtures_dir


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
    """The single Canon rule for the integration scenario."""
    return ProductionRule(
        name="align_sample",
        description="Align a sample — integration test rule",
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
# 1. End-to-End Data Flow: CSV → Cappella → Hippo → Canon
# ---------------------------------------------------------------------------


@pytest.mark.platform
class TestCSVIngestToCanonResolution:
    """CSV ingest via Cappella adapter → Hippo entity → Canon resolution."""

    def test_csv_adapter_produces_raw_records(self, sample_csv_path):
        """Cappella CSV adapter fetches and yields RawRecord objects."""
        adapter = CSVAdapter(config={
            "entity_type": "Sample",
            "external_id_field": "sample_id",
            "source": "file",
            "url": str(sample_csv_path),
            "name": "test_csv",
        })

        records = list(adapter.fetch())
        assert len(records) == 3, "CSV with 3 rows must yield 3 RawRecords"
        assert all(isinstance(r, RawRecord) for r in records)
        assert records[0].external_id == "s001"
        assert records[0].data["tissue_type"] == "brain"

    def test_csv_adapter_transforms_records(self, sample_csv_path):
        """Cappella CSV adapter transforms RawRecord → TransformedRecord."""
        adapter = CSVAdapter(config={
            "entity_type": "Sample",
            "external_id_field": "sample_id",
            "source": "file",
            "url": str(sample_csv_path),
            "field_map": {"external_id": "subject_external_id"},
            "name": "test_csv",
        })

        records = list(adapter.fetch())
        transformed = adapter.transform(records[0])
        assert isinstance(transformed, TransformedRecord)
        assert transformed.entity_type == "Sample"
        assert transformed.external_id == "s001"

    def test_csv_ingest_creates_entities_in_hippo(
        self, hippo_client, seed_subject, sample_csv_path
    ):
        """Simulated Cappella CSV ingest creates Sample entities in Hippo.

        This simulates what IngestPipeline does: fetch → transform → create in Hippo.
        """
        adapter = CSVAdapter(config={
            "entity_type": "Sample",
            "external_id_field": "sample_id",
            "source": "file",
            "url": str(sample_csv_path),
            "name": "test_csv",
        })

        created_ids = []
        for raw in adapter.fetch():
            transformed = adapter.transform(raw)
            entity = hippo_client.create(
                "Sample",
                {
                    "subject_id": seed_subject["id"],
                    "tissue_type": transformed.data["tissue_type"],
                    "sample_id": transformed.external_id,
                },
            )
            created_ids.append(entity["id"])

        # All 3 samples exist in Hippo
        result = hippo_client.query("Sample")
        assert len(result.items) == 3
        sample_ids = {item["data"]["sample_id"] for item in result.items}
        assert sample_ids == {"s001", "s002", "s003"}

    def test_ingested_entity_resolvable_by_canon(
        self, hippo_client, hippo_shim, mock_executor, seed_subject, tmp_path
    ):
        """Entity ingested via Cappella adapter is resolvable by Canon BUILD path."""
        # Simulate Cappella ingest of one sample
        hippo_client.create(
            "Sample",
            {
                "subject_id": seed_subject["id"],
                "tissue_type": "brain",
                "sample_id": "s001",
            },
        )

        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        assert isinstance(uri, str) and uri.startswith("dhlx://")
        assert mock_executor.run.call_count == 1

        # AlignedDatafile written back to Hippo
        aligned = hippo_client.query("AlignedDatafile").items
        matching = [i for i in aligned if i["data"].get("sample_id") == "s001"]
        assert len(matching) == 1
        assert matching[0]["data"]["uri"] == uri

    def test_full_csv_ingest_then_cohort_resolution(
        self, hippo_client, hippo_shim, mock_executor, seed_subject, tmp_path
    ):
        """Full pipeline: CSV ingest of 3 samples → Canon resolution of cohort.

        Two samples resolve (AlignedDatafile rule matches), one resolves to
        a different entity type (QCReport) which has no rule → partial failure.
        """
        # Ingest all 3 samples from CSV
        csv_path = Path(__file__).parent.parent / "fixtures" / "sample_ingest.csv"
        adapter = CSVAdapter(config={
            "entity_type": "Sample",
            "external_id_field": "sample_id",
            "source": "file",
            "url": str(csv_path),
            "name": "test_csv",
        })

        for raw in adapter.fetch():
            transformed = adapter.transform(raw)
            hippo_client.create(
                "Sample",
                {
                    "subject_id": seed_subject["id"],
                    "tissue_type": transformed.data["tissue_type"],
                    "sample_id": transformed.external_id,
                },
            )

        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)

        resolved = []
        unresolved = []

        for sample_id, entity_type, params in [
            ("s001", "AlignedDatafile", {"sample_id": "s001"}),
            ("s002", "AlignedDatafile", {"sample_id": "s002"}),
            ("s003", "QCReport", {"sample_id": "s003"}),  # no rule → NO_RULE
        ]:
            try:
                uri = planner.resolve(entity_type, params)
                resolved.append({"sample_id": sample_id, "uri": uri})
            except CanonNoRuleError:
                unresolved.append({"sample_id": sample_id, "reason": "NO_RULE"})

        assert len(resolved) == 2
        assert len(unresolved) == 1
        assert unresolved[0]["sample_id"] == "s003"

        # Resolved entities exist in Hippo
        aligned = hippo_client.query("AlignedDatafile").items
        aligned_ids = {i["data"].get("sample_id") for i in aligned}
        assert "s001" in aligned_ids
        assert "s002" in aligned_ids
        assert "s003" not in aligned_ids


# ---------------------------------------------------------------------------
# 2. Entity Relationships Across Pipeline
# ---------------------------------------------------------------------------


@pytest.mark.platform
class TestEntityRelationships:
    """Validate entity relationships are maintained across the pipeline."""

    def test_sample_references_subject(self, hippo_client, seed_subject):
        """Sample entity references Subject by UUID across component boundaries."""
        sample = hippo_client.create(
            "Sample",
            {"subject_id": seed_subject["id"], "tissue_type": "brain", "sample_id": "s001"},
        )
        fetched = hippo_client.get("Sample", sample["id"])
        assert fetched["data"]["subject_id"] == seed_subject["id"]

    def test_aligned_datafile_references_sample(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """AlignedDatafile built by Canon references the original Sample."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile").items
        matching = [i for i in aligned if i["data"].get("sample_id") == "s001"]
        assert len(matching) == 1, "AlignedDatafile must reference original sample_id"

    def test_subject_to_aligned_datafile_chain(
        self, hippo_client, hippo_shim, mock_executor, seed_subject, tmp_path
    ):
        """Full reference chain: Subject → Sample → AlignedDatafile."""
        sample = hippo_client.create(
            "Sample",
            {"subject_id": seed_subject["id"], "tissue_type": "brain", "sample_id": "s001"},
        )

        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        # Trace the chain: Subject → Sample → AlignedDatafile
        fetched_sample = hippo_client.get("Sample", sample["id"])
        assert fetched_sample["data"]["subject_id"] == seed_subject["id"]

        aligned = hippo_client.query("AlignedDatafile").items
        matching = [i for i in aligned if i["data"].get("sample_id") == "s001"]
        assert len(matching) == 1
        assert matching[0]["data"]["uri"] == uri


# ---------------------------------------------------------------------------
# 3. Provenance Chain: Cappella → Hippo → Canon
# ---------------------------------------------------------------------------


@pytest.mark.platform
class TestProvenanceChain:
    """Verify provenance is maintained across the full pipeline."""

    def test_entity_version_after_create(self, hippo_client, seed_sample):
        """Entity created during Cappella ingest has version=1."""
        fetched = hippo_client.get("Sample", seed_sample["id"])
        assert fetched.get("version") == 1

    def test_canon_build_creates_entity_with_version(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """Canon BUILD path creates a new entity with version=1 in Hippo."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile").items
        matching = [i for i in aligned if i["data"].get("sample_id") == "s001"]
        assert len(matching) == 1
        entity_id = matching[0]["id"]
        fetched = hippo_client.get("AlignedDatafile", entity_id)
        assert fetched.get("version") == 1

    def test_canon_build_uri_matches_hippo_stored_uri(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """URI returned by Canon resolve() matches what's stored in Hippo."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        canon_uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        aligned = hippo_client.query("AlignedDatafile").items
        matching = [i for i in aligned if i["data"].get("sample_id") == "s001"]
        assert matching[0]["data"]["uri"] == canon_uri

    def test_reuse_after_build_preserves_uri(
        self, hippo_client, hippo_shim, mock_executor, seed_sample, tmp_path
    ):
        """After BUILD, a second resolve() returns REUSE with the same URI."""
        rule = _align_rule()
        planner = _make_planner(hippo_shim, [rule], mock_executor, tmp_path)
        uri1 = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        uri2 = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

        assert uri1 == uri2
        assert mock_executor.run.call_count == 1, "Second resolve must be REUSE (no executor)"
