# Hippo — LinkML Runtime (the structured domain graph)

Hippo is an open-source **LinkML runtime**: point it at a LinkML schema and it *becomes* the typed, queryable **knowledge graph** that schema describes — entities, their fields, and the relationships between them. In a DataHelix deployment it is the platform's **structured domain graph**, so downstream systems, analysis pipelines, and portals can reliably locate and filter records without manually managing spreadsheets or bespoke file manifests. **Metadata tracking** — recording *where data lives* and *what it describes* — is one application it serves, not its defining essence.

Hippo is **domain-agnostic**: the entity types, fields, and relationships it tracks are defined entirely by a schema config file authored for each deployment. For example, an omics research deployment might define entity types like Subject, Sample, and Datafile, while a manufacturing deployment might define Batch, Component, and Inspection.

## Who Is Hippo For?

- **Pipeline authors** who need to resolve file paths and sample metadata at runtime from Nextflow, Snakemake, or custom scripts
- **Researchers** who want a queryable record of what data exists, where it lives, and what it describes
- **Data managers** who need to track the provenance, lifecycle, and relationships of samples and files across a project
- **Platform developers** building downstream tools that need a reliable metadata API

## When to Use Hippo

Use Hippo when you need a central metadata registry that is:

- **Queryable** — find entities by type, field values, relationships, or external identifiers
- **Auditable** — every write is versioned with full provenance; nothing is hard-deleted
- **Flexible** — define your own entity types and relationships without changing code
- **Embeddable** — use the Python SDK directly in scripts and notebooks, or run a REST API for shared access

Hippo tracks *where data lives* and *what it describes* — not the data itself. Raw data files stay in place on your filesystem or object store.

## Key Features

- **Config-driven data model** — Define entity types, fields, and relationships directly in LinkML schema
- **Graph-shaped API** — Query entities and traverse relationships through a relational store with graph semantics
- **Provenance tracking** — Every change is logged with structured context and full audit trail
- **SDK-first architecture** — Embed Hippo directly in Python scripts or notebooks; REST API is a thin transport wrapper
- **Flexible deployment** — From a single researcher's laptop (SQLite) to enterprise cloud (PostgreSQL)

## Key Concepts

| Concept | Description |
|---|---|
| **Entity** | A top-level object tracked by Hippo. Entity types are defined in your schema config (e.g., Subject, Sample, Datafile). |
| **Schema config** | A YAML file defining entity types, fields, and relationships for your deployment, authored directly in LinkML format. |
| **Relationship** | A directional, typed edge connecting two entities with cardinality constraints. |
| **External ID** | An identifier from an upstream system (e.g., LIMS barcode) mapped to a Hippo entity UUID. |
| **Provenance record** | An immutable log entry recording what changed, when, and by whom. |
| **Availability** | Entities are never hard-deleted. Instead, they transition through lifecycle states: `active`, `archived`, `superseded`, `deleted`. |

## Architecture Overview

Hippo has three concentric layers — only the Core SDK is required:

```
┌─────────────────────────────────────────────────┐
│            Transport Layer (optional)            │
│       REST (FastAPI)  ·  GraphQL (future)        │
├─────────────────────────────────────────────────┤
│               Core Python SDK                    │
│  HippoClient · QueryEngine · IngestionPipeline  │
│  ProvenanceManager · SchemaConfig                │
├─────────────────────────────────────────────────┤
│         Infrastructure Layer (adapters)          │
│    SQLite (v0.1)  ·  PostgreSQL (future)         │
└─────────────────────────────────────────────────┘
```

All business logic lives in the **Core SDK**. The REST API is a thin wrapper — you can embed Hippo directly in Python code without running a server.

## Deployment Options

| Tier | How it works | Typical use |
|---|---|---|
| **Local / single-user** | `pip install datahelix-mosaic`, point at a SQLite file, query from Python or a notebook. No server required. | Individual researcher, exploratory analysis |
| **Small team** | Run `mosaic serve` on a shared host backed by SQLite or PostgreSQL. | Lab group, shared project |
| **Enterprise / cloud** | Deploy with a managed PostgreSQL backend, container orchestration, and Bridge for authentication. | Production platform, multi-team environment |

## Getting Started

```bash
pip install datahelix-mosaic
mosaic init my-project
mosaic serve
```

See the **[Quick Start guide](docs/quickstart.md)** for a complete walkthrough — from schema definition through entity creation, querying, and provenance inspection.

## Related Components

- [Cappella](../cappella/index.md) — Harmonizes data from external sources and upserts into Hippo
- [Canon](../canon/index.md) — Resolves computational artifacts registered in Hippo
- [Aperture](../aperture/index.md) — User-facing CLI and web interface for browsing Hippo entities
- [Bridge](../bridge/index.md) — Adds authentication and unified API gateway for multi-user deployments

## User Documentation

- [Introduction](docs/introduction.md) — Detailed overview and use cases
- [Installation](docs/installation.md) — Setup instructions
- [Quick Start](docs/quickstart.md) — Get running in minutes
- [Schema Guide](docs/schema-guide.md) — Authoring entity schemas in LinkML
- [Data Model](docs/data-model.md) — Core data model concepts
- [Configuration](docs/configuration.md) — Configuration reference
- [CLI Reference](docs/cli-reference.md) — Command-line interface
- [API Reference](docs/api-reference.md) — REST API endpoints

## Design Specification

- [Overview & Scope](design/sec1_overview.md)
- [Architecture](design/sec2_architecture.md)
- [Data Model](design/sec3_data_model.md)
- [Relational Storage Mapping](design/sec3b_relational_storage.md)
- [API Layer](design/sec4_api_layer.md)
- [Ingestion & Integration](design/sec5_ingestion.md)
- [Provenance & Audit](design/sec6_provenance.md)
- [Non-Functional Requirements](design/sec7_nfr.md)
- [Auth Integration](design/sec8_auth_integration.md)
- [Appendix A: Example Schema (Omics)](design/appendix_a_example_schema_omics.md)
- [Appendix B: Implementation Guide](design/appendix_b_implementation_guide.md)
- [Reference: mosaic.yaml Config](design/reference_mosaic_yaml.md)
- [Reference: validators.yaml](design/reference_validators_yaml.md)
- [Reference: CEL Context](design/reference_cel_context.md)
