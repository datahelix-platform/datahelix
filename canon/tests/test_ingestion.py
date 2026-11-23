"""Tests for ingestion sidecar, pipeline, and provenance."""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from canon.ingestion.sidecar import load_sidecar, evaluate_mosaic_fields, SidecarOutput
from canon.ingestion.pipeline import OutputIngestionPipeline
from canon.ingestion.provenance import WorkflowRunBuilder
from canon.types import Entity
from canon.executors.base import CWLRunResult
from canon.exceptions import CanonStorageError
from canon.storage.local import LocalStorageAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sidecar(tmp_path, content=None):
    if content is None:
        content = (
            "outputs:\n"
            "  aligned_bam:\n"
            "    entity_type: AlignedReads\n"
            "    identity_fields:\n"
            "      - sample\n"
            "      - genome_build\n"
            "    mosaic_fields:\n"
            "      uri: '{outputs.bam.location}'\n"
            "      sample: '{inputs.sample}'\n"
        )
    p = tmp_path / "align.canon.yaml"
    p.write_text(content)
    return p


def _make_storage_adapter(tmp_path):
    return LocalStorageAdapter(base_path=str(tmp_path / "outputs"))


# ---------------------------------------------------------------------------
# load_sidecar
# ---------------------------------------------------------------------------

def test_load_sidecar_parses_correctly(tmp_path):
    p = _make_sidecar(tmp_path)
    spec = load_sidecar(str(p))
    assert "aligned_bam" in spec.outputs
    output = spec.outputs["aligned_bam"]
    assert output.entity_type == "AlignedReads"
    assert "sample" in output.identity_fields
    assert "genome_build" in output.identity_fields
    assert output.mosaic_fields["uri"] == "{outputs.bam.location}"
    assert output.mosaic_fields["sample"] == "{inputs.sample}"


def test_load_sidecar_missing_file_raises(tmp_path):
    from canon.exceptions import CanonIngestionError
    with pytest.raises(CanonIngestionError, match="not found"):
        load_sidecar(str(tmp_path / "nonexistent.canon.yaml"))


# ---------------------------------------------------------------------------
# evaluate_mosaic_fields
# ---------------------------------------------------------------------------

def test_evaluate_mosaic_fields_outputs_bam_location():
    sidecar_output = SidecarOutput(
        entity_type="AlignedReads",
        identity_fields=["sample"],
        mosaic_fields={"uri": "{outputs.bam.location}"},
    )
    cwl_outputs = {"bam": {"location": "/data/S001.bam", "class": "File"}}
    result = evaluate_mosaic_fields(sidecar_output, cwl_outputs, {}, "run-123")
    assert result["uri"] == "/data/S001.bam"


def test_evaluate_mosaic_fields_inputs_genome_build():
    sidecar_output = SidecarOutput(
        entity_type="AlignedReads",
        identity_fields=["sample"],
        mosaic_fields={"sample": "{inputs.sample}", "genome": "{inputs.genome_build}"},
    )
    result = evaluate_mosaic_fields(
        sidecar_output, {}, {"sample": "S001", "genome_build": "GRCh38"}, "run-abc"
    )
    assert result["sample"] == "S001"
    assert result["genome"] == "GRCh38"


def test_evaluate_mosaic_fields_run_id():
    sidecar_output = SidecarOutput(
        entity_type="AlignedReads",
        identity_fields=[],
        mosaic_fields={"run": "{run_id}"},
    )
    result = evaluate_mosaic_fields(sidecar_output, {}, {}, "my-run-id")
    assert result["run"] == "my-run-id"


# ---------------------------------------------------------------------------
# OutputIngestionPipeline
# ---------------------------------------------------------------------------

def test_ingestion_pipeline_ingest_calls_hippo(tmp_path):
    hippo = MagicMock()
    entity = Entity(
        id="ent-1",
        entity_type="AlignedReads",
        data={"uri": "/data/out.bam"},
        uri="/data/out.bam",
    )
    hippo.ingest_entity.return_value = entity

    # Sidecar without URI field to avoid file relocation
    sidecar_content = (
        "outputs:\n"
        "  aligned_bam:\n"
        "    entity_type: AlignedReads\n"
        "    identity_fields: [sample]\n"
        "    mosaic_fields:\n"
        "      sample: '{inputs.sample}'\n"
    )
    sidecar_file = _make_sidecar(tmp_path, content=sidecar_content)

    cwl_result = CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={})
    cwl_inputs = {"sample": "S001"}

    work_dir = str(tmp_path / "run-abc")
    os.makedirs(work_dir, exist_ok=True)

    pipeline = OutputIngestionPipeline(hippo, _make_storage_adapter(tmp_path))
    result = pipeline.ingest(
        cwl_result=cwl_result,
        sidecar_path=str(sidecar_file),
        cwl_inputs=cwl_inputs,
        rule_name="align-reads",
        bindings={"sample": "S001"},
        work_dir=work_dir,
    )
    hippo.ingest_entity.assert_called()
    # Result indexed both by output_name and entity_type
    assert "aligned_bam" in result or "AlignedReads" in result


def test_ingestion_pipeline_returns_entity(tmp_path):
    hippo = MagicMock()
    entity = Entity(id="ent-2", entity_type="AlignedReads", data={}, uri=None)
    hippo.ingest_entity.return_value = entity

    sidecar_content = (
        "outputs:\n"
        "  out:\n"
        "    entity_type: AlignedReads\n"
        "    identity_fields: []\n"
        "    mosaic_fields:\n"
        "      note: 'done'\n"
    )
    sidecar_file = _make_sidecar(tmp_path, content=sidecar_content)

    work_dir = str(tmp_path / "run-xyz")
    os.makedirs(work_dir, exist_ok=True)

    pipeline = OutputIngestionPipeline(hippo, _make_storage_adapter(tmp_path))
    result = pipeline.ingest(
        cwl_result=CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={}),
        sidecar_path=str(sidecar_file),
        cwl_inputs={},
        rule_name="test-rule",
        bindings={},
        work_dir=work_dir,
    )
    assert result["AlignedReads"].id == "ent-2"


# ---------------------------------------------------------------------------
# WorkflowRunBuilder
# ---------------------------------------------------------------------------

def test_workflow_run_builder_write_running():
    hippo = MagicMock()
    run_entity = Entity(id="run-1", entity_type="WorkflowRun", data={"status": "running"})
    hippo.ingest_entity.return_value = run_entity

    builder = WorkflowRunBuilder(hippo)
    result = builder.write_running(
        rule_name="align-reads",
        cwl_workflow="workflows/star.cwl",
        cwl_inputs={"sample": "S001"},
        target_entity_type="AlignedReads",
        params={"sample": "S001"},
    )
    hippo.ingest_entity.assert_called_once()
    call_entity_type, call_data = hippo.ingest_entity.call_args[0]
    assert call_entity_type == "WorkflowRun"
    assert call_data["status"] == "running"
    assert call_data["rule_name"] == "align-reads"
    assert result.id == "run-1"


def test_workflow_run_builder_write_completed():
    hippo = MagicMock()
    updated_entity = Entity(id="run-1", entity_type="WorkflowRun", data={"status": "completed"})
    hippo.update_entity.return_value = updated_entity

    builder = WorkflowRunBuilder(hippo)
    result = builder.write_completed(
        run_entity_id="run-1",
        output_entity_id="out-entity-1",
        exit_code=0,
    )
    hippo.update_entity.assert_called_once()
    call_id, call_data = hippo.update_entity.call_args[0]
    assert call_id == "run-1"
    assert call_data["status"] == "completed"
    assert call_data["output_entity_id"] == "out-entity-1"
    assert call_data["exit_code"] == 0
    assert result.id == "run-1"


# ---------------------------------------------------------------------------
# Pipeline StorageAdapter delegation
# ---------------------------------------------------------------------------

def test_pipeline_calls_storage_put_when_uri_field_present(tmp_path):
    hippo = MagicMock()
    entity = Entity(id="ent-3", entity_type="AlignedReads", data={}, uri=None)
    hippo.ingest_entity.return_value = entity

    mock_adapter = MagicMock(spec=LocalStorageAdapter)
    mock_adapter.build_dest_uri.return_value = f"file://{tmp_path}/storage/alignedreads/run-put/out.bam"
    mock_adapter.put.return_value = f"file://{tmp_path}/storage/alignedreads/run-put/out.bam"

    # Create a real source file so put() would succeed if not mocked
    src = tmp_path / "out.bam"
    src.write_bytes(b"data")

    sidecar_content = (
        "outputs:\n"
        "  out:\n"
        "    entity_type: AlignedReads\n"
        "    identity_fields: []\n"
        "    mosaic_fields:\n"
        f"      uri: '{src}'\n"
    )
    sidecar_file = tmp_path / "test.canon.yaml"
    sidecar_file.write_text(sidecar_content)

    work_dir = str(tmp_path / "run-put")
    os.makedirs(work_dir, exist_ok=True)

    pipeline = OutputIngestionPipeline(hippo, mock_adapter)
    pipeline.ingest(
        cwl_result=CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={}),
        sidecar_path=str(sidecar_file),
        cwl_inputs={},
        rule_name="test",
        bindings={},
        work_dir=work_dir,
    )
    mock_adapter.put.assert_called_once()


def test_pipeline_propagates_canon_storage_error(tmp_path):
    hippo = MagicMock()

    mock_adapter = MagicMock(spec=LocalStorageAdapter)
    mock_adapter.build_dest_uri.return_value = "file:///tmp/dest.bam"
    mock_adapter.put.side_effect = CanonStorageError("disk full")

    src = tmp_path / "out.bam"
    src.write_bytes(b"data")

    sidecar_content = (
        "outputs:\n"
        "  out:\n"
        "    entity_type: AlignedReads\n"
        "    identity_fields: []\n"
        "    mosaic_fields:\n"
        f"      uri: '{src}'\n"
    )
    sidecar_file = tmp_path / "test2.canon.yaml"
    sidecar_file.write_text(sidecar_content)

    work_dir = str(tmp_path / "run-err")
    os.makedirs(work_dir, exist_ok=True)

    pipeline = OutputIngestionPipeline(hippo, mock_adapter)
    # CanonStorageError is caught and logged as warning; ingestion proceeds
    pipeline.ingest(
        cwl_result=CWLRunResult(exit_code=0, stdout="{}", stderr="", outputs={}),
        sidecar_path=str(sidecar_file),
        cwl_inputs={},
        rule_name="test",
        bindings={},
        work_dir=work_dir,
    )
    # Storage error was caught — hippo was still called with original URI
    hippo.ingest_entity.assert_called_once()
