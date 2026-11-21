"""Platform integration tests: real Mosaic ↔ Canon cross-cutting contract.

Tests exercise RecursivePlanner talking to a real in-process MosaicClient
backed by SQLiteAdapter.  No HTTP server; no actual CWL execution.

## Category taxonomy

### Implemented
1. REUSE path (entity already in Mosaic → executor not called)
2. BUILD path (entity absent → executor called → entity ingested into Mosaic)
3. Cycle detection — 2-node mutual dependency
4. Multi-level dependency chain — executor called N× bottom-up
5. Entity built by Canon is queryable in Mosaic with URI populated
6. Re-resolution idempotency — resolve() twice, executor called once
7. Failure recovery — partial chain failure leaves Mosaic consistent
8. Three-node cycle detection (A→B→C→A)
9. plan() dry-run uses real Mosaic state for REUSE/BUILD decisions
10. No-rule error — CanonNoRuleError when no rule matches unknown entity
11. Full bioinformatics 4-step chain (Sample→RawReads→TrimmedReads→AlignedReads)

### Pending
- WorkflowRun provenance entity written to Mosaic (ingestion_pipeline not None)
- Schema-rules consistency via real schema loaded from YAML
- hippo-reference-canon entry point wiring (requires CLI plumbing)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from canon.exceptions import CanonCycleError, CanonStorageError
from canon.resolver.planner import RecursivePlanner
from canon.rules.models import ExecuteSpec, FetchRule, InputBinding, ProductionRule, ProducesSpec
from canon.rules.registry import RuleRegistry
from canon.storage.http import HTTPStorageAdapter
from canon.storage.local import LocalStorageAdapter
from canon.types import Entity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_planner(
    hippo_shim,
    registry: RuleRegistry,
    executor: MagicMock,
    tmp_path,
) -> RecursivePlanner:
    """Build a RecursivePlanner wired to the in-process shim."""
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = Entity(
        id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
    )
    return RecursivePlanner(
        hippo_client=hippo_shim,
        rule_registry=registry,
        entity_ref_resolver=ref_resolver,
        executor=executor,
        ingestion_pipeline=None,
        work_dir_base=str(tmp_path / "work"),
    )


def _make_planner_with_storage(
    hippo_shim,
    registry: RuleRegistry,
    local_adapter: LocalStorageAdapter,
    https_adapter,
    tmp_path,
) -> RecursivePlanner:
    """Build a RecursivePlanner wired to real storage adapters."""
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = Entity(
        id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
    )
    return RecursivePlanner(
        hippo_client=hippo_shim,
        rule_registry=registry,
        entity_ref_resolver=ref_resolver,
        executor=None,
        ingestion_pipeline=None,
        work_dir_base=str(tmp_path / "work"),
        storage_adapter=local_adapter,
        https_adapter=https_adapter,
    )


# ---------------------------------------------------------------------------
# Test 1: REUSE path — existing entity returned, executor not called
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_reuse_existing_entity(hippo_client, hippo_shim, mock_executor, tmp_path):
    """When RawReads already exists in Mosaic, executor must not be called."""
    hippo_client.create(
        "RawReads",
        {
            "sample_id": "s001",
            "fastq_uri": "file:///data/s001.fastq.gz",
            "uri": "dhlx://rawreads/s001",
        },
    )

    # Empty registry — no rules needed; entity already exists
    registry = RuleRegistry([])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri = planner.resolve("RawReads", {"sample_id": "s001"})

    assert uri == "dhlx://rawreads/s001"
    assert mock_executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Test 2: BUILD path — executor called once, entity stored in Mosaic
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_build_missing_entity(hippo_client, hippo_shim, mock_executor, tmp_path):
    """When RawReads is absent, executor runs once and entity is stored in Mosaic."""
    # Prerequisite: Sample exists; RawReads does not
    hippo_client.create("Sample", {"sample_id": "s001"})

    build_raw_reads = ProductionRule(
        name="build_raw_reads",
        description="Build RawReads from Sample",
        produces=ProducesSpec(
            entity_type="RawReads",
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
            workflow="workflows/build_raw_reads.cwl",
            inputs={"sample_id": "{sample_id}"},
        ),
    )

    registry = RuleRegistry([build_raw_reads])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri = planner.resolve("RawReads", {"sample_id": "s001"})

    # Executor called exactly once for the correct workflow
    assert mock_executor.run.call_count == 1
    assert mock_executor.run.call_args[0][0] == "workflows/build_raw_reads.cwl"

    # RawReads entity now queryable from real Mosaic
    raw_reads_result = hippo_client.query("RawReads")
    matching = [
        item
        for item in raw_reads_result.items
        if item["data"].get("sample_id") == "s001"
    ]
    assert len(matching) == 1
    assert matching[0]["data"]["uri"] == uri


# ---------------------------------------------------------------------------
# Test 3: Cycle detection — CanonCycleError raised
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_cycle_detection_raises(hippo_shim, mock_executor, tmp_path):
    """Two rules with a circular dependency raise CanonCycleError."""
    rule_a = ProductionRule(
        name="rule_a",
        description="",
        produces=ProducesSpec(
            entity_type="EntityA", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="b_in",
                entity_type="EntityB",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="a.cwl", inputs={}),
    )
    rule_b = ProductionRule(
        name="rule_b",
        description="",
        produces=ProducesSpec(
            entity_type="EntityB", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="a_in",
                entity_type="EntityA",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={}),
    )

    registry = RuleRegistry([rule_a, rule_b])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    with pytest.raises(CanonCycleError):
        planner.resolve("EntityA", {"sample_id": "s001"})

    assert mock_executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Test 4: 3-level dependency chain — executor called 3×, all entities in Mosaic
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_dependency_chain_inserts_all(hippo_client, hippo_shim, mock_executor, tmp_path):
    """3-level chain (rule_c→rule_b→rule_a): executor called 3× bottom-up,
    all intermediate entities queryable from real Mosaic afterward."""

    # Only Sample exists in Mosaic; nothing else pre-exists
    hippo_client.create("Sample", {"sample_id": "s001"})

    # rule_a: Sample (REUSE) → build RawReads
    rule_a = ProductionRule(
        name="rule_a",
        description="Build RawReads from Sample",
        produces=ProducesSpec(
            entity_type="RawReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="sample_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="a.cwl",
            inputs={"sample_id": "{sample_id}"},
        ),
    )
    # rule_b: RawReads → build TrimmedReads
    rule_b = ProductionRule(
        name="rule_b",
        description="Build TrimmedReads from RawReads",
        produces=ProducesSpec(
            entity_type="TrimmedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="raw_in",
                entity_type="RawReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="b.cwl",
            inputs={"raw_uri": "{raw_in.uri}"},
        ),
    )
    # rule_c: TrimmedReads → build AlignedReads  (top-level goal)
    rule_c = ProductionRule(
        name="rule_c",
        description="Build AlignedReads from TrimmedReads",
        produces=ProducesSpec(
            entity_type="AlignedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="trimmed_in",
                entity_type="TrimmedReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="c.cwl",
            inputs={"trimmed_uri": "{trimmed_in.uri}"},
        ),
    )

    registry = RuleRegistry([rule_a, rule_b, rule_c])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri = planner.resolve("AlignedReads", {"sample_id": "s001"})

    # Executor called exactly 3 times, bottom-up order: a → b → c
    assert mock_executor.run.call_count == 3
    cwl_paths = [call[0][0] for call in mock_executor.run.call_args_list]
    assert cwl_paths == ["a.cwl", "b.cwl", "c.cwl"]

    # All 3 intermediate entities are now queryable from real Mosaic
    for entity_type in ("RawReads", "TrimmedReads", "AlignedReads"):
        result = hippo_client.query(entity_type)
        matching = [
            item
            for item in result.items
            if item["data"].get("sample_id") == "s001"
        ]
        assert len(matching) == 1, f"{entity_type} not found in Mosaic after chain execution"

    assert uri.startswith("dhlx://alignedreads/")


# ---------------------------------------------------------------------------
# Category 5: Entity built by Canon has URI populated in Mosaic data
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_entity_built_by_canon_has_uri_in_mosaic_data(
    hippo_client, hippo_shim, mock_executor, tmp_path
):
    """After BUILD, the entity stored in Mosaic contains the uri field in its data."""
    hippo_client.create("Sample", {"sample_id": "s001"})

    rule = ProductionRule(
        name="build_raw",
        description="",
        produces=ProducesSpec(
            entity_type="RawReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="sample_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="raw.cwl", inputs={}),
    )

    registry = RuleRegistry([rule])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri = planner.resolve("RawReads", {"sample_id": "s001"})

    # The entity in Mosaic must carry the uri field in its data dict
    result = hippo_client.query("RawReads")
    items = [
        item
        for item in result.items
        if item["data"].get("sample_id") == "s001"
    ]
    assert len(items) == 1
    assert items[0]["data"].get("uri") == uri


# ---------------------------------------------------------------------------
# Category 6: Re-resolution idempotency
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_resolve_idempotent_second_call_is_reuse(
    hippo_client, hippo_shim, mock_executor, tmp_path
):
    """Resolve the same entity twice: executor called exactly once.

    After the first BUILD, the entity exists in Mosaic.  The second resolve()
    follows the REUSE path and must not re-invoke the executor.
    """
    hippo_client.create("Sample", {"sample_id": "s001"})

    rule = ProductionRule(
        name="build_raw",
        description="",
        produces=ProducesSpec(
            entity_type="RawReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="s_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="raw.cwl", inputs={}),
    )

    registry = RuleRegistry([rule])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri1 = planner.resolve("RawReads", {"sample_id": "s001"})
    uri2 = planner.resolve("RawReads", {"sample_id": "s001"})

    assert uri1 == uri2
    assert mock_executor.run.call_count == 1


# ---------------------------------------------------------------------------
# Category 7: Failure recovery
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_failure_recovery_prerequisites_persist_in_mosaic(
    hippo_client, hippo_shim, tmp_path
):
    """When the executor fails on the second step, the first entity is still in Mosaic.

    The contract: Mosaic is always left in a consistent, additive state — prior
    successful ingestions are not rolled back when a later step fails.
    """
    from canon.exceptions import CanonExecutorError
    from canon.executors.base import CWLRunResult

    hippo_client.create("Sample", {"sample_id": "s001"})

    # Two-step chain: Sample → RawReads → TrimmedReads
    rule_a = ProductionRule(
        name="rule_a",
        description="",
        produces=ProducesSpec(
            entity_type="RawReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="s_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="a.cwl", inputs={}),
    )
    rule_b = ProductionRule(
        name="rule_b",
        description="",
        produces=ProducesSpec(
            entity_type="TrimmedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="raw_in",
                entity_type="RawReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={}),
    )

    executor = MagicMock()
    # First call (build RawReads) succeeds; second call (build TrimmedReads) fails
    executor.run.side_effect = [
        CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={}),
        CWLRunResult(exit_code=1, stdout="", stderr="CWL subprocess failed", outputs={}),
    ]

    registry = RuleRegistry([rule_a, rule_b])
    planner = _make_planner(hippo_shim, registry, executor, tmp_path)

    with pytest.raises(CanonExecutorError):
        planner.resolve("TrimmedReads", {"sample_id": "s001"})

    # RawReads was successfully built and ingested before the failure
    raw_result = hippo_client.query("RawReads")
    raw_matching = [
        item for item in raw_result.items if item["data"].get("sample_id") == "s001"
    ]
    assert len(raw_matching) == 1, "RawReads should persist after downstream failure"

    # TrimmedReads was never ingested
    trimmed_result = hippo_client.query("TrimmedReads")
    trimmed_matching = [
        item for item in trimmed_result.items if item["data"].get("sample_id") == "s001"
    ]
    assert len(trimmed_matching) == 0, "TrimmedReads should not exist after failure"


# ---------------------------------------------------------------------------
# Category 8: Three-node cycle detection
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_three_node_cycle_detection_raises(hippo_shim, mock_executor, tmp_path):
    """3-node cycle (A→B→C→A) raises CanonCycleError; executor never called."""
    rule_a = ProductionRule(
        name="rule_a",
        description="",
        produces=ProducesSpec(entity_type="EntityA", match={"k": "{k}"}),
        requires=[
            InputBinding(bind="c_in", entity_type="EntityC", match={"k": "{k}"})
        ],
        execute=ExecuteSpec(workflow="a.cwl", inputs={}),
    )
    rule_b = ProductionRule(
        name="rule_b",
        description="",
        produces=ProducesSpec(entity_type="EntityB", match={"k": "{k}"}),
        requires=[
            InputBinding(bind="a_in", entity_type="EntityA", match={"k": "{k}"})
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={}),
    )
    rule_c = ProductionRule(
        name="rule_c",
        description="",
        produces=ProducesSpec(entity_type="EntityC", match={"k": "{k}"}),
        requires=[
            InputBinding(bind="b_in", entity_type="EntityB", match={"k": "{k}"})
        ],
        execute=ExecuteSpec(workflow="c.cwl", inputs={}),
    )

    registry = RuleRegistry([rule_a, rule_b, rule_c])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    with pytest.raises(CanonCycleError):
        planner.resolve("EntityA", {"k": "v1"})

    assert mock_executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Category 9: plan() dry-run uses real Mosaic state
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_plan_dry_run_reflects_real_mosaic_state(
    hippo_client, hippo_shim, mock_executor, tmp_path
):
    """plan() reads real Mosaic state to decide REUSE vs BUILD for each node."""
    from canon.resolver.planner import PlanNode

    # RawReads exists in Mosaic; TrimmedReads does not
    hippo_client.create(
        "RawReads",
        {"sample_id": "s001", "uri": "dhlx://rawreads/s001"},
    )

    rule_b = ProductionRule(
        name="rule_b",
        description="",
        produces=ProducesSpec(
            entity_type="TrimmedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="raw_in",
                entity_type="RawReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={}),
    )

    registry = RuleRegistry([rule_b])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    node = planner.plan("TrimmedReads", {"sample_id": "s001"})

    assert isinstance(node, PlanNode)
    assert node.decision == "BUILD"
    assert node.rule_name == "rule_b"
    assert len(node.children) == 1

    child = node.children[0]
    assert child.decision == "REUSE"
    assert child.entity_type == "RawReads"

    # plan() must never execute
    assert mock_executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Category 10: CanonNoRuleError when no rule matches
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_no_rule_raises_canon_no_rule_error(hippo_shim, mock_executor, tmp_path):
    """Resolving an entity with no matching rule raises CanonNoRuleError."""
    from canon.exceptions import CanonNoRuleError

    registry = RuleRegistry([])  # empty — no rules installed
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    with pytest.raises(CanonNoRuleError) as exc_info:
        planner.resolve("AlignmentFile", {"sample_id": "s001"})

    assert exc_info.value.entity_type == "AlignmentFile"
    assert mock_executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Category 11: Full bioinformatics 4-step chain
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_full_bioinformatics_chain_sample_to_aligned(
    hippo_client, hippo_shim, mock_executor, tmp_path
):
    """Complete 4-step bioinformatics chain: Sample→RawReads→TrimmedReads→AlignedReads.

    - Sample pre-exists in Mosaic (REUSE, no executor call)
    - RawReads, TrimmedReads, AlignedReads are built in bottom-up order (3 executor calls)
    - All 3 produced entities are queryable from Mosaic afterward
    """
    hippo_client.create("Sample", {"sample_id": "s001"})

    rule_raw = ProductionRule(
        name="build_raw_reads",
        description="",
        produces=ProducesSpec(
            entity_type="RawReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="s_in",
                entity_type="Sample",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(workflow="raw.cwl", inputs={"sample_id": "{sample_id}"}),
    )
    rule_trim = ProductionRule(
        name="build_trimmed_reads",
        description="",
        produces=ProducesSpec(
            entity_type="TrimmedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="raw_in",
                entity_type="RawReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="trim.cwl", inputs={"raw_uri": "{raw_in.uri}"}
        ),
    )
    rule_align = ProductionRule(
        name="build_aligned_reads",
        description="",
        produces=ProducesSpec(
            entity_type="AlignedReads", match={"sample_id": "{sample_id}"}
        ),
        requires=[
            InputBinding(
                bind="trimmed_in",
                entity_type="TrimmedReads",
                match={"sample_id": "{sample_id}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="align.cwl", inputs={"trimmed_uri": "{trimmed_in.uri}"}
        ),
    )

    registry = RuleRegistry([rule_raw, rule_trim, rule_align])
    planner = _make_planner(hippo_shim, registry, mock_executor, tmp_path)

    uri = planner.resolve("AlignedReads", {"sample_id": "s001"})

    # 3 executor calls: raw, trim, align (Sample is REUSE)
    assert mock_executor.run.call_count == 3
    cwl_paths = [c[0][0] for c in mock_executor.run.call_args_list]
    assert cwl_paths == ["raw.cwl", "trim.cwl", "align.cwl"]

    # All 3 produced entity types present in real Mosaic
    for etype in ("RawReads", "TrimmedReads", "AlignedReads"):
        result = hippo_client.query(etype)
        hits = [i for i in result.items if i["data"].get("sample_id") == "s001"]
        assert len(hits) == 1, f"{etype} missing from Mosaic after chain"

    assert uri.startswith("dhlx://alignedreads/")


# ---------------------------------------------------------------------------
# Category 12: Fetch rule — materializes entity and sets URI
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_fetch_materializes_entity_and_sets_uri(hippo_client, hippo_shim, tmp_path):
    """FETCH path: HTTP download materializes file, entity uri set in real Mosaic."""
    hippo_client.create(
        "GenomeBuild",
        {
            "name": "GRCh38",
            "release": "110",
            "source_uri": "https://example.com/genome.fa",
        },
    )

    fetch_rule = FetchRule(
        name="fetch-grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38", "release": "110"},
        ),
        source_uri="https://example.com/genome.fa",
    )
    registry = RuleRegistry([fetch_rule])

    local_adapter = LocalStorageAdapter(str(tmp_path / "outputs"))

    mock_https = MagicMock(spec=HTTPStorageAdapter)

    def _fake_get(uri, local_dir):
        path = Path(local_dir) / uri.split("/")[-1]
        path.write_bytes(b"fake genome content")
        return path

    mock_https.get.side_effect = _fake_get

    planner = _make_planner_with_storage(
        hippo_shim, registry, local_adapter, mock_https, tmp_path
    )

    uri = planner.resolve("GenomeBuild", {"name": "GRCh38", "release": "110"})

    assert mock_https.get.call_count == 1
    assert uri.startswith("file://")
    assert Path(uri[len("file://"):]).exists()

    result = hippo_client.query("GenomeBuild")
    hits = [i for i in result.items if i["data"].get("name") == "GRCh38"]
    assert len(hits) == 1
    assert hits[0]["data"].get("uri") == uri


# ---------------------------------------------------------------------------
# Category 13: Fetch rule — skip download when dest already cached
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_fetch_skip_if_dest_cached(hippo_client, hippo_shim, tmp_path):
    """FETCH skips HTTP download when destination file already exists in local storage."""
    create_result = hippo_client.create(
        "GenomeBuild",
        {
            "name": "GRCh38",
            "release": "110",
            "source_uri": "https://example.com/genome.fa",
        },
    )
    entity_id = create_result["id"]

    # Pre-create the file at the exact destination the adapter will resolve to
    base_path = tmp_path / "outputs"
    dest = base_path / "genomebuild" / entity_id / "genome.fa"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"cached content")

    fetch_rule = FetchRule(
        name="fetch-grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38", "release": "110"},
        ),
        source_uri="https://example.com/genome.fa",
    )
    registry = RuleRegistry([fetch_rule])

    local_adapter = LocalStorageAdapter(str(base_path))
    mock_https = MagicMock(spec=HTTPStorageAdapter)

    planner = _make_planner_with_storage(
        hippo_shim, registry, local_adapter, mock_https, tmp_path
    )

    uri = planner.resolve("GenomeBuild", {"name": "GRCh38", "release": "110"})

    assert mock_https.get.call_count == 0
    assert uri == f"file://{dest}"


# ---------------------------------------------------------------------------
# Category 14: Fetch rule — REUSE on second resolve() call
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_reuse_after_fetch(hippo_client, hippo_shim, tmp_path):
    """Second resolve() after FETCH follows REUSE path; HTTP called exactly once."""
    hippo_client.create(
        "GenomeBuild",
        {
            "name": "GRCh38",
            "release": "110",
            "source_uri": "https://example.com/genome.fa",
        },
    )

    fetch_rule = FetchRule(
        name="fetch-grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38", "release": "110"},
        ),
        source_uri="https://example.com/genome.fa",
    )
    registry = RuleRegistry([fetch_rule])

    local_adapter = LocalStorageAdapter(str(tmp_path / "outputs"))

    mock_https = MagicMock(spec=HTTPStorageAdapter)

    def _fake_get(uri, local_dir):
        path = Path(local_dir) / uri.split("/")[-1]
        path.write_bytes(b"fake genome content")
        return path

    mock_https.get.side_effect = _fake_get

    planner = _make_planner_with_storage(
        hippo_shim, registry, local_adapter, mock_https, tmp_path
    )

    uri1 = planner.resolve("GenomeBuild", {"name": "GRCh38", "release": "110"})
    uri2 = planner.resolve("GenomeBuild", {"name": "GRCh38", "release": "110"})

    assert mock_https.get.call_count == 1
    assert uri1 == uri2


# ---------------------------------------------------------------------------
# Category 15: Fetch rule — checksum mismatch raises, entity uri not set
# ---------------------------------------------------------------------------


@pytest.mark.platform
def test_fetch_checksum_mismatch_raises(hippo_client, hippo_shim, tmp_path):
    """Checksum mismatch on download raises CanonStorageError; entity uri stays unset."""
    hippo_client.create(
        "GenomeBuild",
        {
            "name": "GRCh38",
            "release": "110",
            "source_uri": "https://example.com/genome.fa",
        },
    )

    fetch_rule = FetchRule(
        name="fetch-grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38", "release": "110"},
        ),
        source_uri="https://example.com/genome.fa",
        checksum_sha256="0" * 64,  # will never match real file content
    )
    registry = RuleRegistry([fetch_rule])

    local_adapter = LocalStorageAdapter(str(tmp_path / "outputs"))

    mock_https = MagicMock(spec=HTTPStorageAdapter)

    def _fake_get(uri, local_dir):
        path = Path(local_dir) / uri.split("/")[-1]
        path.write_bytes(b"fake genome content")
        return path

    mock_https.get.side_effect = _fake_get

    planner = _make_planner_with_storage(
        hippo_shim, registry, local_adapter, mock_https, tmp_path
    )

    with pytest.raises(CanonStorageError):
        planner.resolve("GenomeBuild", {"name": "GRCh38", "release": "110"})

    # Entity uri must not be set after the failed fetch
    result = hippo_client.query("GenomeBuild")
    hits = [i for i in result.items if i["data"].get("name") == "GRCh38"]
    assert len(hits) == 1
    assert hits[0]["data"].get("uri") is None
