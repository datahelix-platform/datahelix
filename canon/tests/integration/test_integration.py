"""Integration tests for the Canon resolve pipeline (all-mock, no real Hippo or CWL subprocess)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from canon.resolver.planner import RecursivePlanner
from canon.rules.models import (
    ExecuteSpec,
    InputBinding,
    ProductionRule,
    ProducesSpec,
)
from canon.rules.registry import RuleRegistry
from canon.executors.base import CWLRunResult
from canon.exceptions import CanonCycleError
from canon.types import Entity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(entity_type: str, eid: str, uri: str) -> Entity:
    return Entity(id=eid, entity_type=entity_type, data={"uri": uri}, uri=uri)


def _make_planner(
    hippo: MagicMock,
    registry: RuleRegistry,
    executor: MagicMock | None = None,
    work_dir: str = "/tmp/canon-integration-test",
) -> RecursivePlanner:
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = _make_entity("Unknown", "ref-uuid", "dhlx://ref/unknown")
    return RecursivePlanner(
        hippo_client=hippo,
        rule_registry=registry,
        entity_ref_resolver=ref_resolver,
        executor=executor,
        ingestion_pipeline=None,
        work_dir_base=work_dir,
    )


# ---------------------------------------------------------------------------
# Scenario 1: REUSE path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_reuse_path_returns_existing_uri_no_executor_called():
    """When Hippo returns a pre-existing entity, executor must not be called."""
    hippo = MagicMock()
    existing_entity = _make_entity(
        "AlignmentFile", "align-uuid-001", "dhlx://alignments/sample-001"
    )
    hippo.find_entity.return_value = existing_entity

    executor = MagicMock()
    registry = RuleRegistry([])
    planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

    uri = planner.resolve("AlignmentFile", {"sample": "sample-001"})

    assert uri == "dhlx://alignments/sample-001"
    assert executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Scenario 2: BUILD path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_path_invokes_executor_and_ingests_entity(tmp_path):
    """When Hippo has no entity, executor runs once and output is ingested."""
    # Write canon_rules.yaml for documentation (registry constructed directly below)
    rules_yaml = tmp_path / "canon_rules.yaml"
    rules_yaml.write_text(
        "rules:\n"
        "  - name: trim_reads\n"
        "    description: Trim raw reads with Trim Galore\n"
        "    produces:\n"
        "      entity_type: TrimmedReads\n"
        "      match:\n"
        "        sample: '{sample}'\n"
        "    requires:\n"
        "      - bind: raw\n"
        "        entity_type: RawReads\n"
        "        match:\n"
        "          sample: '{sample}'\n"
        "    execute:\n"
        "      workflow: workflows/trim_reads.cwl\n"
        "      inputs:\n"
        "        fastq_input: '{raw.uri}'\n"
        "        sample_id: '{sample}'\n"
    )

    trim_reads_rule = ProductionRule(
        name="trim_reads",
        description="Trim raw reads with Trim Galore",
        produces=ProducesSpec(
            entity_type="TrimmedReads",
            match={"sample": "{sample}"},
        ),
        requires=[
            InputBinding(
                bind="raw",
                entity_type="RawReads",
                match={"sample": "{sample}"},
            )
        ],
        execute=ExecuteSpec(
            workflow="workflows/trim_reads.cwl",
            inputs={
                "fastq_input": "{raw.uri}",
                "sample_id": "{sample}",
            },
        ),
    )

    raw_reads_entity = _make_entity("RawReads", "raw-uuid-001", "dhlx://raw/sample-001")
    trimmed_entity = _make_entity(
        "TrimmedReads", "trim-uuid-001", "dhlx://trimmed/sample-001"
    )

    hippo = MagicMock()

    def _find_entity(entity_type, params):
        if entity_type == "RawReads":
            return raw_reads_entity
        return None  # TrimmedReads does not exist yet

    hippo.find_entity.side_effect = _find_entity
    hippo.ingest_entity.return_value = trimmed_entity

    executor = MagicMock()
    executor.run.return_value = CWLRunResult(
        exit_code=0,
        stdout="{}",
        stderr="",
        outputs={"trimmed_fastq": {"location": "file:///tmp/trimmed.fastq.gz"}},
    )

    registry = RuleRegistry([trim_reads_rule])
    planner = _make_planner(
        hippo=hippo, registry=registry, executor=executor, work_dir=str(tmp_path)
    )

    uri = planner.resolve("TrimmedReads", {"sample": "sample-001"})

    # Executor called exactly once
    assert executor.run.call_count == 1
    run_call = executor.run.call_args
    assert run_call[0][0] == "workflows/trim_reads.cwl"

    # CWL inputs contain resolved values
    cwl_inputs = run_call[0][1]
    assert cwl_inputs["fastq_input"] == "dhlx://raw/sample-001"
    assert cwl_inputs["sample_id"] == "sample-001"

    # ingest_entity called once for TrimmedReads
    assert hippo.ingest_entity.call_count == 1
    assert hippo.ingest_entity.call_args[0][0] == "TrimmedReads"

    assert uri == "dhlx://trimmed/sample-001"


# ---------------------------------------------------------------------------
# Scenario 3: 2-node cycle detection
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_cycle_detection_two_node_raises_canon_cycle_error():
    """rule_a requires rule_b which requires rule_a — CanonCycleError raised."""
    rule_a = ProductionRule(
        name="rule_a",
        description="",
        produces=ProducesSpec(entity_type="EntityA", match={"sample": "{sample}"}),
        requires=[
            InputBinding(bind="b_input", entity_type="EntityB", match={"sample": "{sample}"})
        ],
        execute=ExecuteSpec(workflow="a.cwl", inputs={}),
    )
    rule_b = ProductionRule(
        name="rule_b",
        description="",
        produces=ProducesSpec(entity_type="EntityB", match={"sample": "{sample}"}),
        requires=[
            InputBinding(bind="a_input", entity_type="EntityA", match={"sample": "{sample}"})
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={}),
    )

    hippo = MagicMock()
    hippo.find_entity.return_value = None

    executor = MagicMock()
    registry = RuleRegistry([rule_a, rule_b])
    planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

    with pytest.raises(CanonCycleError) as exc_info:
        planner.resolve("EntityA", {"sample": "s001"})

    assert "EntityA" in str(exc_info.value) or "Circular" in str(exc_info.value)
    assert executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Scenario 4: Self-referential cycle (1-node)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_cycle_detection_self_referential_raises_canon_cycle_error():
    """rule_a requires its own output — CanonCycleError raised."""
    rule_a = ProductionRule(
        name="rule_a_self",
        description="",
        produces=ProducesSpec(entity_type="SelfEntity", match={"sample": "{sample}"}),
        requires=[
            InputBinding(
                bind="self_input",
                entity_type="SelfEntity",
                match={"sample": "{sample}"},
            )
        ],
        execute=ExecuteSpec(workflow="self.cwl", inputs={}),
    )

    hippo = MagicMock()
    hippo.find_entity.return_value = None

    executor = MagicMock()
    registry = RuleRegistry([rule_a])
    planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

    with pytest.raises(CanonCycleError):
        planner.resolve("SelfEntity", {"sample": "s001"})

    assert executor.run.call_count == 0


# ---------------------------------------------------------------------------
# Scenario 5: 3-level dependency chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_three_level_dependency_chain_executes_in_order(tmp_path):
    """rule_c→rule_b→rule_a: executor invoked 3× bottom-up, all entities ingested."""
    rule_a = ProductionRule(
        name="rule_a",
        description="Produces EntityA from nothing",
        produces=ProducesSpec(entity_type="EntityA", match={"sample": "{sample}"}),
        requires=[],
        execute=ExecuteSpec(workflow="a.cwl", inputs={"sample_id": "{sample}"}),
    )
    rule_b = ProductionRule(
        name="rule_b",
        description="Produces EntityB from EntityA",
        produces=ProducesSpec(entity_type="EntityB", match={"sample": "{sample}"}),
        requires=[
            InputBinding(bind="a_in", entity_type="EntityA", match={"sample": "{sample}"})
        ],
        execute=ExecuteSpec(workflow="b.cwl", inputs={"entity_a_uri": "{a_in.uri}"}),
    )
    rule_c = ProductionRule(
        name="rule_c",
        description="Produces EntityC from EntityB",
        produces=ProducesSpec(entity_type="EntityC", match={"sample": "{sample}"}),
        requires=[
            InputBinding(bind="b_in", entity_type="EntityB", match={"sample": "{sample}"})
        ],
        execute=ExecuteSpec(workflow="c.cwl", inputs={"entity_b_uri": "{b_in.uri}"}),
    )

    entity_a = _make_entity("EntityA", "a-uuid", "dhlx://entity-a/s001")
    entity_b = _make_entity("EntityB", "b-uuid", "dhlx://entity-b/s001")
    entity_c = _make_entity("EntityC", "c-uuid", "dhlx://entity-c/s001")

    hippo = MagicMock()
    hippo.find_entity.return_value = None  # nothing pre-existing

    _ingest_map = {"EntityA": entity_a, "EntityB": entity_b, "EntityC": entity_c}
    hippo.ingest_entity.side_effect = lambda et, params: _ingest_map[et]

    executor = MagicMock()
    executor.run.return_value = CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={})

    registry = RuleRegistry([rule_a, rule_b, rule_c])
    planner = _make_planner(
        hippo=hippo, registry=registry, executor=executor, work_dir=str(tmp_path)
    )

    uri = planner.resolve("EntityC", {"sample": "s001"})

    # Executor called exactly 3 times
    assert executor.run.call_count == 3

    # Bottom-up order: rule_a, rule_b, rule_c
    cwl_paths = [c[0][0] for c in executor.run.call_args_list]
    assert cwl_paths == ["a.cwl", "b.cwl", "c.cwl"]

    # All 3 entity types ingested in bottom-up order
    assert hippo.ingest_entity.call_count == 3
    ingested_types = [c[0][0] for c in hippo.ingest_entity.call_args_list]
    assert ingested_types == ["EntityA", "EntityB", "EntityC"]

    assert uri == "dhlx://entity-c/s001"
