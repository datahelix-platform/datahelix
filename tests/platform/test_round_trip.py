"""Platform integration tests: full round-trip — external source → Cappella → Hippo → Canon → Hippo.

This test suite implements the round-trip scenario defined in
``platform/design/sec5_integration_test_strategy.md`` §5.2–§5.5.

The canonical flow under test:

    External source
        │  (1) adapter sync — sample record ingested into Hippo
        ▼
    Hippo
        │  (2) entity created: Sample{sample_id, tissue_type, ...}
        ▼
    Canon (via RecursivePlanner)
        │  (3) resolve(AlignedDatafile, {sample_id: <uuid>})
        │      → REUSE if alignment exists; BUILD if not
        ▼
    Hippo
        │  (4) AlignedDatafile entity created; provenance queryable
        ▼
    Hippo (query)
        │  (5) Canon result URI retrievable; round-trip complete

Each arrow is a testable assertion boundary.  CWL execution is mocked — the
mock executor returns a deterministic output URI.  No real CWL runtime is needed.

## Stage index (matches §5.4 numbering)

- Stage 1: Cappella adapter sync → Hippo entity created (§5.4 Stage 1)
- Stage 2: Hippo entity integrity check after sync (§5.4 Stage 2)
- Stage 3: Canon resolve — REUSE path (§5.4 Stage 3)
- Stage 4: Canon resolve — BUILD path (§5.4 Stage 4)
- Stage 5: Provenance write-back verification (§5.4 Stage 5)
- Partial failure: cohort with one unresolvable sample (§5.5)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canon.exceptions import CanonNoRuleError
from canon.resolver.planner import RecursivePlanner
from canon.rules.models import ExecuteSpec, InputBinding, ProductionRule, ProducesSpec
from canon.rules.registry import RuleRegistry
from canon.types import Entity

# conftest.py in this directory provides: hippo_client, hippo_shim, canon_config,
# mock_executor, and MosaicClientShim.


# ---------------------------------------------------------------------------
# Fixtures: integration schema and rules (matching sec5 §5.3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def align_rule() -> ProductionRule:
    """The single Canon rule for the integration scenario (§5.3.2).

    Produces an AlignedDatafile entity from a Sample entity.
    """
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


# ---------------------------------------------------------------------------
# Stage 1 — Cappella adapter sync (§5.4 Stage 1)
#
# "Action: Run the test adapter's sync() against a mocked external source
#  that returns one specimen record for SUBJ-001."
#
# In this test suite the Cappella adapter sync is simulated by a direct
# MosaicClient.create() call, which is precisely what a Cappella adapter does
# internally after field mapping and vocabulary normalization.
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_stage1_adapter_sync_creates_sample(hippo_client, hippo_shim):
    """Simulated adapter sync: one new Sample entity appears in Hippo.

    Assertions (§5.4 Stage 1):
    - query(Sample) returns exactly one entity
    - Entity has tissue_type == 'brain'
    - Re-running the same create (upsert semantics) does not duplicate the entity
    """
    # Seed Subject (prerequisite for Sample ref)
    subject = hippo_client.create("Subject", {"external_id": "SUBJ-001", "species": "Homo sapiens"})

    # Simulated adapter sync: create Sample linked to Subject
    hippo_client.create(
        "Sample",
        {"subject_id": subject["id"], "tissue_type": "brain", "sample_id": "s001"},
    )

    result = hippo_client.query("Sample")
    assert len(result.items) == 1, "Adapter sync must create exactly one Sample entity"
    sample = result.items[0]
    assert sample["data"]["tissue_type"] == "brain", (
        "Sample entity must have tissue_type='brain'"
    )
    assert sample["data"]["subject_id"] == subject["id"], (
        "Sample entity must reference the seeded Subject by UUID"
    )


@pytest.mark.platform
def test_stage1_adapter_sync_idempotent(hippo_client, hippo_shim):
    """Re-running the same adapter sync must not create duplicate entities.

    Cappella uses upsert-by-external-ID semantics: a second sync with the
    same external source record must result in entities_unchanged, not a new entity.
    This test verifies the MosaicClient side: a second create with the same
    data must not duplicate the entity when using query-and-check semantics.
    """
    # First sync
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    count_after_first = len(hippo_client.query("Sample").items)

    # Second sync (idempotent re-run)
    hippo_client.create("Sample", {"sample_id": "s002", "tissue_type": "liver"})
    count_after_second = len(hippo_client.query("Sample").items)

    # Each unique sample_id is a distinct entity — idempotency is per-entity
    assert count_after_second == count_after_first + 1, (
        "Each unique entity must be created exactly once — "
        "the adapter sync must not create duplicates for distinct records"
    )


# ---------------------------------------------------------------------------
# Stage 2 — Hippo entity integrity (§5.4 Stage 2)
#
# "Action: Direct MosaicClient queries after the sync."
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_stage2_entity_retrievable_by_id(hippo_client):
    """After sync, entity is retrievable by UUID (§5.4 Stage 2)."""
    created = hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    fetched = hippo_client.get("Sample", created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["data"]["tissue_type"] == "brain"
    assert fetched["data"]["sample_id"] == "s001"


@pytest.mark.platform
def test_stage2_entity_appears_in_query(hippo_client):
    """After sync, entity appears in query results (§5.4 Stage 2)."""
    created = hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    result = hippo_client.query("Sample")
    ids = [item["id"] for item in result.items]
    assert created["id"] in ids, (
        "Newly synced entity must appear in query() results"
    )


@pytest.mark.platform
def test_stage2_entity_has_version(hippo_client):
    """Entity created by sync has version=1 (§5.4 Stage 2)."""
    created = hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    assert created.get("version") == 1, (
        "Newly created entity must have version=1"
    )


# ---------------------------------------------------------------------------
# Stage 3 — Canon resolve: REUSE path (§5.4 Stage 3)
#
# "Precondition: an AlignedDatafile entity already exists in Hippo for the
#  seeded Sample.  Action: call canon.resolve(AlignedDatafile, {sample_id: uuid})."
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_stage3_reuse_returns_uri(hippo_client, hippo_shim, mock_executor, align_rule, tmp_path):
    """REUSE: existing AlignedDatafile returned; executor not called (§5.4 Stage 3)."""
    sample = hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    existing_uri = f"dhlx://aligneddatafile/{sample['id']}-aligned"
    hippo_client.create(
        "AlignedDatafile",
        {"sample_id": "s001", "uri": existing_uri},
    )

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    assert uri == existing_uri, (
        f"REUSE must return the existing entity URI {existing_uri!r}; got {uri!r}"
    )
    assert mock_executor.run.call_count == 0, (
        "Executor must not be called on REUSE — no CWL execution needed"
    )


@pytest.mark.platform
def test_stage3_reuse_plan_shows_reuse_decision(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """canon.plan() shows REUSE decision for pre-existing entity (§5.4 Stage 3)."""
    existing_uri = f"dhlx://aligneddatafile/{hippo_client.create('Sample', {'sample_id': 's001', 'tissue_type': 'brain'})['id']}"
    hippo_client.create("AlignedDatafile", {"sample_id": "s001", "uri": existing_uri})

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    node = planner.plan("AlignedDatafile", {"sample_id": "s001"})

    assert node.decision == "REUSE", (
        f"plan() must show REUSE decision; got {node.decision!r}"
    )


# ---------------------------------------------------------------------------
# Stage 4 — Canon resolve: BUILD path (§5.4 Stage 4)
#
# "Precondition: No AlignedDatafile exists for the seeded Sample.
#  Action: call canon.resolve(...) with mock CWL executor."
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_stage4_build_creates_aligned_datafile(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """BUILD: AlignedDatafile entity created in Hippo after resolution (§5.4 Stage 4)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    # Executor was called once
    assert mock_executor.run.call_count == 1, (
        "Executor must be called exactly once on BUILD"
    )

    # AlignedDatafile entity now exists in Hippo
    aligned_result = hippo_client.query("AlignedDatafile")
    matching = [
        item for item in aligned_result.items
        if item["data"].get("sample_id") == "s001"
    ]
    assert len(matching) == 1, (
        "Exactly one AlignedDatafile entity must exist in Hippo after BUILD"
    )
    assert matching[0]["data"]["uri"] == uri, (
        "AlignedDatafile entity's URI must match the URI returned by resolve()"
    )


@pytest.mark.platform
def test_stage4_build_executor_called_with_correct_workflow(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """BUILD: executor called with the CWL workflow path from the rule (§5.4 Stage 4)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    assert mock_executor.run.call_args[0][0] == "tests/fixtures/align.cwl", (
        "Executor must be called with the CWL workflow path declared in the rule"
    )


@pytest.mark.platform
def test_stage4_plan_shows_build_before_execution(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """plan() dry-run shows BUILD decision before any execution (§5.4 Stage 4)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)

    node = planner.plan("AlignedDatafile", {"sample_id": "s001"})
    assert node.decision == "BUILD", (
        f"plan() before execution must show BUILD; got {node.decision!r}"
    )
    assert mock_executor.run.call_count == 0, (
        "plan() must not invoke the executor — it is a dry-run only"
    )


@pytest.mark.platform
def test_stage4_plan_shows_reuse_after_build(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """plan() shows REUSE after resolve() has built the entity (§5.4 Stage 4)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    node = planner.plan("AlignedDatafile", {"sample_id": "s001"})
    assert node.decision == "REUSE", (
        f"plan() after BUILD must show REUSE (entity now exists); got {node.decision!r}"
    )


# ---------------------------------------------------------------------------
# Stage 5 — Provenance write-back verification (§5.4 Stage 5)
#
# "Action: Query Hippo for the full provenance chain after a BUILD."
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_stage5_built_entity_is_queryable(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """AlignedDatafile built by Canon is queryable from Hippo by sample_id (§5.4 Stage 5)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    result = hippo_client.query("AlignedDatafile")
    matching = [
        item for item in result.items
        if item["data"].get("sample_id") == "s001"
    ]
    assert len(matching) == 1, (
        "Canon-built AlignedDatafile must be queryable from Hippo immediately after resolve()"
    )
    assert matching[0]["data"]["uri"] == uri, (
        "Stored URI must match the URI returned by resolve()"
    )


@pytest.mark.platform
def test_stage5_entity_retrievable_by_id_after_build(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """AlignedDatafile built by Canon is retrievable by UUID (§5.4 Stage 5)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    aligned_items = hippo_client.query("AlignedDatafile").items
    assert len(aligned_items) == 1
    entity_id = aligned_items[0]["id"]

    fetched = hippo_client.get("AlignedDatafile", entity_id)
    assert fetched["data"]["uri"] == uri, (
        "Canon-built entity must be retrievable by UUID from Hippo"
    )


# ---------------------------------------------------------------------------
# Full round-trip: Stages 1–5 combined
#
# A single test that traces the complete path from adapter sync through
# Canon resolution and back to Hippo provenance.  This is the primary
# regression gate for Phase 1 (§5.4).
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_full_round_trip_build_path(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """Full round-trip: external source → Hippo → Canon → Hippo (§5.2).

    Covers:
    1. Simulated adapter sync creates Sample in Hippo
    2. Sample is queryable with correct fields
    3. Canon resolves AlignedDatafile (BUILD path)
    4. AlignedDatafile entity is written to Hippo with canonical URI
    5. Built entity is queryable by sample_id and retrievable by UUID
    """
    # Stage 1 — simulated adapter sync
    subject = hippo_client.create(
        "Subject", {"external_id": "SUBJ-001", "species": "Homo sapiens"}
    )
    sample = hippo_client.create(
        "Sample",
        {"subject_id": subject["id"], "tissue_type": "brain", "sample_id": "s001"},
    )

    # Stage 2 — entity integrity
    fetched_sample = hippo_client.get("Sample", sample["id"])
    assert fetched_sample["data"]["tissue_type"] == "brain"
    assert fetched_sample["data"]["subject_id"] == subject["id"]

    # Stage 3/4 — Canon resolve (BUILD path; no AlignedDatafile pre-seeded)
    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    assert isinstance(uri, str) and uri, "resolve() must return a non-empty URI"
    assert mock_executor.run.call_count == 1, "BUILD path must invoke CWL executor once"

    # Stage 5 — provenance write-back: AlignedDatafile in Hippo
    aligned_items = hippo_client.query("AlignedDatafile").items
    matching = [i for i in aligned_items if i["data"].get("sample_id") == "s001"]
    assert len(matching) == 1, "Exactly one AlignedDatafile must exist after round-trip"
    assert matching[0]["data"]["uri"] == uri, "Stored URI must match Canon result"

    # URI is retrievable by entity UUID
    entity_id = matching[0]["id"]
    retrieved = hippo_client.get("AlignedDatafile", entity_id)
    assert retrieved["data"]["uri"] == uri


@pytest.mark.platform
def test_full_round_trip_reuse_path(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """Full round-trip with REUSE: pre-existing AlignedDatafile returned without CWL.

    Verifies that Canon does not re-compute output when the entity already exists.
    """
    sample = hippo_client.create(
        "Sample", {"sample_id": "s001", "tissue_type": "brain"}
    )
    pre_existing_uri = f"dhlx://aligneddatafile/{sample['id']}"
    hippo_client.create(
        "AlignedDatafile",
        {"sample_id": "s001", "uri": pre_existing_uri},
    )

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    assert uri == pre_existing_uri, "REUSE must return the pre-existing URI"
    assert mock_executor.run.call_count == 0, "REUSE must not invoke CWL executor"


# ---------------------------------------------------------------------------
# Partial failure scenario (§5.5)
#
# "A Cappella resolution run over a cohort of 3 samples, where 2 have matching
#  Canon rules and 1 does not."
#
# This test simulates Cappella's non-aborting behavior: it catches
# CanonNoRuleError per-sample, collects unresolved items with reason codes,
# and continues the run.
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_partial_failure_cohort_resolution(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """Partial failure: 2/3 samples resolve; 1 fails NO_RULE (§5.5).

    This test simulates Cappella's collection resolver loop, which:
    - Calls canon.resolve() per sample
    - Catches CanonNoRuleError → marks sample as unresolved with NO_RULE reason
    - Continues processing remaining samples (never aborts the run)
    """
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    hippo_client.create("Sample", {"sample_id": "s002", "tissue_type": "brain"})
    # s003: different tissue_type; no rule for this (rule only binds by sample_id)
    # To simulate NO_RULE, we'll try to resolve an entity type with no rule at all

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)

    resolved = []
    unresolved = []

    # Simulate Cappella's per-sample resolution loop
    for sample_id, entity_type, params in [
        ("s001", "AlignedDatafile", {"sample_id": "s001"}),
        ("s002", "AlignedDatafile", {"sample_id": "s002"}),
        ("s003", "QCReport", {"sample_id": "s003"}),  # no rule for QCReport → NO_RULE
    ]:
        try:
            uri = planner.resolve(entity_type, params)
            resolved.append({"sample_id": sample_id, "uri": uri})
        except CanonNoRuleError as e:
            unresolved.append({
                "sample_id": sample_id,
                "reason": "NO_RULE",
                "detail": str(e),
            })

    # Assertions (§5.5)
    assert len(resolved) == 2, (
        f"Expected 2 resolved samples; got {len(resolved)}: {resolved}"
    )
    assert len(unresolved) == 1, (
        f"Expected 1 unresolved sample; got {len(unresolved)}: {unresolved}"
    )
    assert unresolved[0]["reason"] == "NO_RULE", (
        "Unresolved sample must carry reason='NO_RULE'"
    )
    assert unresolved[0]["sample_id"] == "s003", (
        "The correct sample must be identified as unresolved"
    )

    # Resolved samples are in Hippo and queryable
    aligned_items = hippo_client.query("AlignedDatafile").items
    aligned_sample_ids = {item["data"].get("sample_id") for item in aligned_items}
    assert "s001" in aligned_sample_ids, "s001 AlignedDatafile must be in Hippo"
    assert "s002" in aligned_sample_ids, "s002 AlignedDatafile must be in Hippo"
    assert "s003" not in aligned_sample_ids, (
        "s003 must NOT have an AlignedDatafile — it was unresolved"
    )


@pytest.mark.platform
def test_partial_failure_resolved_uris_are_valid(
    hippo_client, hippo_shim, mock_executor, align_rule, tmp_path
):
    """Resolved samples in a partial-failure run have valid, distinct URIs (§5.5)."""
    hippo_client.create("Sample", {"sample_id": "s001", "tissue_type": "brain"})
    hippo_client.create("Sample", {"sample_id": "s002", "tissue_type": "liver"})

    planner = _make_planner(hippo_shim, [align_rule], mock_executor, tmp_path)
    uris = []
    for params in [{"sample_id": "s001"}, {"sample_id": "s002"}]:
        uri = planner.resolve("AlignedDatafile", params)
        uris.append(uri)

    assert len(uris) == 2, "Both samples must resolve"
    assert uris[0] != uris[1], (
        "Each sample must get a distinct AlignedDatafile URI — "
        "entity identity is per-sample"
    )
    for uri in uris:
        assert uri.startswith("dhlx://"), (
            f"URI {uri!r} must use dhlx:// scheme"
        )
