"""Tests for CappellaConfig loading and validation."""
import pytest

from cappella.config import (
    AdapterConfig,
    CappellaConfig,
    CanonConfig,
    MosaicConfig,
    LoggingConfig,
    ResolutionConfig,
    ServerConfig,
    TriggerConfig,
    ActionConfig,
    _substitute_env_vars,
    load_config,
)
from cappella.exceptions import ConfigError


def _write(tmp_path, content: str):
    p = tmp_path / "cappella.yaml"
    p.write_text(content)
    return p


class TestSubstituteEnvVars:
    def test_replaces_known_var(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        result = _substitute_env_vars("token: ${MY_TOKEN}")
        assert result == "token: secret123"

    def test_leaves_unknown_var_unchanged(self):
        result = _substitute_env_vars("url: ${UNKNOWN_VAR}")
        assert result == "url: ${UNKNOWN_VAR}"

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("HOST", "myhost")
        monkeypatch.setenv("PORT", "9999")
        result = _substitute_env_vars("${HOST}:${PORT}")
        assert result == "myhost:9999"

    def test_no_vars(self):
        result = _substitute_env_vars("plain text")
        assert result == "plain text"


class TestLoadConfig:
    def test_empty_yaml_gives_defaults(self, tmp_path):
        p = _write(tmp_path, "")
        cfg = load_config(p)
        assert isinstance(cfg, CappellaConfig)
        assert cfg.mosaic.url == "http://localhost:8001"

    def test_file_not_found_raises_config_error(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises_config_error(self, tmp_path):
        p = _write(tmp_path, "key: [unclosed")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(p)

    def test_hippo_url_loaded(self, tmp_path):
        p = _write(tmp_path, "mosaic:\n  url: http://mosaic.example.com\n")
        cfg = load_config(p)
        assert cfg.mosaic.url == "http://mosaic.example.com"

    def test_env_var_substitution_in_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOSAIC_TOKEN", "tok-abc")
        p = _write(tmp_path, "mosaic:\n  token: ${MOSAIC_TOKEN}\n")
        cfg = load_config(p)
        assert cfg.mosaic.token == "tok-abc"

    def test_invalid_field_raises_config_error(self, tmp_path):
        p = _write(tmp_path, "server:\n  port: not_a_number\n")
        with pytest.raises(ConfigError):
            load_config(p)


class TestMosaicConfig:
    def test_defaults(self):
        cfg = MosaicConfig()
        assert cfg.url == "http://localhost:8001"
        assert cfg.token == ""

    def test_custom_values(self):
        cfg = MosaicConfig(url="http://custom:9000", token="abc")
        assert cfg.url == "http://custom:9000"
        assert cfg.token == "abc"


class TestCanonConfig:
    def test_defaults(self):
        cfg = CanonConfig()
        assert cfg.enabled is True
        assert cfg.mode == "http"

    def test_in_process_mode(self):
        cfg = CanonConfig(mode="in_process")
        assert cfg.mode == "in_process"


class TestServerConfig:
    def test_defaults(self):
        cfg = ServerConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8000
        assert cfg.workers == 1


class TestResolutionConfig:
    def test_defaults(self):
        cfg = ResolutionConfig()
        assert cfg.max_concurrent_canon_calls == 10
        assert cfg.sync_threshold == 100
        assert cfg.canon_timeout_seconds == 30.0


class TestAdapterConfig:
    def test_type_required(self):
        cfg = AdapterConfig(type="csv")
        assert cfg.type == "csv"
        assert cfg.trust_level == 50
        assert cfg.config == {}

    def test_custom_trust_level(self):
        cfg = AdapterConfig(type="sql", trust_level=90, config={"query": "SELECT 1"})
        assert cfg.trust_level == 90


class TestLoggingConfig:
    def test_defaults(self):
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.format == "json"
        assert cfg.output == "stdout"


class TestCappellaConfig:
    def test_all_defaults(self):
        cfg = CappellaConfig()
        assert isinstance(cfg.mosaic, MosaicConfig)
        assert isinstance(cfg.canon, CanonConfig)
        assert isinstance(cfg.server, ServerConfig)
        assert isinstance(cfg.resolution, ResolutionConfig)
        assert cfg.adapters == {}
        assert cfg.triggers == []

    def test_adapter_config_nested(self, tmp_path):
        p = _write(
            tmp_path,
            "adapters:\n  my_csv:\n    type: csv\n    trust_level: 70\n",
        )
        cfg = load_config(p)
        assert "my_csv" in cfg.adapters
        assert cfg.adapters["my_csv"].type == "csv"
        assert cfg.adapters["my_csv"].trust_level == 70

    def test_trigger_config_nested(self, tmp_path):
        p = _write(
            tmp_path,
            (
                "triggers:\n"
                "  - name: daily_ingest\n"
                "    type: schedule\n"
                "    schedule: '0 6 * * *'\n"
                "    action:\n"
                "      type: ingest\n"
                "      adapter: my_csv\n"
            ),
        )
        cfg = load_config(p)
        assert len(cfg.triggers) == 1
        t = cfg.triggers[0]
        assert t.name == "daily_ingest"
        assert t.schedule == "0 6 * * *"
        assert t.action.type == "ingest"


class TestStaleHippoConfig:
    """Platform ADR-0007: pre-rename config names fail loudly and name the replacement."""

    def test_hippo_section_rejected(self, tmp_path):
        p = _write(tmp_path, "hippo:\n  url: http://h:8001\n")
        with pytest.raises(ConfigError, match="'hippo:'.*renamed to 'mosaic:'"):
            load_config(p)

    def test_hippo_poll_trigger_rejected(self, tmp_path):
        p = _write(
            tmp_path,
            "triggers:\n"
            "  - name: t\n"
            "    type: hippo_poll\n"
            "    action: {type: ingest}\n"
            "    hippo_poll: {entity_type: Sample}\n",
        )
        with pytest.raises(ConfigError, match="'hippo_poll'.*renamed to 'mosaic_poll'"):
            load_config(p)

    def test_mosaic_names_accepted(self, tmp_path):
        p = _write(
            tmp_path,
            "mosaic:\n  url: http://m:8001\n"
            "triggers:\n"
            "  - name: t\n"
            "    type: mosaic_poll\n"
            "    action: {type: ingest}\n"
            "    mosaic_poll: {entity_type: Sample}\n",
        )
        cfg = load_config(p)
        assert cfg.mosaic.url == "http://m:8001"
        assert cfg.triggers[0].type == "mosaic_poll"
