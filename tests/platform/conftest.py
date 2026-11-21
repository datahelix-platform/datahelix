"""Shared fixtures for platform integration tests.

These tests exercise the real Hippo ↔ Canon contract using an in-process
MosaicClient backed by SQLiteAdapter.  No HTTP server required.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure hippo and canon packages are importable regardless of how pytest is
# invoked (PYTHONPATH env-var path or direct src-tree reference).
_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mosaic.core.client import MosaicClient
from mosaic.core.storage.adapters.sqlite_adapter import SQLiteAdapter
from canon.config import CanonConfig
from canon.executors.base import CWLRunResult
from canon.types import Entity

from tests.conftest import build_test_schema_registry


# ---------------------------------------------------------------------------
# MosaicClientShim
# ---------------------------------------------------------------------------


class MosaicClientShim:
    """Adapter that wraps a real MosaicClient to satisfy RecursivePlanner's
    hippo_client interface (find_entity / ingest_entity / update_entity).

    This removes the need for an HTTP server: Canon talks directly to the
    in-process MosaicClient backed by SQLiteAdapter.
    """

    def __init__(self, hippo_client: MosaicClient) -> None:
        self._client = hippo_client
        # Maps entity_id → entity_type for update_entity lookups
        self._entity_type_cache: dict[str, str] = {}

    def find_entity(self, entity_type: str, filters: dict) -> Entity | None:
        """Query Hippo for a single entity matching all filter key-value pairs.

        Performs a full-type scan then filters in-Python; avoids relying on
        SQLiteAdapter's limited JSON-field filter support.
        """
        result = self._client.query(entity_type)
        for item in result.items:
            data = item.get("data", {})
            if all(str(data.get(k)) == str(v) for k, v in filters.items()):
                self._entity_type_cache[item["id"]] = entity_type
                return Entity(
                    id=item["id"],
                    entity_type=item["entity_type"],
                    data=data,
                    # uri populated from data["uri"] by Entity.__post_init__ if present
                )
        return None

    def ingest_entity(self, entity_type: str, data: dict) -> Entity:
        """Create entity in Hippo and return as a Canon Entity with a URI.

        A synthetic URI (dhlx://<type>/<uuid>) is added to the stored data so
        that RecursivePlanner.resolve() can return a non-None URI.
        """
        synthetic_uri = f"dhlx://{entity_type.lower()}/{uuid.uuid4()}"
        data_with_uri = {**data, "uri": synthetic_uri}
        result = self._client.create(entity_type, data_with_uri)
        self._entity_type_cache[result["id"]] = entity_type
        return Entity(
            id=result["id"],
            entity_type=entity_type,
            data=result["data"],
            uri=synthetic_uri,
        )

    def update_entity(self, entity_id: str, data: dict) -> None:
        """Merge data fields into an existing entity in Hippo.

        Called by RecursivePlanner after a successful fetch to record the
        canonical URI and fetch provenance on the entity record.
        """
        entity_type = self._entity_type_cache.get(entity_id)
        if entity_type is None:
            raise RuntimeError(
                f"MosaicClientShim.update_entity: unknown entity_id {entity_id!r}. "
                "Call find_entity or ingest_entity first so the type is cached."
            )
        current = self._client.get(entity_type, entity_id)
        merged = {**current["data"], **data}
        self._client.update(entity_type, entity_id, merged)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hippo_client(tmp_path: Path) -> MosaicClient:
    """Real MosaicClient backed by SQLiteAdapter in a temporary directory."""
    registry = build_test_schema_registry()
    storage = SQLiteAdapter(str(tmp_path / "hippo.db"), schema_registry=registry)
    return MosaicClient(storage=storage, registry=registry)


@pytest.fixture()
def hippo_shim(hippo_client: MosaicClient) -> MosaicClientShim:
    """MosaicClientShim wrapping the real MosaicClient."""
    return MosaicClientShim(hippo_client)


@pytest.fixture()
def canon_config(tmp_path: Path) -> CanonConfig:
    """Minimal CanonConfig with a rules_file stub in tmp_path.

    mosaic_url is a placeholder — platform tests bypass HTTP and use
    MosaicClientShim directly.
    """
    rules_file = tmp_path / "canon_rules.yaml"
    rules_file.write_text("rules: []\n")
    return CanonConfig.model_validate(
        {
            "mosaic_url": "http://localhost:58080",
            "mosaic_token": "test-token",
            "executor": "cwltool",
            "rules_file": str(rules_file),
            "work_dir": str(tmp_path / "work"),
            "output_storage": {
                "type": "local",
                "base_path": str(tmp_path / "outputs"),
            },
        }
    )


@pytest.fixture()
def mock_executor() -> MagicMock:
    """MagicMock for CwltoolAdapter — returns a successful CWLRunResult."""
    executor = MagicMock()
    executor.run.return_value = CWLRunResult(
        exit_code=0,
        stdout="{}",
        stderr="",
        outputs={"output_uri": {"location": "file:///tmp/output.txt"}},
    )
    return executor


# ---------------------------------------------------------------------------
# Shared fixture factory for cross-component integration tests
# ---------------------------------------------------------------------------

_fixtures_dir = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    """Path to tests/fixtures/ directory."""
    return _fixtures_dir


@pytest.fixture()
def sample_csv_path() -> Path:
    """Path to the sample CSV ingest file."""
    return _fixtures_dir / "sample_ingest.csv"


@pytest.fixture()
def seed_subject(hippo_client: MosaicClient) -> dict:
    """Seed a Subject entity and return it."""
    return hippo_client.create(
        "Subject", {"external_id": "SUBJ-001", "species": "Homo sapiens"}
    )


@pytest.fixture()
def seed_sample(hippo_client: MosaicClient, seed_subject: dict) -> dict:
    """Seed a Sample entity linked to the seeded Subject and return it."""
    return hippo_client.create(
        "Sample",
        {
            "subject_id": seed_subject["id"],
            "tissue_type": "brain",
            "sample_id": "s001",
        },
    )


@pytest.fixture()
def seed_cohort(hippo_client: MosaicClient, seed_subject: dict) -> list[dict]:
    """Seed a cohort of 3 samples for partial-failure testing."""
    samples = []
    for sid, tissue in [("s001", "brain"), ("s002", "liver"), ("s003", "csf")]:
        s = hippo_client.create(
            "Sample",
            {"subject_id": seed_subject["id"], "tissue_type": tissue, "sample_id": sid},
        )
        samples.append(s)
    return samples
