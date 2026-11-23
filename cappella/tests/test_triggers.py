"""Tests for webhook and mosaic_poll trigger types."""
import hashlib
import hmac
import json

import pytest

from cappella.exceptions import TriggerError
from cappella.triggers.engine import (
    HippoPollHandler,
    HippoPollState,
    TriggerEngine,
    TriggerExecutor,
    WebhookHandler,
)
from cappella.triggers.models import (
    ActionConfig,
    HippoPollConfig,
    TriggerConfig,
    TriggerProvenance,
    WebhookConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(secret: str, payload: bytes) -> str:
    """Create an HMAC-SHA256 signature for a payload."""
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _webhook_trigger(
    name: str = "lims-webhook",
    path: str = "/webhooks/lims-ingest",
    secret: str = "test-secret",
    payload_mapping: dict | None = None,
) -> TriggerConfig:
    return TriggerConfig(
        name=name,
        type="webhook",
        action=ActionConfig(type="ingest", adapter="lims"),
        webhook=WebhookConfig(
            path=path,
            secret=secret,
            payload_mapping=payload_mapping or {},
        ),
    )


def _hippo_poll_trigger(
    name: str = "poll-samples",
    entity_type: str = "Sample",
    interval: str = "*/5 * * * *",
) -> TriggerConfig:
    return TriggerConfig(
        name=name,
        type="mosaic_poll",
        action=ActionConfig(type="ingest", adapter="hippo"),
        mosaic_poll=HippoPollConfig(
            entity_type=entity_type,
            interval=interval,
        ),
    )


class MockHippoClient:
    """Minimal mock for mosaic_poll testing."""

    def __init__(self, entities: list[dict] | None = None) -> None:
        self._entities = entities or []

    def query_entities(self, entity_type: str, **kwargs) -> list[dict]:
        filter_spec = kwargs.get("filter", {})
        results = [e for e in self._entities if e.get("entity_type") == entity_type]
        if filter_spec:
            for field, cond in filter_spec.items():
                if "$gt" in cond:
                    results = [e for e in results if e.get(field, "") > cond["$gt"]]
        return results


# ===========================================================================
# WebhookConfig model tests
# ===========================================================================


class TestWebhookConfig:
    def test_verify_signature_valid(self):
        cfg = WebhookConfig(path="/webhooks/test", secret="my-secret")
        payload = b'{"event": "sample_created"}'
        sig = _make_signature("my-secret", payload)
        assert cfg.verify_signature(payload, sig) is True

    def test_verify_signature_invalid(self):
        cfg = WebhookConfig(path="/webhooks/test", secret="my-secret")
        payload = b'{"event": "sample_created"}'
        assert cfg.verify_signature(payload, "sha256=bad") is False

    def test_verify_signature_without_prefix(self):
        cfg = WebhookConfig(path="/webhooks/test", secret="my-secret")
        payload = b"hello"
        raw_sig = hmac.new(b"my-secret", payload, hashlib.sha256).hexdigest()
        assert cfg.verify_signature(payload, raw_sig) is True


# ===========================================================================
# TriggerProvenance tests
# ===========================================================================


class TestTriggerProvenance:
    def test_hash_payload(self):
        payload = b"test-payload"
        expected = hashlib.sha256(payload).hexdigest()
        assert TriggerProvenance.hash_payload(payload) == expected


# ===========================================================================
# WebhookHandler tests
# ===========================================================================


class TestWebhookHandler:
    def test_handle_webhook_success(self):
        trigger = _webhook_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)
        handler = WebhookHandler(triggers, executor)

        payload = json.dumps({"sample_id": "S-001"}).encode()
        sig = _make_signature("test-secret", payload)

        result = handler.handle_webhook("/webhooks/lims-ingest", payload, sig)
        assert result["status"] == "success"
        assert result["trigger"] == "lims-webhook"

    def test_handle_webhook_invalid_signature(self):
        trigger = _webhook_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)
        handler = WebhookHandler(triggers, executor)

        payload = b'{"sample_id": "S-001"}'
        with pytest.raises(TriggerError, match="invalid signature"):
            handler.handle_webhook("/webhooks/lims-ingest", payload, "sha256=wrong")

    def test_handle_webhook_unknown_path(self):
        trigger = _webhook_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)
        handler = WebhookHandler(triggers, executor)

        with pytest.raises(TriggerError, match="no trigger registered"):
            handler.handle_webhook("/webhooks/unknown", b"{}", "sha256=x")

    def test_handle_webhook_payload_mapping(self):
        trigger = _webhook_trigger(
            payload_mapping={"entity_id": "id", "entity_name": "name"}
        )
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)
        handler = WebhookHandler(triggers, executor)

        payload = json.dumps({"id": "123", "name": "Test", "extra": "ignored"}).encode()
        sig = _make_signature("test-secret", payload)

        result = handler.handle_webhook("/webhooks/lims-ingest", payload, sig)
        ctx = result["result"]["trigger_context"]
        assert ctx["webhook_payload"] == {"entity_id": "123", "entity_name": "Test"}

    def test_handle_webhook_records_provenance(self):
        trigger = _webhook_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)
        handler = WebhookHandler(triggers, executor)

        payload = b'{"x": 1}'
        sig = _make_signature("test-secret", payload)

        result = handler.handle_webhook("/webhooks/lims-ingest", payload, sig)
        prov = result["result"]["trigger_context"]["provenance"]
        assert prov["trigger_name"] == "lims-webhook"
        assert prov["trigger_type"] == "webhook"
        assert prov["payload_hash"] == hashlib.sha256(payload).hexdigest()


# ===========================================================================
# HippoPollState tests
# ===========================================================================


class TestHippoPollState:
    def test_dedup_tracking(self):
        state = HippoPollState()
        assert state.is_processed("t1", "key1") is False
        state.mark_processed("t1", "key1")
        assert state.is_processed("t1", "key1") is True
        assert state.is_processed("t1", "key2") is False

    def test_last_seen(self):
        state = HippoPollState()
        assert state.get_last_seen("t1") is None
        state.set_last_seen("t1", "2026-04-01T00:00:00Z")
        assert state.get_last_seen("t1") == "2026-04-01T00:00:00Z"

    def test_reset(self):
        state = HippoPollState()
        state.set_last_seen("t1", "2026-04-01T00:00:00Z")
        state.mark_processed("t1", "key1")
        state.reset("t1")
        assert state.get_last_seen("t1") is None
        assert state.is_processed("t1", "key1") is False


# ===========================================================================
# HippoPollHandler tests
# ===========================================================================


class TestHippoPollHandler:
    def test_poll_with_new_entities(self):
        trigger = _hippo_poll_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)

        mock_hippo = MockHippoClient(entities=[
            {
                "entity_type": "Sample",
                "external_id": "EXT-001",
                "updated_at": "2026-04-01T12:00:00Z",
                "name": "Sample A",
            },
        ])

        handler = HippoPollHandler(triggers, executor, hippo_client=mock_hippo)
        result = handler.poll("poll-samples")
        assert result["status"] == "success"
        assert result["result"]["trigger_context"]["new_count"] == 1

    def test_poll_deduplicates(self):
        trigger = _hippo_poll_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)

        mock_hippo = MockHippoClient(entities=[
            {
                "entity_type": "Sample",
                "external_id": "EXT-001",
                "updated_at": "2026-04-01T12:00:00Z",
                "name": "Sample A",
            },
        ])

        handler = HippoPollHandler(triggers, executor, hippo_client=mock_hippo)

        # First poll picks up the entity
        result1 = handler.poll("poll-samples")
        assert result1["status"] == "success"

        # Second poll should see no new entities (dedup)
        result2 = handler.poll("poll-samples")
        assert result2["status"] == "no_changes"

    def test_poll_no_hippo_client(self):
        trigger = _hippo_poll_trigger()
        triggers = {trigger.name: trigger}
        executor = TriggerExecutor(triggers)

        handler = HippoPollHandler(triggers, executor, hippo_client=None)
        result = handler.poll("poll-samples")
        assert result["status"] == "no_changes"

    def test_poll_unknown_trigger(self):
        handler = HippoPollHandler({}, TriggerExecutor({}))
        with pytest.raises(TriggerError, match="unknown trigger"):
            handler.poll("nonexistent")

    def test_poll_wrong_type(self):
        trigger = TriggerConfig(
            name="manual-trigger",
            type="manual",
            action=ActionConfig(type="ingest"),
        )
        triggers = {trigger.name: trigger}
        handler = HippoPollHandler(triggers, TriggerExecutor(triggers))
        with pytest.raises(TriggerError, match="not a mosaic_poll trigger"):
            handler.poll("manual-trigger")


# ===========================================================================
# TriggerEngine integration tests
# ===========================================================================


class TestTriggerEngineWebhook:
    def test_engine_handle_webhook(self):
        trigger = _webhook_trigger()
        engine = TriggerEngine(triggers=[trigger])

        payload = json.dumps({"event": "created"}).encode()
        sig = _make_signature("test-secret", payload)

        result = engine.handle_webhook("/webhooks/lims-ingest", payload, sig)
        assert result["status"] == "success"

    def test_engine_add_webhook_trigger(self):
        engine = TriggerEngine()
        trigger = _webhook_trigger()
        engine.add_trigger(trigger)

        payload = b'{"data": true}'
        sig = _make_signature("test-secret", payload)

        result = engine.handle_webhook("/webhooks/lims-ingest", payload, sig)
        assert result["status"] == "success"


class TestTriggerEngineHippoPoll:
    def test_engine_poll_hippo(self):
        trigger = _hippo_poll_trigger()
        mock_hippo = MockHippoClient(entities=[
            {
                "entity_type": "Sample",
                "external_id": "EXT-100",
                "updated_at": "2026-04-01T10:00:00Z",
                "name": "Test Sample",
            },
        ])

        engine = TriggerEngine(triggers=[trigger], hippo_client=mock_hippo)
        result = engine.poll_hippo("poll-samples")
        assert result["status"] == "success"

    def test_engine_poll_hippo_no_changes(self):
        trigger = _hippo_poll_trigger()
        engine = TriggerEngine(triggers=[trigger], hippo_client=None)
        result = engine.poll_hippo("poll-samples")
        assert result["status"] == "no_changes"


class TestTriggerEngineExisting:
    """Verify existing trigger types still work after refactoring."""

    def test_manual_trigger(self):
        trigger = TriggerConfig(
            name="manual-ingest",
            type="manual",
            action=ActionConfig(type="ingest", adapter="csv"),
        )
        engine = TriggerEngine(triggers=[trigger])
        result = engine.run_manual("manual-ingest")
        assert result["status"] == "success"
        assert result["trigger"] == "manual-ingest"

    def test_internal_event_trigger(self):
        t1 = TriggerConfig(
            name="source-trigger",
            type="manual",
            action=ActionConfig(type="ingest"),
            on_success="data_ready",
        )
        t2 = TriggerConfig(
            name="chained-trigger",
            type="internal_event",
            event="data_ready",
            action=ActionConfig(type="resolve"),
        )
        engine = TriggerEngine(triggers=[t1, t2])
        result = engine.run_manual("source-trigger")
        assert result["status"] == "success"

    def test_unknown_trigger(self):
        engine = TriggerEngine()
        with pytest.raises(TriggerError):
            engine.run_manual("does-not-exist")

    def test_parse_cron_valid(self):
        engine = TriggerEngine()
        assert engine.parse_cron("0 2 * * *") is True

    def test_parse_cron_invalid(self):
        engine = TriggerEngine()
        assert engine.parse_cron("not a cron") is False
