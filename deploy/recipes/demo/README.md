# DataHelix `demo` — populated single-container showcase

The `solo` recipe with a **large synthetic brain-bank dataset baked into the
image**. Boots straight into a populated Aperture explorer — no setup, no
ingest step, nothing to configure. Built for demos, screenshots, and kicking
the tyres on the platform.

```bash
cd deploy/recipes/demo
make up            # builds (generates + bakes the dataset) and starts
make check-reverses  # every reverse edge matches its forward slot on the baked data
open http://localhost:8080
```

> Same posture as `solo`: **no auth**, single-user, localhost/trusted-network
> only. The dataset is **synthetic** — realistic in shape, not in meaning
> (`linkml-data-gen` fills values to satisfy the schema's types/patterns, not
> real clinical semantics) — and **immutable** (there is no schema-editing or
> ingest surface; rebuild the image to change the data).

## What's inside

At build time, a data stage running **inside the pinned Mosaic/Hippo image**:

1. installs [`linkml-data-gen`](https://github.com/datahelix-platform/linkml-data-gen)
   (pinned) and clones
   [`brainbank-hippo-schema`](https://github.com/VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema)
   (pinned);
2. generates a connected, referentially-consistent dataset from the schema's
   tree-root (`brainbank.yaml`);
3. remaps the bundle's top-level keys to Mosaic's ingest accessors (schema-
   driven, via the image's own `linkml_bridge` — see `remap_accessors.py`);
4. ingests it into a SQLite `data/mosaic.db`.

That database is copied into the final image, which is otherwise the `solo`
runtime (nginx + `mosaic serve --graphql`, same-origin `/graphql` seam). The DB
is built by the exact runtime version that serves it, so there is no version
skew.

## Tuning the dataset

Scale and seed are build args — rebuild to change them:

```bash
DEMO_COUNTS="donors=2000 samples=12000 datasets=3000 assays=3000 processes=1500 analyses=800" \
DEMO_SEED=1 make up
```

`DEMO_COUNTS` is `linkml-data-gen --count-for` syntax (per-collection counts).
Generation is deterministic for a fixed `DEMO_SEED`, so a given
counts+seed pair always bakes a byte-identical dataset. Larger datasets mean a
longer build and a bigger image.

## Certification

Same as `solo`: built FROM the digest-pinned certified pair; `make check-pins`
enforces the Dockerfile pins match `certification/composition.lock.json`;
`make gate` is the ADR-0001 deploy pre-flight. The data generator and schema
are pinned separately (they are build inputs, not runtime components).

## Limitations

- Synthetic data (see banner); dynamic-enum CURIEs are shape-valid but not
  checked against live ontologies.
- Immutable dataset — no `mosaic migrate` loop (use `solo`/`ide` for that).
- No Modeler (nothing to edit); no auth (see banner).
