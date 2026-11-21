import threading
from datetime import datetime
from typing import Any, Callable

from cappella.exceptions import TriggerError
from cappella.ingest import audit
from cappella.triggers.models import (
    HippoPollConfig,
    TriggerConfig,
    TriggerProvenance,
    WebhookConfig,
)


class InternalEventBus:
    """Simple synchronous event bus with cycle detection."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = {}
        self._emitting: set[str] = set()

    def subscribe(self, event: str, handler: Callable) -> None:
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(handler)

    def emit(self, event: str, payload: dict | None = None) -> None:
        if event in self._emitting:
            raise TriggerError(
                f"InternalEventBus: cycle detected for event '{event}'",
                {"event": event},
            )

        self._emitting.add(event)
        try:
            handlers = self._subscribers.get(event, [])
            for handler in handlers:
                handler(event, payload or {})
        finally:
            self._emitting.discard(event)

    def has_subscribers(self, event: str) -> bool:
        return bool(self._subscribers.get(event))


class HippoPollState:
    """Tracks state for mosaic_poll triggers to enable deduplication."""

    def __init__(self) -> None:
        self._last_seen: dict[str, str] = {}  # trigger_name -> last seen timestamp
        self._processed: dict[str, set[str]] = {}  # trigger_name -> set of dedup keys

    def get_last_seen(self, trigger_name: str) -> str | None:
        return self._last_seen.get(trigger_name)

    def set_last_seen(self, trigger_name: str, timestamp: str) -> None:
        self._last_seen[trigger_name] = timestamp

    def is_processed(self, trigger_name: str, dedup_key: str) -> bool:
        return dedup_key in self._processed.get(trigger_name, set())

    def mark_processed(self, trigger_name: str, dedup_key: str) -> None:
        if trigger_name not in self._processed:
            self._processed[trigger_name] = set()
        self._processed[trigger_name].add(dedup_key)

    def reset(self, trigger_name: str) -> None:
        self._last_seen.pop(trigger_name, None)
        self._processed.pop(trigger_name, None)


class TriggerExecutor:
    """Executes trigger actions synchronously."""

    def __init__(
        self,
        triggers: dict[str, TriggerConfig],
        event_bus: InternalEventBus | None = None,
    ) -> None:
        self._triggers = triggers
        self._event_bus = event_bus

    def run(self, trigger_name: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a trigger by name. Returns result dict.

        Args:
            trigger_name: Name of the trigger to execute.
            context: Optional context dict (e.g. webhook payload, poll results).
        """
        if trigger_name not in self._triggers:
            raise TriggerError(
                f"TriggerExecutor: unknown trigger '{trigger_name}'",
                {"trigger": trigger_name},
            )

        trigger = self._triggers[trigger_name]
        audit.emit_event("trigger_fired", trigger=trigger_name, action=trigger.action.type)

        try:
            result = self._execute_action(trigger, context)
            if trigger.on_success and self._event_bus:
                try:
                    self._event_bus.emit(trigger.on_success)
                except TriggerError:
                    pass
            return {"status": "success", "trigger": trigger_name, "result": result}
        except Exception as e:
            audit.emit_event("trigger_failed", trigger=trigger_name, error=str(e))
            raise TriggerError(
                f"TriggerExecutor: trigger '{trigger_name}' failed: {e}",
                {"trigger": trigger_name, "error": str(e)},
            )

    def _execute_action(
        self, trigger: TriggerConfig, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        action = trigger.action
        result: dict[str, Any] = {
            "action_type": action.type,
            "adapter": action.adapter,
            "entity_type": action.entity_type,
            "executed_at": datetime.utcnow().isoformat() + "Z",
        }
        if context:
            result["trigger_context"] = context
        return result


class WebhookHandler:
    """Handles incoming webhook requests and dispatches to the trigger engine."""

    def __init__(
        self,
        triggers: dict[str, TriggerConfig],
        executor: TriggerExecutor,
    ) -> None:
        self._triggers = triggers
        self._executor = executor
        self._path_map: dict[str, str] = {}  # path -> trigger_name
        self._rebuild_path_map()

    def _rebuild_path_map(self) -> None:
        self._path_map.clear()
        for name, trigger in self._triggers.items():
            if trigger.type == "webhook" and trigger.webhook:
                self._path_map[trigger.webhook.path] = name

    def register_trigger(self, trigger: TriggerConfig) -> None:
        if trigger.type == "webhook" and trigger.webhook:
            self._path_map[trigger.webhook.path] = trigger.name

    def get_trigger_for_path(self, path: str) -> TriggerConfig | None:
        name = self._path_map.get(path)
        if name:
            return self._triggers.get(name)
        return None

    def handle_webhook(
        self, path: str, payload: bytes, signature: str
    ) -> dict[str, Any]:
        """Process an incoming webhook request.

        Args:
            path: The webhook URL path.
            payload: Raw request body bytes.
            signature: The HMAC-SHA256 signature from the request header.

        Returns:
            Result dict from trigger execution.

        Raises:
            TriggerError: If path is unknown, signature is invalid, or execution fails.
        """
        trigger = self.get_trigger_for_path(path)
        if trigger is None:
            raise TriggerError(
                f"WebhookHandler: no trigger registered for path '{path}'",
                {"path": path},
            )

        if trigger.webhook is None:
            raise TriggerError(
                f"WebhookHandler: trigger '{trigger.name}' has no webhook config",
                {"trigger": trigger.name},
            )

        if not trigger.webhook.verify_signature(payload, signature):
            raise TriggerError(
                f"WebhookHandler: invalid signature for trigger '{trigger.name}'",
                {"trigger": trigger.name, "path": path},
            )

        provenance = TriggerProvenance(
            trigger_name=trigger.name,
            trigger_type="webhook",
            source=path,
            timestamp=datetime.utcnow().isoformat() + "Z",
            payload_hash=TriggerProvenance.hash_payload(payload),
        )

        import json

        try:
            parsed_payload = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed_payload = {}

        # Apply payload mapping if configured
        mapped_input = parsed_payload
        if trigger.webhook.payload_mapping:
            mapped_input = {}
            for target_key, source_key in trigger.webhook.payload_mapping.items():
                if source_key in parsed_payload:
                    mapped_input[target_key] = parsed_payload[source_key]

        context = {
            "webhook_payload": mapped_input,
            "provenance": provenance.model_dump(),
        }

        audit.emit_event(
            "webhook_received",
            trigger=trigger.name,
            path=path,
            payload_hash=provenance.payload_hash,
        )

        return self._executor.run(trigger.name, context=context)


class HippoPollHandler:
    """Handles mosaic_poll triggers by polling Hippo for changed entities."""

    def __init__(
        self,
        triggers: dict[str, TriggerConfig],
        executor: TriggerExecutor,
        hippo_client: Any = None,
    ) -> None:
        self._triggers = triggers
        self._executor = executor
        self._hippo_client = hippo_client
        self._state = HippoPollState()

    @property
    def state(self) -> HippoPollState:
        return self._state

    def poll(self, trigger_name: str) -> dict[str, Any]:
        """Execute a single poll cycle for a mosaic_poll trigger.

        Returns:
            Result dict with poll results and trigger execution outcome.
        """
        if trigger_name not in self._triggers:
            raise TriggerError(
                f"HippoPollHandler: unknown trigger '{trigger_name}'",
                {"trigger": trigger_name},
            )

        trigger = self._triggers[trigger_name]
        if trigger.type != "mosaic_poll" or trigger.mosaic_poll is None:
            raise TriggerError(
                f"HippoPollHandler: trigger '{trigger_name}' is not a mosaic_poll trigger",
                {"trigger": trigger_name},
            )

        poll_config = trigger.mosaic_poll
        last_seen = self._state.get_last_seen(trigger_name)

        # Query Hippo for changed entities
        changed_entities = self._fetch_changed_entities(
            poll_config, since=last_seen
        )

        # Deduplicate
        new_entities = []
        for entity in changed_entities:
            dedup_value = entity.get(poll_config.dedup_key, "")
            if dedup_value and not self._state.is_processed(trigger_name, dedup_value):
                new_entities.append(entity)
                self._state.mark_processed(trigger_name, dedup_value)

        # Update last-seen timestamp
        if new_entities:
            latest_ts = max(
                e.get(poll_config.filter_field, "") for e in new_entities
            )
            if latest_ts:
                self._state.set_last_seen(trigger_name, latest_ts)

        provenance = TriggerProvenance(
            trigger_name=trigger_name,
            trigger_type="mosaic_poll",
            source=f"mosaic:{poll_config.entity_type}",
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

        context = {
            "poll_results": new_entities,
            "entity_type": poll_config.entity_type,
            "total_changed": len(changed_entities),
            "new_count": len(new_entities),
            "provenance": provenance.model_dump(),
        }

        audit.emit_event(
            "mosaic_poll_executed",
            trigger=trigger_name,
            entity_type=poll_config.entity_type,
            total_changed=len(changed_entities),
            new_count=len(new_entities),
        )

        if new_entities:
            return self._executor.run(trigger_name, context=context)

        return {
            "status": "no_changes",
            "trigger": trigger_name,
            "result": context,
        }

    def _fetch_changed_entities(
        self, config: HippoPollConfig, since: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch entities from Hippo that changed since the given timestamp."""
        if self._hippo_client is None:
            return []

        params: dict[str, Any] = {"entity_type": config.entity_type}
        if since:
            params["filter"] = {config.filter_field: {"$gt": since}}

        if hasattr(self._hippo_client, "query_entities"):
            return self._hippo_client.query_entities(**params)

        return []


class TriggerEngine:
    """Manages trigger scheduling and execution."""

    def __init__(
        self,
        triggers: list[TriggerConfig] | None = None,
        hippo_client: Any = None,
    ) -> None:
        self._triggers: dict[str, TriggerConfig] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._event_bus = InternalEventBus()

        if triggers:
            for t in triggers:
                self._triggers[t.name] = t
                if t.type == "internal_event" and t.event:
                    self._event_bus.subscribe(
                        t.event,
                        lambda event, payload, tr=t: self._executor.run(tr.name),
                    )

        self._executor = TriggerExecutor(self._triggers, self._event_bus)
        self._webhook_handler = WebhookHandler(self._triggers, self._executor)
        self._hippo_poll_handler = HippoPollHandler(
            self._triggers, self._executor, hippo_client
        )

    def add_trigger(self, trigger: TriggerConfig) -> None:
        self._triggers[trigger.name] = trigger
        if trigger.type == "internal_event" and trigger.event:
            self._event_bus.subscribe(
                trigger.event,
                lambda event, payload, t=trigger: self._executor.run(t.name),
            )
        if trigger.type == "webhook":
            self._webhook_handler.register_trigger(trigger)

    def schedule_trigger(self, trigger_name: str) -> None:
        """Schedule a trigger to run based on its cron expression."""
        if trigger_name not in self._triggers:
            raise TriggerError(f"Unknown trigger: '{trigger_name}'")

        trigger = self._triggers[trigger_name]
        if trigger.type == "mosaic_poll" and trigger.mosaic_poll:
            self._schedule_next(trigger_name, trigger.mosaic_poll.interval)
            return

        if trigger.type != "schedule" or not trigger.schedule:
            raise TriggerError(f"Trigger '{trigger_name}' is not a schedule trigger")

        self._schedule_next(trigger_name, trigger.schedule)

    def _schedule_next(self, trigger_name: str, cron_expr: str) -> None:
        try:
            from croniter import croniter
            now = datetime.utcnow()
            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            delay = (next_run - now).total_seconds()
            delay = max(0, delay)
        except Exception as e:
            raise TriggerError(f"Invalid cron expression '{cron_expr}': {e}")

        trigger = self._triggers[trigger_name]

        def _run() -> None:
            try:
                if trigger.type == "mosaic_poll":
                    self._hippo_poll_handler.poll(trigger_name)
                else:
                    self._executor.run(trigger_name)
            except Exception:
                pass
            # Reschedule
            self._schedule_next(trigger_name, cron_expr)

        timer = threading.Timer(delay, _run)
        timer.daemon = True
        self._timers[trigger_name] = timer
        timer.start()

    def cancel_trigger(self, trigger_name: str) -> None:
        if trigger_name in self._timers:
            self._timers[trigger_name].cancel()
            del self._timers[trigger_name]

    def run_manual(self, trigger_name: str) -> dict[str, Any]:
        """Execute a trigger manually."""
        return self._executor.run(trigger_name)

    def handle_webhook(
        self, path: str, payload: bytes, signature: str
    ) -> dict[str, Any]:
        """Handle an incoming webhook request."""
        return self._webhook_handler.handle_webhook(path, payload, signature)

    def poll_hippo(self, trigger_name: str) -> dict[str, Any]:
        """Execute a mosaic_poll trigger manually."""
        return self._hippo_poll_handler.poll(trigger_name)

    def emit_event(self, event: str, payload: dict | None = None) -> None:
        """Emit an internal event."""
        self._event_bus.emit(event, payload)

    def get_event_bus(self) -> InternalEventBus:
        return self._event_bus

    def get_webhook_handler(self) -> WebhookHandler:
        return self._webhook_handler

    def get_hippo_poll_handler(self) -> HippoPollHandler:
        return self._hippo_poll_handler

    def parse_cron(self, cron_expr: str) -> bool:
        """Validate a cron expression. Returns True if valid."""
        try:
            from croniter import croniter
            return croniter.is_valid(cron_expr)
        except Exception:
            return False
