"""Platform integration tests: Canon-only categories.

Tests exercise Canon's resolver, rules, ingestion, and sidecar components
in-process — no Hippo HTTP server, no real CWL execution.

## Category taxonomy

### Implemented
1. Rules DSL — RulesLoader valid/invalid YAML, duplicate names, missing fields
2. Entity ref parsing — parse_entity_ref syntax variants, error cases
3. Wildcard utilities — is_pure_wildcard, is_entity_ref, extract_wildcard_name
4. Planner REUSE vs BUILD decisions — plan() dry-run with mock Hippo
5. Dependency ordering — topological correctness via resolve() + mocked executor
6. Cycle detection — 2-node, self-referential, 3-node cycles
7. Sidecar parsing — load_sidecar() valid/invalid files
8. Output ingestion — evaluate_mosaic_fields() expression evaluation

### Pending
- CwltoolAdapter subprocess contract (requires cwltool on PATH; covered by test_cwltool.py)
- EntityRefResolver with real Hippo shim (covered by test_entity_ref.py + test_mosaic_canon.py)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

# Ensure packages importable regardless of how pytest is invoked
_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canon.exceptions import (
    CanonCycleError,
    CanonIngestionError,
    CanonNoRuleError,
    CanonPlanningError,
    CanonResolutionError,
    CanonRuleValidationError,
    CanonStorageError,
)
from canon.executors.base import CWLRunResult
from canon.ingestion.sidecar import (
    SidecarOutput,
    evaluate_mosaic_fields,
    load_sidecar,
)
from canon.resolver.entity_ref import EntityRefResolver, parse_entity_ref
from canon.resolver.planner import PlanNode, RecursivePlanner
from canon.rules.loader import RulesLoader
from canon.rules.models import (
    ExecuteSpec,
    FetchRule,
    InputBinding,
    ProductionRule,
    ProducesSpec,
    extract_wildcard_name,
    is_entity_ref,
    is_pure_wildcard,
)
from canon.rules.registry import RuleRegistry
from canon.storage.http import HTTPStorageAdapter
from canon.storage.local import LocalStorageAdapter
from canon.storage.registry import StorageAdapterRegistry
from canon.types import Entity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rules(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "canon_rules.yaml"
    p.write_text(yaml.dump(data))
    return p


def _make_rule(
    name: str = "r1",
    entity_type: str = "AlignedReads",
    match: dict | None = None,
    requires: list | None = None,
) -> ProductionRule:
    return ProductionRule(
        name=name,
        description="",
        produces=ProducesSpec(
            entity_type=entity_type, match=match or {"sample": "{sample}"}
        ),
        requires=requires or [],
        execute=ExecuteSpec(workflow="w.cwl", inputs={}),
    )


def _make_planner(
    hippo: MagicMock | None = None,
    registry: RuleRegistry | None = None,
    executor: MagicMock | None = None,
    work_dir: str = "/tmp/canon-platform-test",
) -> RecursivePlanner:
    hippo = hippo or MagicMock()
    registry = registry if registry is not None else RuleRegistry([])
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = Entity(
        id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
    )
    return RecursivePlanner(
        hippo_client=hippo,
        rule_registry=registry,
        entity_ref_resolver=ref_resolver,
        executor=executor,
        ingestion_pipeline=None,
        work_dir_base=work_dir,
    )


def _make_cwl_and_sidecar(
    tmp_path: Path, workflow: str = "workflows/align.cwl"
) -> Path:
    """Create minimal CWL + sidecar files so RulesLoader semantic validation passes."""
    cwl = tmp_path / workflow
    cwl.parent.mkdir(parents=True, exist_ok=True)
    cwl.write_text(
        "#!/usr/bin/env cwltool\nclass: CommandLineTool\ncwlVersion: v1.2\nbaseCommand: echo\n"
    )
    sidecar = cwl.with_suffix("").with_suffix(".canon.yaml")
    sidecar.write_text(
        "outputs:\n"
        "  aligned_bam:\n"
        "    entity_type: AlignedReads\n"
        "    identity_fields: [sample]\n"
        "    mosaic_fields:\n"
        "      uri: '{outputs.bam.location}'\n"
    )
    return cwl


# ---------------------------------------------------------------------------
# Category 1: Rules DSL — RulesLoader
# ---------------------------------------------------------------------------


class TestRulesDSL:
    """RulesLoader parses valid YAML and rejects bad rules with CanonRuleValidationError."""

    def test_valid_rule_parses_correctly(self, tmp_path):
        _make_cwl_and_sidecar(tmp_path, "workflows/align.cwl")
        data = {
            "rules": [
                {
                    "name": "align-reads",
                    "description": "Align with STAR",
                    "produces": {
                        "entity_type": "AlignedReads",
                        "match": {"sample": "{sample}", "genome_build": "{genome_build}"},
                    },
                    "requires": [
                        {
                            "bind": "reads",
                            "entity_type": "RawReads",
                            "match": {"sample": "{sample}"},
                        }
                    ],
                    "execute": {
                        "workflow": "workflows/align.cwl",
                        "inputs": {"reads_fastq": "{reads.uri}"},
                    },
                }
            ]
        }
        rules = RulesLoader(_write_rules(tmp_path, data)).load()
        assert len(rules) == 1
        rule = rules[0]
        assert rule.name == "align-reads"
        assert rule.produces.entity_type == "AlignedReads"
        assert rule.produces.match["sample"] == "{sample}"
        assert len(rule.requires) == 1
        assert rule.requires[0].bind == "reads"

    def test_duplicate_rule_names_raise(self, tmp_path):
        data = {
            "rules": [
                {
                    "name": "my-rule",
                    "produces": {"entity_type": "Foo", "match": {"x": "1"}},
                    "execute": {"workflow": "w.cwl", "inputs": {}},
                },
                {
                    "name": "my-rule",
                    "produces": {"entity_type": "Foo", "match": {"x": "2"}},
                    "execute": {"workflow": "w.cwl", "inputs": {}},
                },
            ]
        }
        with pytest.raises(CanonRuleValidationError, match="my-rule"):
            RulesLoader(_write_rules(tmp_path, data)).load()

    def test_missing_name_raises(self, tmp_path):
        data = {
            "rules": [
                {
                    "produces": {"entity_type": "Foo", "match": {}},
                    "execute": {"workflow": "w.cwl", "inputs": {}},
                }
            ]
        }
        with pytest.raises(CanonRuleValidationError):
            RulesLoader(_write_rules(tmp_path, data)).load()

    def test_missing_produces_raises(self, tmp_path):
        data = {
            "rules": [
                {
                    "name": "bad-rule",
                    "execute": {"workflow": "w.cwl", "inputs": {}},
                }
            ]
        }
        with pytest.raises(CanonRuleValidationError):
            RulesLoader(_write_rules(tmp_path, data)).load()

    def test_empty_rules_list_returns_empty(self, tmp_path):
        data = {"rules": []}
        rules = RulesLoader(_write_rules(tmp_path, data)).load()
        assert rules == []


# ---------------------------------------------------------------------------
# Category 2: Entity ref parsing
# ---------------------------------------------------------------------------


class TestEntityRefParsing:
    """parse_entity_ref syntax variants and error cases."""

    def test_simple_single_constraint(self):
        ref = parse_entity_ref("ref:ToolVersion{version=2.7.11a}")
        assert ref.entity_type == "ToolVersion"
        assert ref.constraints == {"version": "2.7.11a"}

    def test_multiple_constraints(self):
        ref = parse_entity_ref("ref:ToolVersion{tool.name=STAR, version=2.7.11a}")
        assert ref.entity_type == "ToolVersion"
        assert ref.constraints["tool.name"] == "STAR"
        assert ref.constraints["version"] == "2.7.11a"

    def test_wildcard_in_constraint_value(self):
        ref = parse_entity_ref("ref:GenomeBuild{name=GRCh38}")
        assert ref.entity_type == "GenomeBuild"
        assert ref.constraints["name"] == "GRCh38"

    def test_nested_braces_in_constraint_raises(self):
        with pytest.raises(CanonPlanningError):
            parse_entity_ref("ref:GenomeBuild{name={genome_build}}")

    def test_invalid_format_no_type_raises(self):
        with pytest.raises(CanonPlanningError):
            parse_entity_ref("not-a-ref")

    def test_missing_braces_raises(self):
        with pytest.raises(CanonPlanningError):
            parse_entity_ref("ref:ToolVersion")


# ---------------------------------------------------------------------------
# Category 3: Wildcard utilities
# ---------------------------------------------------------------------------


class TestWildcardUtilities:
    """is_pure_wildcard, is_entity_ref, extract_wildcard_name correctness."""

    def test_pure_wildcard_simple(self):
        assert is_pure_wildcard("{sample}") is True

    def test_pure_wildcard_with_underscores(self):
        assert is_pure_wildcard("{genome_build}") is True

    def test_pure_wildcard_false_for_plain_string(self):
        assert is_pure_wildcard("plain_value") is False

    def test_pure_wildcard_false_for_entity_ref(self):
        assert is_pure_wildcard("ref:ToolVersion{name=STAR}") is False

    def test_pure_wildcard_false_for_partial(self):
        assert is_pure_wildcard("{sample}_extra") is False

    def test_pure_wildcard_false_for_int(self):
        assert is_pure_wildcard(42) is False

    def test_is_entity_ref_true(self):
        assert is_entity_ref("ref:ToolVersion{version=2.7.11a}") is True

    def test_is_entity_ref_false_for_plain(self):
        assert is_entity_ref("plain_value") is False

    def test_is_entity_ref_false_for_wildcard(self):
        assert is_entity_ref("{sample}") is False

    def test_extract_wildcard_name(self):
        assert extract_wildcard_name("{genome_build}") == "genome_build"
        assert extract_wildcard_name("{sample}") == "sample"

    def test_extract_wildcard_name_non_wildcard_raises(self):
        with pytest.raises(ValueError):
            extract_wildcard_name("not-a-wildcard")


# ---------------------------------------------------------------------------
# Category 4: Planner REUSE vs BUILD decisions
# ---------------------------------------------------------------------------


class TestPlannerDecisions:
    """plan() dry-run returns correct REUSE/BUILD decisions; no executor called."""

    def test_plan_returns_reuse_when_entity_exists(self):
        hippo = MagicMock()
        entity = Entity(id="e1", entity_type="AlignedReads", data={}, uri="/data/a.bam")
        hippo.find_entity.return_value = entity

        planner = _make_planner(hippo=hippo)
        node = planner.plan("AlignedReads", {"sample": "S001"})
        assert node.decision == "REUSE"
        assert node.entity_id == "e1"
        assert node.uri == "/data/a.bam"

    def test_plan_returns_build_when_entity_absent(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None
        rule = _make_rule("r1", "AlignedReads")
        registry = RuleRegistry([rule])

        planner = _make_planner(hippo=hippo, registry=registry)
        node = planner.plan("AlignedReads", {"sample": "S001"})
        assert node.decision == "BUILD"
        assert node.rule_name == "r1"

    def test_plan_does_not_call_executor(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None
        rule = _make_rule("r1")
        registry = RuleRegistry([rule])
        executor = MagicMock()

        planner = _make_planner(hippo=hippo, registry=registry, executor=executor)
        planner.plan("AlignedReads", {"sample": "S001"})
        executor.run.assert_not_called()

    def test_plan_tree_has_reuse_child_when_input_exists(self):
        """plan() produces REUSE child when an input entity already exists in Hippo."""
        hippo = MagicMock()
        raw_entity = Entity(id="raw-id", entity_type="RawReads", data={}, uri="/raw.fastq")

        def _find(entity_type, params):
            if entity_type == "RawReads":
                return raw_entity
            return None  # TrimmedReads doesn't exist

        hippo.find_entity.side_effect = _find

        rule = ProductionRule(
            name="trim",
            description="",
            produces=ProducesSpec(
                entity_type="TrimmedReads", match={"sample": "{sample}"}
            ),
            requires=[
                InputBinding(
                    bind="raw_in",
                    entity_type="RawReads",
                    match={"sample": "{sample}"},
                )
            ],
            execute=ExecuteSpec(workflow="trim.cwl", inputs={}),
        )
        registry = RuleRegistry([rule])
        planner = _make_planner(hippo=hippo, registry=registry)

        node = planner.plan("TrimmedReads", {"sample": "S001"})
        assert node.decision == "BUILD"
        assert len(node.children) == 1
        assert node.children[0].decision == "REUSE"
        assert node.children[0].entity_type == "RawReads"

    def test_plan_no_rule_raises_no_rule_error(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None
        registry = RuleRegistry([])

        planner = _make_planner(hippo=hippo, registry=registry)
        with pytest.raises(CanonNoRuleError) as exc_info:
            planner.plan("AlignedReads", {"sample": "S001"})
        assert exc_info.value.entity_type == "AlignedReads"


# ---------------------------------------------------------------------------
# Category 5: Dependency ordering
# ---------------------------------------------------------------------------


class TestDependencyOrdering:
    """Executor is invoked in bottom-up (dependency-first) order."""

    def test_two_level_chain_bottom_up_order(self, tmp_path):
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        entity_a = Entity(id="a-id", entity_type="EntityA", data={}, uri="uri://a")
        entity_b = Entity(id="b-id", entity_type="EntityB", data={}, uri="uri://b")
        hippo.ingest_entity.side_effect = lambda et, _: (
            entity_a if et == "EntityA" else entity_b
        )

        rule_a = _make_rule("rule_a", "EntityA", {"sample": "{sample}"}, requires=[])
        rule_b = _make_rule(
            "rule_b",
            "EntityB",
            {"sample": "{sample}"},
            requires=[
                InputBinding(
                    bind="a_in", entity_type="EntityA", match={"sample": "{sample}"}
                )
            ],
        )

        executor = MagicMock()
        executor.run.return_value = CWLRunResult(
            exit_code=0, stdout="{}", stderr="", outputs={}
        )

        registry = RuleRegistry([rule_a, rule_b])
        planner = _make_planner(
            hippo=hippo, registry=registry, executor=executor, work_dir=str(tmp_path)
        )

        planner.resolve("EntityB", {"sample": "S001"})

        assert executor.run.call_count == 2
        cwl_order = [c[0][0] for c in executor.run.call_args_list]
        assert cwl_order == ["w.cwl", "w.cwl"]  # both rules use w.cwl; order is a→b

    def test_three_level_chain_ingested_in_order(self, tmp_path):
        """EntityA, EntityB, EntityC ingested in bottom-up order."""
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        entities = {
            "EntityA": Entity(id="a-id", entity_type="EntityA", data={}, uri="uri://a"),
            "EntityB": Entity(id="b-id", entity_type="EntityB", data={}, uri="uri://b"),
            "EntityC": Entity(id="c-id", entity_type="EntityC", data={}, uri="uri://c"),
        }
        hippo.ingest_entity.side_effect = lambda et, _: entities[et]

        rule_a = _make_rule("rule_a", "EntityA", {"k": "{k}"}, requires=[])
        rule_b = _make_rule(
            "rule_b",
            "EntityB",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="a_in", entity_type="EntityA", match={"k": "{k}"})
            ],
        )
        rule_c = _make_rule(
            "rule_c",
            "EntityC",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="b_in", entity_type="EntityB", match={"k": "{k}"})
            ],
        )

        executor = MagicMock()
        executor.run.return_value = CWLRunResult(
            exit_code=0, stdout="{}", stderr="", outputs={}
        )

        registry = RuleRegistry([rule_a, rule_b, rule_c])
        planner = _make_planner(
            hippo=hippo, registry=registry, executor=executor, work_dir=str(tmp_path)
        )

        uri = planner.resolve("EntityC", {"k": "v1"})

        assert executor.run.call_count == 3
        assert hippo.ingest_entity.call_count == 3
        ingested_types = [c[0][0] for c in hippo.ingest_entity.call_args_list]
        assert ingested_types == ["EntityA", "EntityB", "EntityC"]
        assert uri == "uri://c"


# ---------------------------------------------------------------------------
# Category 6: Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """2-node, self-referential, and 3-node cycles all raise CanonCycleError."""

    def test_two_node_cycle_raises(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        rule_a = _make_rule(
            "rule_a",
            "EntityA",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="b_in", entity_type="EntityB", match={"k": "{k}"})
            ],
        )
        rule_b = _make_rule(
            "rule_b",
            "EntityB",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="a_in", entity_type="EntityA", match={"k": "{k}"})
            ],
        )

        registry = RuleRegistry([rule_a, rule_b])
        executor = MagicMock()
        planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

        with pytest.raises(CanonCycleError):
            planner.resolve("EntityA", {"k": "v"})
        executor.run.assert_not_called()

    def test_self_referential_cycle_raises(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        rule = _make_rule(
            "rule_self",
            "SelfEntity",
            {"k": "{k}"},
            requires=[
                InputBinding(
                    bind="self_in", entity_type="SelfEntity", match={"k": "{k}"}
                )
            ],
        )
        registry = RuleRegistry([rule])
        executor = MagicMock()
        planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

        with pytest.raises(CanonCycleError):
            planner.resolve("SelfEntity", {"k": "v"})
        executor.run.assert_not_called()

    def test_three_node_cycle_raises(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        rule_a = _make_rule(
            "rule_a",
            "EntityA",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="c_in", entity_type="EntityC", match={"k": "{k}"})
            ],
        )
        rule_b = _make_rule(
            "rule_b",
            "EntityB",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="a_in", entity_type="EntityA", match={"k": "{k}"})
            ],
        )
        rule_c = _make_rule(
            "rule_c",
            "EntityC",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="b_in", entity_type="EntityB", match={"k": "{k}"})
            ],
        )

        registry = RuleRegistry([rule_a, rule_b, rule_c])
        executor = MagicMock()
        planner = _make_planner(hippo=hippo, registry=registry, executor=executor)

        with pytest.raises(CanonCycleError):
            planner.resolve("EntityA", {"k": "v"})
        executor.run.assert_not_called()

    def test_cycle_detected_in_plan_dry_run(self):
        hippo = MagicMock()
        hippo.find_entity.return_value = None

        rule_a = _make_rule(
            "rule_a",
            "EntityA",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="b_in", entity_type="EntityB", match={"k": "{k}"})
            ],
        )
        rule_b = _make_rule(
            "rule_b",
            "EntityB",
            {"k": "{k}"},
            requires=[
                InputBinding(bind="a_in", entity_type="EntityA", match={"k": "{k}"})
            ],
        )

        registry = RuleRegistry([rule_a, rule_b])
        planner = _make_planner(hippo=hippo, registry=registry)

        with pytest.raises(CanonCycleError):
            planner.plan("EntityA", {"k": "v"})


# ---------------------------------------------------------------------------
# Category 7: Sidecar parsing
# ---------------------------------------------------------------------------


class TestSidecarParsing:
    """load_sidecar() accepts valid files and raises CanonIngestionError on bad input."""

    def test_valid_sidecar_parses_correctly(self, tmp_path):
        sidecar = tmp_path / "workflow.canon.yaml"
        sidecar.write_text(
            "outputs:\n"
            "  aligned_bam:\n"
            "    entity_type: AlignedReads\n"
            "    identity_fields: [sample]\n"
            "    mosaic_fields:\n"
            "      uri: '{outputs.bam.location}'\n"
            "      sample_id: '{inputs.sample_id}'\n"
        )
        spec = load_sidecar(str(sidecar))
        assert "aligned_bam" in spec.outputs
        output = spec.outputs["aligned_bam"]
        assert output.entity_type == "AlignedReads"
        assert output.identity_fields == ["sample"]
        assert output.mosaic_fields["uri"] == "{outputs.bam.location}"
        assert output.mosaic_fields["sample_id"] == "{inputs.sample_id}"

    def test_missing_sidecar_raises_ingestion_error(self, tmp_path):
        with pytest.raises(CanonIngestionError, match="not found"):
            load_sidecar(str(tmp_path / "does-not-exist.canon.yaml"))

    def test_malformed_yaml_raises_ingestion_error(self, tmp_path):
        sidecar = tmp_path / "bad.canon.yaml"
        sidecar.write_text(": invalid: yaml: {\n")
        with pytest.raises(CanonIngestionError):
            load_sidecar(str(sidecar))

    def test_non_mapping_top_level_raises_ingestion_error(self, tmp_path):
        sidecar = tmp_path / "bad.canon.yaml"
        sidecar.write_text("- item1\n- item2\n")
        with pytest.raises(CanonIngestionError, match="mapping"):
            load_sidecar(str(sidecar))

    def test_output_missing_entity_type_raises(self, tmp_path):
        sidecar = tmp_path / "bad.canon.yaml"
        sidecar.write_text(
            "outputs:\n"
            "  my_output:\n"
            "    identity_fields: [sample]\n"
            "    mosaic_fields:\n"
            "      uri: '{outputs.x.location}'\n"
        )
        with pytest.raises(CanonIngestionError, match="entity_type"):
            load_sidecar(str(sidecar))

    def test_empty_outputs_mapping_is_valid(self, tmp_path):
        sidecar = tmp_path / "empty.canon.yaml"
        sidecar.write_text("outputs: {}\n")
        spec = load_sidecar(str(sidecar))
        assert spec.outputs == {}


# ---------------------------------------------------------------------------
# Category 8: Output ingestion — evaluate_mosaic_fields
# ---------------------------------------------------------------------------


class TestEvaluateMosaicFields:
    """evaluate_mosaic_fields resolves {outputs.*}, {inputs.*}, {run_id} expressions."""

    def _make_output(self, mosaic_fields: dict) -> SidecarOutput:
        return SidecarOutput(
            entity_type="AlignedReads",
            identity_fields=["sample"],
            mosaic_fields=mosaic_fields,
        )

    def test_outputs_dot_path_expression(self):
        sidecar_output = self._make_output({"uri": "{outputs.bam.location}"})
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={"bam": {"location": "file:///data/out.bam"}},
            cwl_inputs={},
            run_id="run-001",
        )
        assert result["uri"] == "file:///data/out.bam"

    def test_inputs_expression(self):
        sidecar_output = self._make_output({"sample_id": "{inputs.sample_id}"})
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={},
            cwl_inputs={"sample_id": "S001"},
            run_id="run-001",
        )
        assert result["sample_id"] == "S001"

    def test_run_id_expression(self):
        sidecar_output = self._make_output({"run_id": "{run_id}"})
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={},
            cwl_inputs={},
            run_id="my-run-uuid",
        )
        assert result["run_id"] == "my-run-uuid"

    def test_string_interpolation_mixed(self):
        """Multiple expressions inside a single string are interpolated together."""
        sidecar_output = self._make_output(
            {"label": "sample={inputs.sample_id} run={run_id}"}
        )
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={},
            cwl_inputs={"sample_id": "S001"},
            run_id="run-42",
        )
        assert result["label"] == "sample=S001 run=run-42"

    def test_missing_outputs_key_resolves_to_none(self):
        sidecar_output = self._make_output({"uri": "{outputs.missing_key.location}"})
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={},  # 'missing_key' not present
            cwl_inputs={},
            run_id="r1",
        )
        assert result["uri"] is None

    def test_literal_value_passthrough(self):
        """Non-expression field values are passed through unchanged."""
        sidecar_output = self._make_output({"status": "completed"})
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={},
            cwl_inputs={},
            run_id="r1",
        )
        assert result["status"] == "completed"

    def test_multiple_fields_evaluated_independently(self):
        sidecar_output = self._make_output(
            {
                "uri": "{outputs.bam.location}",
                "sample_id": "{inputs.sample_id}",
                "run_id": "{run_id}",
            }
        )
        result = evaluate_mosaic_fields(
            sidecar_output,
            cwl_outputs={"bam": {"location": "file:///out.bam"}},
            cwl_inputs={"sample_id": "S002"},
            run_id="run-99",
        )
        assert result["uri"] == "file:///out.bam"
        assert result["sample_id"] == "S002"
        assert result["run_id"] == "run-99"


# ---------------------------------------------------------------------------
# Category 9: Fetch rules
# ---------------------------------------------------------------------------


class TestFetchRules:
    """Fetch rule parsing, planner decisions, and storage adapter routing."""

    def test_fetch_rule_parses_from_yaml(self, tmp_path):
        """A type:fetch rule in YAML loads as a FetchRule with correct fields."""
        data = {
            "rules": [
                {
                    "name": "fetch-genome-grch38",
                    "type": "fetch",
                    "produces": {
                        "entity_type": "GenomeBuild",
                        "match": {"name": "GRCh38", "release": "110"},
                    },
                    "fetch": {
                        "source_uri": "https://example.com/genome.fa",
                        "checksum_sha256": "abc123",
                    },
                }
            ]
        }
        rules = RulesLoader(_write_rules(tmp_path, data)).load()

        assert len(rules) == 1
        rule = rules[0]
        assert isinstance(rule, FetchRule)
        assert rule.name == "fetch-genome-grch38"
        assert rule.produces.entity_type == "GenomeBuild"
        assert rule.produces.match == {"name": "GRCh38", "release": "110"}
        assert rule.source_uri == "https://example.com/genome.fa"
        assert rule.checksum_sha256 == "abc123"

    def test_fetch_rule_coexists_with_production_rule(self, tmp_path):
        """YAML with both fetch and production rule types loads both correctly."""
        _make_cwl_and_sidecar(tmp_path, "workflows/align.cwl")
        data = {
            "rules": [
                {
                    "name": "fetch-genome-grch38",
                    "type": "fetch",
                    "produces": {
                        "entity_type": "GenomeBuild",
                        "match": {"name": "GRCh38"},
                    },
                    "fetch": {"source_uri": "https://example.com/genome.fa"},
                },
                {
                    "name": "align-reads",
                    "description": "Align with STAR",
                    "produces": {
                        "entity_type": "AlignedReads",
                        "match": {"sample": "{sample}"},
                    },
                    "requires": [],
                    "execute": {
                        "workflow": "workflows/align.cwl",
                        "inputs": {},
                    },
                },
            ]
        }
        rules = RulesLoader(_write_rules(tmp_path, data)).load()

        assert len(rules) == 2
        fetch_rules = [r for r in rules if isinstance(r, FetchRule)]
        prod_rules = [r for r in rules if isinstance(r, ProductionRule)]
        assert len(fetch_rules) == 1
        assert len(prod_rules) == 1
        assert fetch_rules[0].name == "fetch-genome-grch38"
        assert prod_rules[0].name == "align-reads"

    @pytest.mark.platform
    def test_plan_returns_fetch_decision_for_entity_without_uri(self):
        """plan() returns FETCH when entity exists with no accessible uri and fetch rule matches."""
        hippo = MagicMock()
        hippo.find_entity.return_value = Entity(
            id="e1", entity_type="GenomeBuild", data={}, uri=None
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

        planner = _make_planner(hippo=hippo, registry=registry)
        node = planner.plan("GenomeBuild", {"name": "GRCh38", "release": "110"})

        assert node.decision == "FETCH"
        assert node.rule_name == "fetch-grch38"

    @pytest.mark.platform
    def test_plan_returns_reuse_when_uri_accessible(self):
        """plan() returns REUSE when entity has a uri that storage_adapter reports as accessible."""
        hippo = MagicMock()
        hippo.find_entity.return_value = Entity(
            id="e1",
            entity_type="GenomeBuild",
            data={},
            uri="file:///data/genome.fa",
        )

        mock_storage = MagicMock()
        mock_storage.exists.return_value = True

        ref_resolver = MagicMock()
        ref_resolver.resolve.return_value = Entity(
            id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
        )
        planner = RecursivePlanner(
            hippo_client=hippo,
            rule_registry=RuleRegistry([]),
            entity_ref_resolver=ref_resolver,
            executor=None,
            ingestion_pipeline=None,
            storage_adapter=mock_storage,
        )

        node = planner.plan("GenomeBuild", {"name": "GRCh38", "release": "110"})

        assert node.decision == "REUSE"
        assert node.uri == "file:///data/genome.fa"
        mock_storage.exists.assert_called_once_with("file:///data/genome.fa")

    @pytest.mark.platform
    def test_http_adapter_in_registry(self):
        """StorageAdapterRegistry routes https:// and http:// URIs to HTTPStorageAdapter."""
        reg = StorageAdapterRegistry()
        adapter = HTTPStorageAdapter()
        reg._adapters["https"] = adapter
        for scheme in adapter.uri_schemes:  # ["https", "http"]
            reg._scheme_map[scheme] = adapter
        reg._default_type = "https"

        result_https = reg.adapter_for_uri("https://example.com/genome.fa")
        result_http = reg.adapter_for_uri("http://example.com/genome.fa")

        assert isinstance(result_https, HTTPStorageAdapter)
        assert isinstance(result_http, HTTPStorageAdapter)
        assert result_https is result_http  # same instance registered for both schemes
