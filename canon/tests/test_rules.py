"""Tests for RulesLoader and RuleRegistry."""

from __future__ import annotations

import yaml
import pytest
from pathlib import Path

from canon.rules.loader import RulesLoader
from canon.rules.registry import RuleRegistry
from canon.rules.models import (
    AggregateRule,
    CollectSpec,
    ProductionRule,
    ProducesSpec,
    InputBinding,
    ExecuteSpec,
    is_glob_wildcard,
    is_pure_wildcard,
    is_entity_ref,
)
from canon.exceptions import CanonRuleValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_rules(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "canon_rules.yaml"
    p.write_text(yaml.dump(data))
    return p


def _make_cwl_and_sidecar(tmp_path: Path, workflow: str = "workflows/star_align.cwl") -> Path:
    """Create a stub CWL file and its sidecar so semantic validation passes."""
    cwl = tmp_path / workflow
    cwl.parent.mkdir(parents=True, exist_ok=True)
    cwl.write_text(
        "#!/usr/bin/env cwltool\nclass: CommandLineTool\ncwlVersion: v1.2\nbaseCommand: echo\n"
    )
    sidecar = cwl.with_name(cwl.stem + ".canon.yaml")
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
# RulesLoader
# ---------------------------------------------------------------------------

def test_valid_rules_parse(tmp_path):
    _make_cwl_and_sidecar(tmp_path, "workflows/star_align.cwl")
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
                    {"bind": "reads", "entity_type": "RawReads", "match": {"sample": "{sample}"}}
                ],
                "execute": {
                    "workflow": "workflows/star_align.cwl",
                    "inputs": {"reads_fastq": "{reads.uri}", "genome_build": "{genome_build}"},
                },
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    loader = RulesLoader(p)
    rules = loader.load()
    assert len(rules) == 1
    assert rules[0].name == "align-reads"
    assert rules[0].produces.entity_type == "AlignedReads"
    assert rules[0].produces.match["sample"] == "{sample}"
    assert len(rules[0].requires) == 1
    assert rules[0].requires[0].bind == "reads"


def test_duplicate_rule_names_raise(tmp_path):
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
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError, match="my-rule"):
        RulesLoader(p).load()


def test_missing_name_raises(tmp_path):
    data = {
        "rules": [
            {
                "produces": {"entity_type": "Foo", "match": {}},
                "execute": {"workflow": "w.cwl", "inputs": {}},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError):
        RulesLoader(p).load()


def test_missing_produces_raises(tmp_path):
    data = {
        "rules": [
            {
                "name": "bad-rule",
                "execute": {"workflow": "w.cwl", "inputs": {}},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError):
        RulesLoader(p).load()


# ---------------------------------------------------------------------------
# is_pure_wildcard
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# is_glob_wildcard
# ---------------------------------------------------------------------------

def test_is_glob_wildcard_true():
    assert is_glob_wildcard("*") is True


def test_is_glob_wildcard_false():
    assert is_glob_wildcard("{sample}") is False
    assert is_glob_wildcard("**") is False
    assert is_glob_wildcard("star") is False
    assert is_glob_wildcard("") is False
    assert is_glob_wildcard(42) is False
    assert is_glob_wildcard(None) is False


# ---------------------------------------------------------------------------
# is_pure_wildcard
# ---------------------------------------------------------------------------

def test_is_pure_wildcard_true():
    assert is_pure_wildcard("{sample}") is True
    assert is_pure_wildcard("{genome_build}") is True
    assert is_pure_wildcard("{x}") is True


def test_is_pure_wildcard_false():
    assert is_pure_wildcard("plain_value") is False
    assert is_pure_wildcard("ref:ToolVersion{name=STAR}") is False
    assert is_pure_wildcard("{sample}_extra") is False
    assert is_pure_wildcard("") is False
    assert is_pure_wildcard(42) is False
    assert is_pure_wildcard("{a}{b}") is False


# ---------------------------------------------------------------------------
# RuleRegistry
# ---------------------------------------------------------------------------

def _make_rule(name, entity_type, match, requires=None):
    return ProductionRule(
        name=name,
        description="",
        produces=ProducesSpec(entity_type=entity_type, match=match),
        requires=requires or [],
        execute=ExecuteSpec(workflow="w.cwl", inputs={}),
    )


def test_registry_wildcard_matches_any_value():
    rule = _make_rule("r", "AlignedReads", {"sample": "{sample}"})
    registry = RuleRegistry([rule])
    assert registry.find_rule("AlignedReads", {"sample": "S001"}) is rule
    assert registry.find_rule("AlignedReads", {"sample": "ANYTHINGELSE"}) is rule


def test_registry_fixed_param_must_match_exactly():
    rule = _make_rule("r", "AlignedReads", {"genome_build": "GRCh38"})
    registry = RuleRegistry([rule])
    assert registry.find_rule("AlignedReads", {"genome_build": "GRCh38"}) is rule
    assert registry.find_rule("AlignedReads", {"genome_build": "GRCh37"}) is None
    assert registry.find_rule("AlignedReads", {}) is None


def test_registry_rules_for_entity_type():
    r1 = _make_rule("r1", "AlignedReads", {})
    r2 = _make_rule("r2", "GeneAnnotation", {})
    r3 = _make_rule("r3", "AlignedReads", {"tool": "bowtie"})
    registry = RuleRegistry([r1, r2, r3])
    aligned = registry.rules_for_entity_type("AlignedReads")
    assert len(aligned) == 2
    assert {x.name for x in aligned} == {"r1", "r3"}
    assert registry.rules_for_entity_type("GeneAnnotation") == [r2]
    assert registry.rules_for_entity_type("Unknown") == []


def test_registry_wrong_entity_type_never_matches():
    rule = _make_rule("r", "AlignedReads", {"sample": "{sample}"})
    registry = RuleRegistry([rule])
    assert registry.find_rule("GeneAnnotation", {"sample": "S001"}) is None


def test_registry_glob_wildcard_matches_when_field_absent():
    """'*' in a rule match means the field is optional — absent in request is fine."""
    rule = _make_rule(
        "r",
        "AlignmentFile",
        {"sample_id": "{sample_id}", "genome": "{genome}", "tool_version": "*"},
    )
    registry = RuleRegistry([rule])
    # Caller omits tool_version entirely — still matches
    assert registry.find_rule("AlignmentFile", {"sample_id": "S001", "genome": "GRCh38"}) is rule


def test_registry_glob_wildcard_matches_when_field_present():
    """'*' in a rule match also accepts any value when the field IS provided."""
    rule = _make_rule(
        "r",
        "AlignmentFile",
        {"sample_id": "{sample_id}", "genome": "{genome}", "tool_version": "*"},
    )
    registry = RuleRegistry([rule])
    assert registry.find_rule(
        "AlignmentFile",
        {"sample_id": "S001", "genome": "GRCh38", "tool_version": "2.7.10a"},
    ) is rule
    assert registry.find_rule(
        "AlignmentFile",
        {"sample_id": "S001", "genome": "GRCh38", "tool_version": "any_version"},
    ) is rule


def test_registry_glob_wildcard_only_field_always_matches():
    """A rule with only '*' fields matches any params (or none)."""
    rule = _make_rule("r", "AlignmentFile", {"tool_version": "*"})
    registry = RuleRegistry([rule])
    assert registry.find_rule("AlignmentFile", {}) is rule
    assert registry.find_rule("AlignmentFile", {"tool_version": "STAR_2.7"}) is rule
    assert registry.find_rule("AlignmentFile", {"sample": "S001"}) is rule


def test_registry_named_wildcard_still_requires_field():
    """Named wildcard {sample_id} still requires the field to be present."""
    rule = _make_rule(
        "r",
        "AlignmentFile",
        {"sample_id": "{sample_id}", "tool_version": "*"},
    )
    registry = RuleRegistry([rule])
    # sample_id missing → no match
    assert registry.find_rule("AlignmentFile", {"tool_version": "2.7"}) is None
    # sample_id present → match
    assert registry.find_rule("AlignmentFile", {"sample_id": "S001"}) is rule


def test_entity_ref_in_rules_is_detected():
    rule = _make_rule("r", "AlignedReads", {"tool_version": "ref:ToolVersion{version=2.7.11a}"})
    assert is_entity_ref(rule.produces.match["tool_version"]) is True
    assert is_entity_ref(rule.produces.match.get("other", "plain")) is False


# ---------------------------------------------------------------------------
# FetchRule dataclass
# ---------------------------------------------------------------------------

from canon.rules.models import FetchRule


def test_fetch_rule_is_not_production_rule():
    fetch_rule = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(entity_type="GenomeBuild", match={"name": "GRCh38"}),
        source_uri="https://example.com/genome.fa.gz",
    )
    assert isinstance(fetch_rule, FetchRule)
    assert not isinstance(fetch_rule, ProductionRule)


def test_fetch_rule_optional_checksum():
    rule = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(entity_type="GenomeBuild", match={"name": "GRCh38"}),
        source_uri="https://example.com/genome.fa.gz",
    )
    assert rule.checksum_sha256 is None

    rule_with_checksum = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(entity_type="GenomeBuild", match={"name": "GRCh38"}),
        source_uri="https://example.com/genome.fa.gz",
        checksum_sha256="abc123",
    )
    assert rule_with_checksum.checksum_sha256 == "abc123"


# ---------------------------------------------------------------------------
# RulesLoader — fetch rules
# ---------------------------------------------------------------------------

_FETCH_RULE_YAML = {
    "rules": [
        {
            "name": "fetch_grch38_ensembl110",
            "type": "fetch",
            "produces": {
                "entity_type": "GenomeBuild",
                "match": {"name": "GRCh38", "source": "ensembl", "release": "110"},
            },
            "fetch": {
                "source_uri": "https://ftp.ensembl.org/pub/genome.fa.gz",
                "checksum_sha256": "abc123",
            },
        }
    ]
}


def test_rules_loader_parses_fetch_rule(tmp_path):
    p = _write_rules(tmp_path, _FETCH_RULE_YAML)
    loader = RulesLoader(p)
    rules = loader.load()
    assert len(rules) == 1
    rule = rules[0]
    assert isinstance(rule, FetchRule)
    assert rule.name == "fetch_grch38_ensembl110"
    assert rule.produces.entity_type == "GenomeBuild"
    assert rule.source_uri == "https://ftp.ensembl.org/pub/genome.fa.gz"
    assert rule.checksum_sha256 == "abc123"


def test_rules_loader_raises_on_missing_source_uri(tmp_path):
    data = {
        "rules": [
            {
                "name": "bad_fetch",
                "type": "fetch",
                "produces": {"entity_type": "GenomeBuild", "match": {}},
                "fetch": {},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError, match="source_uri"):
        RulesLoader(p).load()


def test_rules_loader_raises_on_invalid_source_uri_scheme(tmp_path):
    data = {
        "rules": [
            {
                "name": "ftp_fetch",
                "type": "fetch",
                "produces": {"entity_type": "GenomeBuild", "match": {}},
                "fetch": {"source_uri": "ftp://example.com/genome.fa"},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError, match="ftp"):
        RulesLoader(p).load()


def test_rules_loader_mixed_production_and_fetch(tmp_path):
    _make_cwl_and_sidecar(tmp_path, "workflows/star_align.cwl")
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
                    {"bind": "reads", "entity_type": "RawReads", "match": {"sample": "{sample}"}}
                ],
                "execute": {
                    "workflow": "workflows/star_align.cwl",
                    "inputs": {"reads_fastq": "{reads.uri}", "genome_build": "{genome_build}"},
                },
            },
            {
                "name": "fetch_grch38",
                "type": "fetch",
                "produces": {"entity_type": "GenomeBuild", "match": {"name": "GRCh38"}},
                "fetch": {"source_uri": "https://example.com/genome.fa.gz"},
            },
        ]
    }
    p = _write_rules(tmp_path, data)
    rules = RulesLoader(p).load()
    assert len(rules) == 2
    production = [r for r in rules if isinstance(r, ProductionRule)]
    fetch = [r for r in rules if isinstance(r, FetchRule)]
    assert len(production) == 1
    assert len(fetch) == 1


# ---------------------------------------------------------------------------
# RuleRegistry — fetch rules
# ---------------------------------------------------------------------------

def test_registry_find_fetch_rule_returns_match():
    fetch_rule = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38", "source": "ensembl", "release": "110"},
        ),
        source_uri="https://example.com/genome.fa.gz",
    )
    registry = RuleRegistry([fetch_rule])
    result = registry.find_fetch_rule("GenomeBuild", {"name": "GRCh38", "source": "ensembl", "release": "110"})
    assert result is fetch_rule


def test_registry_find_fetch_rule_returns_none_no_match():
    fetch_rule = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(
            entity_type="GenomeBuild",
            match={"name": "GRCh38"},
        ),
        source_uri="https://example.com/genome.fa.gz",
    )
    registry = RuleRegistry([fetch_rule])
    result = registry.find_fetch_rule("GenomeBuild", {"name": "CHM13", "release": "2.0"})
    assert result is None


def test_registry_find_fetch_rule_wrong_entity_type():
    fetch_rule = FetchRule(
        name="fetch_grch38",
        produces=ProducesSpec(entity_type="GenomeBuild", match={"name": "GRCh38"}),
        source_uri="https://example.com/genome.fa.gz",
    )
    registry = RuleRegistry([fetch_rule])
    result = registry.find_fetch_rule("AlignedReads", {"name": "GRCh38"})
    assert result is None


# ---------------------------------------------------------------------------
# AggregateRule dataclass
# ---------------------------------------------------------------------------

def _make_aggregate_rule(
    name="merge_gene_counts",
    entity_type="CountsMatrix",
    match=None,
    collect_entity_type="GeneCounts",
    collect_match=None,
    group_by="cohort_id",
):
    return AggregateRule(
        name=name,
        produces=ProducesSpec(
            entity_type=entity_type,
            match=match or {"cohort_id": "{cohort_id}", "genome": "{genome}"},
        ),
        collect=CollectSpec(
            entity_type=collect_entity_type,
            match=collect_match or {"genome": "{genome}"},
            group_by=group_by,
        ),
        execute=ExecuteSpec(workflow="workflows/merge_counts.cwl", inputs={}),
    )


def test_aggregate_rule_is_not_production_rule():
    rule = _make_aggregate_rule()
    assert isinstance(rule, AggregateRule)
    assert not isinstance(rule, ProductionRule)


def test_aggregate_rule_collect_spec_fields():
    rule = _make_aggregate_rule()
    assert rule.collect.entity_type == "GeneCounts"
    assert rule.collect.group_by == "cohort_id"
    assert rule.collect.match["genome"] == "{genome}"


# ---------------------------------------------------------------------------
# RulesLoader — aggregate rules
# ---------------------------------------------------------------------------

_AGGREGATE_RULE_YAML = {
    "rules": [
        {
            "name": "merge_gene_counts",
            "type": "aggregate",
            "produces": {
                "entity_type": "CountsMatrix",
                "match": {"cohort_id": "{cohort_id}", "genome": "{genome}"},
            },
            "collect": {
                "entity_type": "GeneCounts",
                "match": {"genome": "{genome}"},
                "group_by": "cohort_id",
            },
            "execute": {
                "workflow": "workflows/merge_counts.cwl",
                "inputs": {"input_files": "{input_files}"},
            },
        }
    ]
}


def test_rules_loader_parses_aggregate_rule(tmp_path):
    p = _write_rules(tmp_path, _AGGREGATE_RULE_YAML)
    rules = RulesLoader(p).load()
    assert len(rules) == 1
    rule = rules[0]
    assert isinstance(rule, AggregateRule)
    assert rule.name == "merge_gene_counts"
    assert rule.produces.entity_type == "CountsMatrix"
    assert rule.produces.match["cohort_id"] == "{cohort_id}"
    assert rule.collect.entity_type == "GeneCounts"
    assert rule.collect.group_by == "cohort_id"
    assert rule.collect.match["genome"] == "{genome}"
    assert rule.execute.workflow == "workflows/merge_counts.cwl"


def test_rules_loader_aggregate_missing_collect_raises(tmp_path):
    data = {
        "rules": [
            {
                "name": "bad_agg",
                "type": "aggregate",
                "produces": {"entity_type": "CountsMatrix", "match": {}},
                "execute": {"workflow": "w.cwl", "inputs": {}},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError, match="collect"):
        RulesLoader(p).load()


def test_rules_loader_aggregate_missing_group_by_raises(tmp_path):
    data = {
        "rules": [
            {
                "name": "bad_agg",
                "type": "aggregate",
                "produces": {"entity_type": "CountsMatrix", "match": {}},
                "collect": {"entity_type": "GeneCounts", "match": {}},
                "execute": {"workflow": "w.cwl", "inputs": {}},
            }
        ]
    }
    p = _write_rules(tmp_path, data)
    with pytest.raises(CanonRuleValidationError, match="group_by"):
        RulesLoader(p).load()


def test_rules_loader_mixed_all_three_types(tmp_path):
    _make_cwl_and_sidecar(tmp_path, "workflows/star_align.cwl")
    data = {
        "rules": [
            {
                "name": "align-reads",
                "produces": {
                    "entity_type": "AlignedReads",
                    "match": {"sample": "{sample}"},
                },
                "requires": [],
                "execute": {"workflow": "workflows/star_align.cwl", "inputs": {}},
            },
            {
                "name": "fetch_grch38",
                "type": "fetch",
                "produces": {"entity_type": "GenomeBuild", "match": {"name": "GRCh38"}},
                "fetch": {"source_uri": "https://example.com/genome.fa.gz"},
            },
            {
                "name": "merge_gene_counts",
                "type": "aggregate",
                "produces": {
                    "entity_type": "CountsMatrix",
                    "match": {"cohort_id": "{cohort_id}", "genome": "{genome}"},
                },
                "collect": {
                    "entity_type": "GeneCounts",
                    "match": {"genome": "{genome}"},
                    "group_by": "cohort_id",
                },
                "execute": {"workflow": "workflows/merge_counts.cwl", "inputs": {}},
            },
        ]
    }
    p = _write_rules(tmp_path, data)
    rules = RulesLoader(p).load()
    assert len(rules) == 3
    production = [r for r in rules if isinstance(r, ProductionRule)]
    fetch = [r for r in rules if isinstance(r, FetchRule)]
    aggregate = [r for r in rules if isinstance(r, AggregateRule)]
    assert len(production) == 1
    assert len(fetch) == 1
    assert len(aggregate) == 1


# ---------------------------------------------------------------------------
# RuleRegistry — aggregate rules
# ---------------------------------------------------------------------------

def test_registry_find_aggregate_rule_returns_match():
    rule = _make_aggregate_rule()
    registry = RuleRegistry([rule])
    result = registry.find_aggregate_rule(
        "CountsMatrix", {"cohort_id": "C001", "genome": "GRCh38"}
    )
    assert result is rule


def test_registry_find_aggregate_rule_wrong_entity_type():
    rule = _make_aggregate_rule()
    registry = RuleRegistry([rule])
    result = registry.find_aggregate_rule("AlignedReads", {"cohort_id": "C001"})
    assert result is None


def test_registry_find_aggregate_rule_returns_none_when_missing_param():
    rule = _make_aggregate_rule()
    registry = RuleRegistry([rule])
    # cohort_id is a named wildcard — must be present
    result = registry.find_aggregate_rule("CountsMatrix", {"genome": "GRCh38"})
    assert result is None


def test_registry_aggregate_rules_stored_separately_from_production():
    prod_rule = _make_rule("prod", "AlignedReads", {"sample": "{sample}"})
    agg_rule = _make_aggregate_rule()
    registry = RuleRegistry([prod_rule, agg_rule])
    assert registry.find_rule("CountsMatrix", {"cohort_id": "C001", "genome": "GRCh38"}) is None
    assert registry.find_aggregate_rule("CountsMatrix", {"cohort_id": "C001", "genome": "GRCh38"}) is agg_rule
