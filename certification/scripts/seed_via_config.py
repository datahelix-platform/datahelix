"""Seed the certification fixture through mosaic's config-driven factory.

Runs INSIDE the pinned mosaic container (piped to ``python -`` by
run_composition.sh). ``mosaic ingest`` cannot be used here: the CLI builds its
client directly (SQLite default) and never reads ``/app/mosaic.yaml``, so it
would write to a throwaway SQLite file instead of the postgres deployment
that ``mosaic serve`` is reading. This wires the same ingest function to the
same config the server booted with.
"""

import sys

from mosaic.cli.commands.ingest import ingest_linkml_yaml
from mosaic.config import load_mosaic_config as load_config
from mosaic.core.factory import build_schema_registry, create_client_from_config

CONFIG = "/app/mosaic.yaml"
SEED = "/app/seed/seed.yaml"

cfg = load_config(CONFIG)
client = create_client_from_config(cfg)
registry = build_schema_registry(cfg.schema_path, merge_requires=True)

result = ingest_linkml_yaml(SEED, client, registry)
print(
    f"seeded {SEED}: created={result.created} "
    f"updated={result.updated} errors={result.errors}"
)
for message in result.error_messages:
    print(f"  - {message}", file=sys.stderr)
sys.exit(1 if result.errors else 0)
