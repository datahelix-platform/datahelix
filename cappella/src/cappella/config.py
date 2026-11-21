import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from cappella.exceptions import ConfigError


class MosaicConfig(BaseModel):
    url: str = "http://localhost:8001"
    token: str = ""


class CanonConfig(BaseModel):
    enabled: bool = True
    url: str = "http://localhost:8002"
    mode: str = "http"  # "http" or "in_process"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class ResolutionConfig(BaseModel):
    max_concurrent_canon_calls: int = 10
    sync_threshold: int = 100
    canon_timeout_seconds: float = 30.0


class AdapterConfig(BaseModel):
    type: str
    trust_level: int = 50
    config: dict[str, Any] = Field(default_factory=dict)


class ActionConfig(BaseModel):
    type: str
    adapter: str | None = None
    entity_type: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class TriggerConfig(BaseModel):
    name: str
    type: str  # "schedule" | "manual" | "internal_event" | "webhook" | "mosaic_poll"
    action: ActionConfig
    schedule: str | None = None
    event: str | None = None
    on_success: str | None = None
    webhook: dict[str, Any] | None = None  # raw dict, converted to triggers.WebhookConfig
    mosaic_poll: dict[str, Any] | None = None  # raw dict, converted to triggers.HippoPollConfig

    def to_trigger_config(self) -> "TriggerConfig":
        """Convert to a triggers.models.TriggerConfig with typed sub-configs."""
        from cappella.triggers.models import (
            ActionConfig as TActionConfig,
            HippoPollConfig,
            TriggerConfig as TTriggerConfig,
            WebhookConfig,
        )

        webhook = WebhookConfig(**self.webhook) if self.webhook else None
        mosaic_poll = HippoPollConfig(**self.mosaic_poll) if self.mosaic_poll else None

        return TTriggerConfig(
            name=self.name,
            type=self.type,
            action=TActionConfig(
                type=self.action.type,
                adapter=self.action.adapter,
                entity_type=self.action.entity_type,
                parameters=self.action.parameters,
            ),
            schedule=self.schedule,
            event=self.event,
            on_success=self.on_success,
            webhook=webhook,
            mosaic_poll=mosaic_poll,
        )


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"  # "json" or "text"
    output: str = "stdout"


class CappellaConfig(BaseModel):
    mosaic: MosaicConfig = Field(default_factory=MosaicConfig)
    canon: CanonConfig = Field(default_factory=CanonConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    resolution: ResolutionConfig = Field(default_factory=ResolutionConfig)
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)
    triggers: list[TriggerConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _substitute_env_vars(text: str) -> str:
    """Replace ${VAR} patterns with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(r"\$\{([^}]+)\}", replacer, text)


def load_config(path: str | Path) -> CappellaConfig:
    """Load a CappellaConfig from a YAML file, substituting ${ENV_VAR} patterns."""
    path = Path(path)
    try:
        raw_text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except OSError as e:
        raise ConfigError(f"Cannot read config file: {path}", {"error": str(e)})

    substituted = _substitute_env_vars(raw_text)

    try:
        data = yaml.safe_load(substituted)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in config file: {path}", {"error": str(e)})

    if data is None:
        data = {}

    try:
        return CappellaConfig(**data)
    except Exception as e:
        raise ConfigError(f"Invalid config: {e}", {"error": str(e)})
