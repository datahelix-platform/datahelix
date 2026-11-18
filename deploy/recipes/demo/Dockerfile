# DataHelix `demo` recipe — solo, with a large synthetic brain-bank dataset
# baked into the image. Boots instantly into a populated Aperture explorer.
#
# Built FROM the digest-pinned certified pair (platform ADR-0001), same as the
# solo recipe — check_pins.py enforces the pins match composition.lock.json.
# The dataset is generated at build time by linkml-data-gen against the real
# brainbank-hippo-schema, INSIDE the pinned image, so the SQLite DB is created
# by the exact runtime version that serves it (no version skew).
#
# This is a demo artifact: the dataset is synthetic (realistic in shape, not in
# meaning) and the data is immutable — there is no schema-iteration loop and no
# auth (see the solo recipe's banner; run on localhost / trusted network).

ARG MOSAIC_IMAGE=ghcr.io/datahelix-platform/mosaic@sha256:27ea806f7cb61bd0217b8b247996196cfb4b6241aa9a06800779484c776d87ed
ARG APERTURE_IMAGE=ghcr.io/bu-neuromics/aperture@sha256:dbe6d7b8b8657e27f79f04e9a7b987df7b32813a3bb5f43b21dcbd11a8c805f6

# Data generator (pinned; carries the global-id-uniqueness fix,
# datahelix-platform/linkml-data-gen#3) and the domain schema (pinned).
ARG DATAGEN_REPO=https://github.com/datahelix-platform/linkml-data-gen.git
# Pinned to the squashed global-id-uniqueness commit (linkml-data-gen#3).
ARG DATAGEN_REF=6d1386f75e400f5e659ff5d7c810adb1914b7131
ARG SCHEMA_REPO=https://github.com/VA-NCPTSDBB-Bioinformatics/brainbank-hippo-schema.git
ARG SCHEMA_REF=05c58aa78939a5b9bbcb4d0a3d901a3eab3ca67f

FROM ${APERTURE_IMAGE} AS aperture

# ── Data-build stage: generate + ingest inside the pinned runtime ───────────
FROM ${MOSAIC_IMAGE} AS data
USER root
ARG DATAGEN_REPO
ARG DATAGEN_REF
ARG SCHEMA_REPO
ARG SCHEMA_REF
ARG DEMO_SEED=0
# Space-separated per-collection counts (linkml-data-gen --count-for syntax).
ARG DEMO_COUNTS="donors=500 samples=3000 datasets=800 assays=800 processes=400 analyses=200"

RUN if command -v apt-get >/dev/null; then \
      apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /build
RUN pip install --no-cache-dir "git+${DATAGEN_REPO}@${DATAGEN_REF}"
RUN git clone --depth 1 "${SCHEMA_REPO}" brainbank-hippo-schema \
    && git -C brainbank-hippo-schema fetch --depth 1 origin "${SCHEMA_REF}" \
    && git -C brainbank-hippo-schema checkout -q FETCH_HEAD
COPY remap_accessors.py build-dataset.sh /build/
RUN chmod +x build-dataset.sh \
    && DEMO_SEED="${DEMO_SEED}" DEMO_COUNTS="${DEMO_COUNTS}" ./build-dataset.sh

# ── Final stage: solo runtime, dataset baked in ─────────────────────────────
FROM ${MOSAIC_IMAGE}
ARG MOSAIC_IMAGE
ARG APERTURE_IMAGE
ARG SCHEMA_REF
ARG VERSION=dev
ARG REVISION=unknown

LABEL org.opencontainers.image.title="datahelix-demo" \
      org.opencontainers.image.description="DataHelix demo — Aperture + Mosaic with a pre-loaded synthetic brain-bank dataset" \
      org.opencontainers.image.source="https://github.com/datahelix-platform/datahelix" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.datahelix.solo.mosaic-image="${MOSAIC_IMAGE}" \
      org.datahelix.solo.aperture-image="${APERTURE_IMAGE}" \
      org.datahelix.demo.schema-ref="${SCHEMA_REF}"

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default

COPY --from=aperture /usr/share/nginx/html /srv/aperture
# The baked project: schemas/, mosaic.yaml, and the pre-loaded data/mosaic.db.
COPY --from=data /project /project

COPY nginx.conf /etc/nginx/conf.d/demo.conf
COPY supervisord.conf /etc/supervisor/conf.d/demo.conf
COPY entrypoint.sh /usr/local/bin/demo-entrypoint
RUN chmod +x /usr/local/bin/demo-entrypoint

WORKDIR /project
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

ENTRYPOINT ["/usr/local/bin/demo-entrypoint"]
