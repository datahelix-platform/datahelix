# Installation

## Requirements

- Python 3.11+
- A running [Hippo](../../hippo/README.md) instance (v0.3.1+)
- (Optional) A running [Canon](../../canon/README.md) instance (v0.1+) for artifact resolution

## Install

```bash
pip install cappella
```

For SQL adapter support (PostgreSQL, MySQL, SQLite):
```bash
pip install cappella[sql]
```

For development and testing:
```bash
pip install cappella[dev]
```

## Verify Installation

```bash
cappella --version
cappella --help
```

## Configure

Create a `cappella.yaml` configuration file. At minimum you need a Hippo connection:

```yaml
mosaic:
  url: "http://localhost:8001"
  token: "${MOSAIC_TOKEN}"
```

See the [Quick Start](quickstart.md) for a minimal working example, or the [User Guide](user_guide.md) for the full configuration reference.

## Run as a Service

```bash
cappella serve --config cappella.yaml
```

The REST API will be available at `http://localhost:8000` by default.

## Run as a CLI Tool

All Cappella operations are also available as CLI commands without starting a server:

```bash
cappella ingest <adapter_name> --config cappella.yaml
cappella resolve --entity-type GeneCounts --criteria "donor.diagnosis=CTE" --config cappella.yaml
cappella status --config cappella.yaml
cappella --help
```

## Verify Connection

```bash
cappella status --config cappella.yaml
```

Expected output:
```json
{
  "cappella_version": "0.1.0",
  "mosaic": {"status": "ok", "version": "0.3.1"},
  "canon": {"status": "ok", "version": "0.2.0"},
  "adapters": {}
}
```
