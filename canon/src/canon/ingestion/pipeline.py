"""OutputIngestionPipeline: post-CWL output parsing and Hippo entity ingestion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from canon.exceptions import CanonIngestionError, CanonStorageError
from canon.executors.base import CWLRunResult
from canon.ingestion.sidecar import evaluate_mosaic_fields, load_sidecar
from canon.storage.base import StorageAdapter
from canon.types import Entity

logger = logging.getLogger(__name__)


class OutputIngestionPipeline:
    """
    Ingests CWL outputs into Hippo after a successful workflow run.

    For each sidecar output definition:
      1. Evaluate mosaic_fields expressions against CWL outputs + inputs
      2. Optionally relocate output files via the configured StorageAdapter
      3. POST entity to Hippo
    """

    def __init__(self, hippo_client: Any, storage_adapter: StorageAdapter) -> None:
        self._hippo = hippo_client
        self._storage = storage_adapter

    def relocate_output(
        self,
        cwl_output_path: str,
        entity_type: str,
        run_id: str,
    ) -> str:
        """
        Move a CWL output file to managed storage via the StorageAdapter.

        Args:
            cwl_output_path: Current file path (local URI or path).
            entity_type: Hippo entity type (used in destination path).
            run_id: Run UUID (used in destination path).

        Returns:
            New canonical URI string.

        Raises:
            CanonStorageError: if the storage adapter cannot relocate the file.
        """
        src = cwl_output_path.removeprefix("file://")
        filename = Path(src).name
        dest_uri = self._storage.build_dest_uri(entity_type, run_id, filename)
        return self._storage.put(src, dest_uri)

    def ingest(
        self,
        cwl_result: CWLRunResult,
        sidecar_path: str,
        cwl_inputs: dict[str, Any],
        rule_name: str,
        bindings: dict[str, Any],
        work_dir: str,
    ) -> dict[str, Entity]:
        """
        Parse CWL outputs, load sidecar, evaluate field expressions, POST to Hippo.

        Args:
            cwl_result: Result of the CWL execution.
            sidecar_path: Path to the .canon.yaml sidecar file.
            cwl_inputs: CWL inputs that were passed to the workflow.
            rule_name: Name of the Canon rule (for logging).
            bindings: Wildcard bindings for this invocation.
            work_dir: Working directory of the run.

        Returns:
            Dict of output_name → ingested Entity.
        """
        run_id = Path(work_dir).name  # use work_dir leaf as run ID

        sidecar = load_sidecar(sidecar_path)
        cwl_outputs = cwl_result.outputs

        ingested: dict[str, Entity] = {}

        for output_name, sidecar_output in sidecar.outputs.items():
            logger.info("Ingesting sidecar output '%s' as %s", output_name, sidecar_output.entity_type)

            try:
                mosaic_fields = evaluate_mosaic_fields(
                    sidecar_output,
                    cwl_outputs=cwl_outputs,
                    cwl_inputs=cwl_inputs,
                    run_id=run_id,
                )
            except Exception as e:
                raise CanonIngestionError(
                    f"Rule {rule_name}: failed to evaluate mosaic_fields for "
                    f"output '{output_name}': {e}"
                ) from e

            # Relocate file outputs if present
            uri_field = mosaic_fields.get("uri") or mosaic_fields.get("location")
            if uri_field and isinstance(uri_field, str):
                try:
                    new_uri = self.relocate_output(uri_field, sidecar_output.entity_type, run_id)
                    if "uri" in mosaic_fields:
                        mosaic_fields["uri"] = new_uri
                    elif "location" in mosaic_fields:
                        mosaic_fields["location"] = new_uri
                except CanonStorageError:
                    logger.warning("Could not relocate %s, using original", uri_field)

            try:
                entity = self._hippo.ingest_entity(sidecar_output.entity_type, mosaic_fields)
                ingested[output_name] = entity
                # Also index by entity_type for planner lookup
                ingested[sidecar_output.entity_type] = entity
                logger.info(
                    "Ingested %s entity %s", sidecar_output.entity_type, entity.id
                )
            except Exception as e:
                raise CanonIngestionError(
                    f"Rule {rule_name}: failed to ingest output '{output_name}' "
                    f"as {sidecar_output.entity_type}: {e}"
                ) from e

        return ingested
