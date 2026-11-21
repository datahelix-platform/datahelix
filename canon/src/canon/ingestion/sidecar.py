"""Canon sidecar file parser: maps CWL outputs to Hippo entity fields."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from canon.exceptions import CanonIngestionError

# Matches {outputs.bam.location}, {inputs.genome_build}, {run_id}, etc.
_EXPR_RE = re.compile(r"\{([^}]+)\}")


@dataclass
class SidecarOutput:
    """Definition of a single sidecar output — one Hippo entity to ingest."""

    entity_type: str
    identity_fields: list[str]
    mosaic_fields: dict[str, str]  # mosaic_field_name → expression string


@dataclass
class SidecarSpec:
    """Parsed content of a .canon.yaml sidecar file."""

    outputs: dict[str, SidecarOutput] = field(default_factory=dict)


def load_sidecar(path: str) -> SidecarSpec:
    """
    Load and parse a .canon.yaml sidecar file.

    Args:
        path: Absolute or relative path to the sidecar file.

    Returns:
        Parsed SidecarSpec.

    Raises:
        CanonIngestionError: if the file is missing or malformed.
    """
    p = Path(path)
    if not p.exists():
        raise CanonIngestionError(f"Sidecar file not found: {path}")

    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise CanonIngestionError(f"Sidecar YAML parse error in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise CanonIngestionError(f"Sidecar {path}: must be a YAML mapping")

    outputs_raw = raw.get("outputs", {})
    if not isinstance(outputs_raw, dict):
        raise CanonIngestionError(f"Sidecar {path}: 'outputs' must be a mapping")

    outputs: dict[str, SidecarOutput] = {}
    for name, spec in outputs_raw.items():
        if not isinstance(spec, dict):
            raise CanonIngestionError(
                f"Sidecar {path}: output '{name}' must be a mapping"
            )
        entity_type = spec.get("entity_type")
        if not entity_type:
            raise CanonIngestionError(
                f"Sidecar {path}: output '{name}' is missing 'entity_type'"
            )
        identity_fields = spec.get("identity_fields", [])
        if not isinstance(identity_fields, list):
            raise CanonIngestionError(
                f"Sidecar {path}: output '{name}'.identity_fields must be a list"
            )
        mosaic_fields_raw = spec.get("mosaic_fields", {})
        if not isinstance(mosaic_fields_raw, dict):
            raise CanonIngestionError(
                f"Sidecar {path}: output '{name}'.mosaic_fields must be a mapping"
            )
        outputs[name] = SidecarOutput(
            entity_type=str(entity_type),
            identity_fields=[str(f) for f in identity_fields],
            mosaic_fields={str(k): str(v) for k, v in mosaic_fields_raw.items()},
        )

    return SidecarSpec(outputs=outputs)


def _resolve_dot_path(obj: Any, dot_path: str) -> Any:
    """Traverse a nested dict using dot notation."""
    parts = dot_path.split(".")
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return obj


def evaluate_mosaic_fields(
    sidecar_output: SidecarOutput,
    cwl_outputs: dict[str, Any],
    cwl_inputs: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """
    Evaluate expression strings in sidecar_output.mosaic_fields.

    Supported expression contexts (dot-notation):
      {outputs.<name>.<attr>}  — field from CWL output object
      {inputs.<name>}          — CWL input value
      {run_id}                 — the current run UUID

    Returns:
        Dict of mosaic_field_name → resolved value.
    """
    context: dict[str, Any] = {
        "outputs": cwl_outputs,
        "inputs": cwl_inputs,
        "run_id": run_id,
    }

    result: dict[str, Any] = {}
    for mosaic_field, expr in sidecar_output.mosaic_fields.items():
        if not isinstance(expr, str):
            result[mosaic_field] = expr
            continue

        # If the entire expression is a single placeholder, return the resolved value directly
        single_match = re.fullmatch(r"\{([^}]+)\}", expr.strip())
        if single_match:
            path = single_match.group(1)
            parts = path.split(".", 1)
            root = parts[0]
            rest = parts[1] if len(parts) > 1 else None
            if root in context:
                val = context[root]
                if rest is not None:
                    val = _resolve_dot_path(val, rest)
                result[mosaic_field] = val
            else:
                result[mosaic_field] = None
        else:
            # String interpolation: replace each {expr} with its string value
            def _replace(m: re.Match) -> str:
                path = m.group(1)
                parts = path.split(".", 1)
                root = parts[0]
                rest = parts[1] if len(parts) > 1 else None
                if root in context:
                    val = context[root]
                    if rest is not None:
                        val = _resolve_dot_path(val, rest)
                    return str(val) if val is not None else ""
                return m.group(0)  # leave unresolved placeholders as-is

            result[mosaic_field] = _EXPR_RE.sub(_replace, expr)

    return result
