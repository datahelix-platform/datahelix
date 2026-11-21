"""Contract tests: Cappella's behavioral expectations of Canon's resolve() API.

These tests assert the exact behaviors Cappella depends on from Canon's RecursivePlanner.
Written from Cappella's perspective — the consumer — and run against RecursivePlanner
directly.

A failure here means Canon changed a behavioral contract that Cappella relies on.
Treat it like a breaking API change:
  1. If the change was unintentional: fix RecursivePlanner.
  2. If the change was intentional: update this spec + bump Cappella's version
     to signal that integration code may need adaptation.

DO NOT add Canon-internal tests here. This file only asserts what Cappella needs.

See TESTING.md §"CanonClient — Cappella's View" for the full behavioral spec.

Cappella depends on Canon (RecursivePlanner) for:
  - resolve(entity_type, params) → URI string — non-empty, dhlx:// scheme
  - resolve_with_decision() → dict with 'decision' and 'uri' keys
  - Idempotency: same URI on repeated calls; executor called only once (BUILD)
  - CanonNoRuleError: raised when no rule matches (NO_RULE unresolved reason)
  - CanonExecutorError: raised when CWL execution fails (EXECUTOR_ERROR reason)
  - CanonRuleValidationError: raised at startup on invalid rule; not per-resolution
  - Exception hierarchy: all three are CanonError subclasses
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_root = Path(__file__).parent.parent.parent
for _pkg in ("mosaic/src", "canon/src"):
    _p = str(_root / _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mosaic.core.client import MosaicClient
from mosaic.core.storage.adapters.sqlite_adapter import SQLiteAdapter

from tests.conftest import build_test_schema_registry
from canon.exceptions import (
    CanonError,
    CanonExecutorError,
    CanonNoRuleError,
    CanonRuleValidationError,
)
from canon.executors.base import CWLRunResult
from canon.resolver.planner import RecursivePlanner
from canon.rules.models import ExecuteSpec, InputBinding, ProductionRule, ProducesSpec
from canon.rules.registry import RuleRegistry
from canon.types import Entity


# ---------------------------------------------------------------------------
# Minimal MosaicClientShim — maps MosaicClient to RecursivePlanner's interface
# ---------------------------------------------------------------------------


class _HippoShim:
    """Thin adapter between MosaicClient and RecursivePlanner's hippo_client interface.

    RecursivePlanner calls: find_entity, ingest_entity, update_entity.
    These map directly to MosaicClient CRUD operations.
    """

    def __init__(self, client: MosaicClient) -> None:
        self._client = client
        self._type_cache: dict[str, str] = {}

    def find_entity(self, entity_type: str, filters: dict) -> Entity | None:
        result = self._client.query(entity_type)
        for item in result.items:
            data = item.get("data", {})
            if all(str(data.get(k)) == str(v) for k, v in filters.items()):
                self._type_cache[item["id"]] = entity_type
                return Entity(
                    id=item["id"],
                    entity_type=item["entity_type"],
                    data=data,
                )
        return None

    def ingest_entity(self, entity_type: str, data: dict) -> Entity:
        synthetic_uri = f"dhlx://{entity_type.lower()}/{uuid.uuid4()}"
        data_with_uri = {**data, "uri": synthetic_uri}
        result = self._client.create(entity_type, data_with_uri)
        self._type_cache[result["id"]] = entity_type
        return Entity(
            id=result["id"],
            entity_type=entity_type,
            data=result["data"],
            uri=synthetic_uri,
        )

    def update_entity(self, entity_id: str, data: dict) -> None:
        entity_type = self._type_cache.get(entity_id)
        if entity_type is None:
            raise RuntimeError(
                f"_HippoShim.update_entity: unknown entity_id {entity_id!r}. "
                "Call find_entity or ingest_entity first so the type is cached."
            )
        current = self._client.get(entity_type, entity_id)
        self._client.update(entity_type, entity_id, {**current["data"], **data})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hippo_client(tmp_path: Path) -> MosaicClient:
    registry = build_test_schema_registry()
    storage = SQLiteAdapter(str(tmp_path / "hippo.db"), schema_registry=registry)
    return MosaicClient(storage=storage, registry=registry)


@pytest.fixture()
def shim(hippo_client: MosaicClient) -> _HippoShim:
    return _HippoShim(hippo_client)


@pytest.fixture()
def mock_executor() -> MagicMock:
    executor = MagicMock()
    executor.run.return_value = CWLRunResult(
        exit_code=0,
        stdout="{}",
        stderr="",
        outputs={"output_uri": {"location": "file:///tmp/output.txt"}},
    )
    return executor


@pytest.fixture()
def failing_executor() -> MagicMock:
    executor = MagicMock()
    executor.run.return_value = CWLRunResult(
        exit_code=1,
        stdout="",
        stderr="Error: CWL execution failed at step align",
        outputs={},
    )
    return executor


@pytest.fixture()
def align_rule() -> ProductionRule:
    """A minimal ProductionRule that produces AlignedDatafile from Sample.

    This mirrors the integration test schema (sec5 §5.3.2).
    """
    return ProductionRule(
        name="align_sample",
        description="Align a sample to produce an AlignedDatafile",
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
            workflow="workflows/align.cwl",
            inputs={"sample_id": "{sample_id}"},
        ),
    )


def _make_planner(
    shim: _HippoShim,
    rules: list,
    executor: MagicMock | None,
    tmp_path: Path,
) -> RecursivePlanner:
    ref_resolver = MagicMock()
    ref_resolver.resolve.return_value = Entity(
        id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
    )
    return RecursivePlanner(
        hippo_client=shim,
        rule_registry=RuleRegistry(rules),
        entity_ref_resolver=ref_resolver,
        executor=executor,
        ingestion_pipeline=None,
        work_dir_base=str(tmp_path / "work"),
    )


# URI pattern Cappella uses to parse Canon results
# See TESTING.md §"CanonClient — Cappella's View" — URI structure guarantee
CANON_URI_RE = re.compile(r"^dhlx://\w+/[0-9a-f-]{36}$")


# ---------------------------------------------------------------------------
# CONTRACT: resolve() returns a non-empty URI string
#
# Cappella's collection resolver calls canon.resolve(entity_type, params)
# for each sample. It expects a non-empty string URI back on success.
# The URI is stored in HarmonizedCollection and passed to downstream consumers.
# ---------------------------------------------------------------------------


class TestResolveURIContract:
    """Cappella depends on resolve() returning a non-empty URI string."""

    def test_reuse_returns_non_empty_string(self, hippo_client, shim, mock_executor, tmp_path):
        """REUSE path: entity exists in Hippo — resolve() returns its URI."""
        hippo_client.create(
            "AlignedDatafile",
            {"sample_id": "s001", "uri": f"dhlx://aligneddatafile/{uuid.uuid4()}"},
        )
        planner = _make_planner(shim, [], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert isinstance(uri, str), "resolve() must return str on REUSE"
        assert uri, "resolve() must return a non-empty string"

    def test_build_returns_non_empty_string(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """BUILD path: entity absent — executor runs and resolve() returns a URI."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert isinstance(uri, str), "resolve() must return str on BUILD"
        assert uri, "resolve() must return a non-empty string"

    def test_reuse_executor_not_called(self, hippo_client, shim, mock_executor, tmp_path):
        """REUSE path: executor must NOT be called when entity already exists.

        Cappella relies on this to efficiently re-run resolution for large cohorts
        where most samples already have computed outputs.
        """
        hippo_client.create(
            "AlignedDatafile",
            {"sample_id": "s001", "uri": f"dhlx://aligneddatafile/{uuid.uuid4()}"},
        )
        planner = _make_planner(shim, [], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert mock_executor.run.call_count == 0, (
            "Executor must not be called on REUSE — Cappella relies on this "
            "for efficient re-runs of large cohorts"
        )


# ---------------------------------------------------------------------------
# CONTRACT: URI format — dhlx://<entity_type>/<uuid36>
#
# Cappella parses Canon URIs to extract entity_type and UUID for downstream
# Hippo queries and provenance tracking.  The format must be stable.
# See TESTING.md: "URI structure guarantee"
# ---------------------------------------------------------------------------


class TestURIFormatContract:
    """Cappella parses Canon URIs — the dhlx://<type>/<uuid> format must be stable."""

    def test_build_uri_matches_dhlx_scheme(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """BUILD URI must match dhlx://<entity_type>/<uuid36>."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert CANON_URI_RE.match(uri), (
            f"URI {uri!r} does not match dhlx://<type>/<uuid36> — "
            "Cappella extracts entity_type and UUID from this URI for Hippo queries"
        )

    def test_uri_uuid_component_is_36_chars(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """UUID component of the URI must be 36 characters (UUID4 with hyphens)."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        uri = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        uuid_part = uri.rsplit("/", 1)[-1]
        assert len(uuid_part) == 36, (
            f"UUID component {uuid_part!r} is not 36 characters — "
            "Cappella's URI parser expects UUID4 format"
        )


# ---------------------------------------------------------------------------
# CONTRACT: idempotency
#
# Cappella re-runs resolution runs for checkpoint recovery and safe retries.
# resolve() must return the same URI on repeated calls with the same params.
# On the second call, the entity exists in Hippo → REUSE path, no CWL re-execution.
# See TESTING.md: "Idempotency guarantee"
# ---------------------------------------------------------------------------


class TestIdempotencyContract:
    """Cappella re-runs resolution — resolve() must be idempotent."""

    def test_resolve_twice_returns_same_uri(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """Two consecutive resolve() calls with the same params must return the same URI."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        uri_1 = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        uri_2 = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert uri_1 == uri_2, (
            "resolve() must return the same URI on repeated calls — "
            "Cappella relies on idempotency for checkpoint recovery and safe re-runs"
        )

    def test_resolve_twice_executor_called_once(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """Second resolve() call must use REUSE path — executor must not run again."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert mock_executor.run.call_count == 1, (
            "Executor must be called exactly once — second call must be REUSE; "
            "Cappella depends on this for safe re-runs without duplicating CWL jobs"
        )


# ---------------------------------------------------------------------------
# CONTRACT: resolve_with_decision() — decision field
#
# Cappella's reconciliation module calls resolve_with_decision() to record
# whether each sample required a BUILD or a REUSE.  This feeds the
# HarmonizedCollection provenance and the SyncRun audit log.
# ---------------------------------------------------------------------------


class TestResolveWithDecisionContract:
    """Cappella depends on resolve_with_decision() returning decision and uri."""

    def test_reuse_decision_is_reuse(self, hippo_client, shim, mock_executor, tmp_path):
        """REUSE path: resolve_with_decision()['decision'] must equal 'REUSE'."""
        hippo_client.create(
            "AlignedDatafile",
            {"sample_id": "s001", "uri": f"dhlx://aligneddatafile/{uuid.uuid4()}"},
        )
        planner = _make_planner(shim, [], mock_executor, tmp_path)
        result = planner.resolve_with_decision("AlignedDatafile", {"sample_id": "s001"})
        assert isinstance(result, dict), "resolve_with_decision() must return a dict"
        assert "decision" in result, "Result must have 'decision' key — Cappella reads this"
        assert "uri" in result, "Result must have 'uri' key — Cappella stores this"
        assert result["decision"] == "REUSE", (
            f"Expected decision='REUSE', got {result['decision']!r}"
        )

    def test_build_decision_is_build(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """BUILD path: resolve_with_decision()['decision'] must equal 'BUILD'."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        result = planner.resolve_with_decision("AlignedDatafile", {"sample_id": "s001"})
        assert result["decision"] == "BUILD", (
            f"Expected decision='BUILD', got {result['decision']!r}"
        )
        assert result["uri"], "BUILD result must have a non-empty uri"

    def test_result_uri_matches_resolve(
        self, hippo_client, shim, mock_executor, align_rule, tmp_path
    ):
        """resolve_with_decision()['uri'] must equal what resolve() returns.

        Cappella uses both interchangeably depending on whether it needs the decision.
        """
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], mock_executor, tmp_path)
        result = planner.resolve_with_decision("AlignedDatafile", {"sample_id": "s001"})
        # Second call is REUSE (entity now in Hippo) — URI must still match
        uri_direct = planner.resolve("AlignedDatafile", {"sample_id": "s001"})
        assert result["uri"] == uri_direct, (
            "resolve_with_decision()['uri'] must equal resolve() — "
            "Cappella uses both interchangeably"
        )


# ---------------------------------------------------------------------------
# CONTRACT: exception types and hierarchy
#
# Cappella handles Canon exceptions per-sample and continues the run.
# Only three typed exceptions are caught as non-aborting per-sample failures:
#   CanonNoRuleError     → reason: NO_RULE
#   CanonExecutorError   → reason: EXECUTOR_ERROR
#   CanonRuleValidationError → startup error (propagated as Cappella startup failure)
#
# All three must be CanonError subclasses so Cappella can catch CanonError
# as a final safety net.
# See TESTING.md §"CanonClient — Cappella's View" — Partial failure format
# ---------------------------------------------------------------------------


class TestExceptionHierarchyContract:
    """All Canon exceptions Cappella handles must be CanonError subclasses."""

    def test_canon_no_rule_error_is_canon_error(self):
        """CanonNoRuleError must inherit from CanonError."""
        assert issubclass(CanonNoRuleError, CanonError), (
            "CanonNoRuleError must be a CanonError subclass — "
            "Cappella catches CanonError as a final safety net"
        )

    def test_canon_executor_error_is_canon_error(self):
        """CanonExecutorError must inherit from CanonError."""
        assert issubclass(CanonExecutorError, CanonError)

    def test_canon_rule_validation_error_is_canon_error(self):
        """CanonRuleValidationError must inherit from CanonError."""
        assert issubclass(CanonRuleValidationError, CanonError)


class TestExceptionBehaviorContract:
    """Cappella maps Canon exception types to HarmonizedCollection unresolved reasons."""

    def test_no_rule_raises_canon_no_rule_error(self, shim, mock_executor, tmp_path):
        """No matching rule: CanonNoRuleError raised — Cappella maps to NO_RULE reason."""
        planner = _make_planner(shim, [], mock_executor, tmp_path)
        with pytest.raises(CanonNoRuleError):
            planner.resolve("AlignedDatafile", {"sample_id": "s-missing"})

    def test_no_rule_error_carries_entity_type(self, shim, mock_executor, tmp_path):
        """CanonNoRuleError.entity_type must be the requested type — Cappella logs this."""
        planner = _make_planner(shim, [], mock_executor, tmp_path)
        try:
            planner.resolve("AlignedDatafile", {"sample_id": "s999"})
            pytest.fail("Expected CanonNoRuleError")
        except CanonNoRuleError as e:
            assert e.entity_type == "AlignedDatafile", (
                "CanonNoRuleError.entity_type must match the requested entity type — "
                "Cappella uses this attribute for structured error reporting"
            )

    def test_executor_failure_raises_canon_executor_error(
        self, hippo_client, shim, failing_executor, align_rule, tmp_path
    ):
        """Executor exit_code != 0: CanonExecutorError raised — Cappella maps to EXECUTOR_ERROR."""
        hippo_client.create("Sample", {"sample_id": "s001"})
        planner = _make_planner(shim, [align_rule], failing_executor, tmp_path)
        with pytest.raises(CanonExecutorError):
            planner.resolve("AlignedDatafile", {"sample_id": "s001"})

    def test_no_executor_configured_raises_canon_executor_error(
        self, hippo_client, shim, align_rule, tmp_path
    ):
        """No executor + entity absent: CanonExecutorError raised — not a silent no-op.

        Cappella must never receive a None or empty URI silently. If Canon cannot
        execute (no executor), it must raise so Cappella can mark the sample as
        EXECUTOR_ERROR rather than emitting a broken HarmonizedCollection.
        """
        hippo_client.create("Sample", {"sample_id": "s001"})
        ref_resolver = MagicMock()
        ref_resolver.resolve.return_value = Entity(
            id="ref-uuid", entity_type="Unknown", data={}, uri="dhlx://ref/unknown"
        )
        planner = RecursivePlanner(
            hippo_client=shim,
            rule_registry=RuleRegistry([align_rule]),
            entity_ref_resolver=ref_resolver,
            executor=None,       # deliberately no executor
            ingestion_pipeline=None,
            work_dir_base=str(tmp_path / "work"),
        )
        with pytest.raises(CanonExecutorError):
            planner.resolve("AlignedDatafile", {"sample_id": "s001"})
