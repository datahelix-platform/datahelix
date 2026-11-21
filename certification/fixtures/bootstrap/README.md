# Bootstrap fixture package (v2.0.0)

The single versioned source of the seed **schema**, seed **data**, and the
Aperture **control-plane document recipe** used to boot a certification
composition. See [`manifest.yaml`](./manifest.yaml) for the machine-readable
inventory and [platform ADR-0001](../../../platform/design/decisions/ADR-0001-certified-frontier-composition.md)
for why it exists.

## Contents

| Path | What it is |
|---|---|
| `VERSION` | Fixture package version — part of every ledger entry's triple (`fixture_version`). |
| `schema/portal_schema.yaml` | Generic library-catalog domain (Book/Author/Review). Mosaic autogenerates GraphQL from it. |
| `schema/aperture_control_plane.yaml` | `ApertureDocument` recipe — the `{kind,name,payload}` control-plane store (Aperture ADR-0032). |
| `data/seed.yaml` | Idempotent tree-root bundle (identity by `id`). |
| `manifest.yaml` | Inventory, seeding commands, and the product-loop → fixture map. |

## Why a generic domain

Aperture's source carries no domain nouns (Aperture ADR-0002) and derives every
capability from Mosaic's introspection (formerly Hippo, ADR-0004). A neutral
catalog domain (mirroring Aperture's own `capableSchema()` test fixture)
exercises the four seams — introspection enrichment, filter SDL, the batch
unit-of-work, and the control-plane document type — without smuggling in
deployment specifics.

## Seeding a fresh Mosaic

```bash
# from this directory, against a Mosaic checkout/serve using these schemas
mosaic ingest --file data/seed.yaml --validate-schema schema/
```

REST (`POST /ingest`) and GraphQL (`ingestBatch`) seeding paths are documented
in `manifest.yaml` for eras/backends where the CLI bundle path differs.

## Versioning

Bumping any file here is a **suite change**: bump `VERSION`, and the next
certification records the new `fixture_version` in its ledger entry. Old ledger
entries keep the fixture version they were certified against — they are never
re-tested (facts about immutable inputs; ADR-0001).

> **Maintenance lines freeze their fixture.** A DataHelix maintenance branch
> (`release/lts-*`) pins the era-appropriate fixture version alongside its
> submodule pins; the `main` fixture may assert newer-only behavior and must not
> be used to certify an older line.
