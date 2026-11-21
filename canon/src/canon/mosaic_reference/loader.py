"""CanonReferenceLoader: registers Canon's entity schema with Mosaic."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.yaml"


class CanonReferenceLoader:
    """
    Mosaic reference loader for Canon's built-in entity schema.

    Registered as an entry point under 'mosaic.reference_loaders':
        canon = canon.mosaic_reference.loader:CanonReferenceLoader

    Mosaic discovers and invokes this class to load Canon's entity type
    definitions (Tool, ToolVersion, GenomeBuild, GeneAnnotation, WorkflowRun).
    """

    @property
    def name(self) -> str:
        """Loader identifier used by Mosaic."""
        return "canon"

    def load(self) -> dict[str, Any]:
        """
        Load the Canon schema definition.

        Returns:
            Parsed schema dict from schema.yaml.
        """
        raw = yaml.safe_load(_SCHEMA_PATH.read_text())
        if not isinstance(raw, dict):
            raise RuntimeError(f"Canon schema.yaml is not a YAML mapping: {_SCHEMA_PATH}")
        return raw

    def install(self, hippo_client: Any) -> None:
        """
        POST the Canon schema to Mosaic, registering all entity types.

        Args:
            hippo_client: A MosaicQueryClient (or compatible) instance.
        """
        schema = self.load()
        entity_types = schema.get("entity_types", {})

        for entity_type, definition in entity_types.items():
            logger.info("Installing Canon entity type: %s", entity_type)
            try:
                hippo_client.ingest_entity(
                    "__schema__",
                    {
                        "entity_type": entity_type,
                        "namespace": schema.get("namespace", "canon"),
                        "schema_version": schema.get("schema_version", "1.0"),
                        "definition": definition,
                    },
                )
            except Exception as e:
                logger.warning(
                    "Failed to install entity type %s: %s (may already exist)",
                    entity_type,
                    e,
                )
