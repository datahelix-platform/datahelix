from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActionConfig(BaseModel):
    type: str  # "ingest" | "resolve" | "reconcile" | "notify"
    adapter: str | None = None
    entity_type: str | None = None
    parameters: dict[str, Any] = {}


class WebhookConfig(BaseModel):
    """Configuration for webhook trigger type."""

    path: str  # URL path to register, e.g. "/webhooks/lims-ingest"
    secret: str  # Shared secret for HMAC-SHA256 signature verification
    payload_mapping: dict[str, str] = {}  # Maps webhook payload fields to adapter input

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 signature of a webhook payload.

        The signature should be hex-encoded, optionally prefixed with 'sha256='.
        """
        expected = hmac.new(
            self.secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        sig = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, sig)


class HippoPollConfig(BaseModel):
    """Configuration for mosaic_poll trigger type."""

    entity_type: str  # Hippo entity type to poll
    interval: str  # Cron expression for polling interval
    filter_field: str = "updated_at"  # Field to track changes
    dedup_key: str = "external_id"  # Field used for deduplication


class TriggerConfig(BaseModel):
    name: str
    type: str  # "schedule" | "manual" | "internal_event" | "webhook" | "mosaic_poll"
    action: ActionConfig
    schedule: str | None = None  # cron expression for schedule triggers
    event: str | None = None  # event name for internal_event triggers
    on_success: str | None = None  # name of trigger to fire on success
    webhook: WebhookConfig | None = None  # config for webhook triggers
    mosaic_poll: HippoPollConfig | None = None  # config for mosaic_poll triggers


class TriggerProvenance(BaseModel):
    """Provenance record for a trigger execution."""

    trigger_name: str
    trigger_type: str
    source: str | None = None
    timestamp: str
    payload_hash: str | None = None

    @staticmethod
    def hash_payload(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()
