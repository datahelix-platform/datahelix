# DataHelix `solo` recipe — single-container production MVP.
#
# One container, one published port: nginx fronts the Aperture SPA (/) and
# reverse-proxies the data plane (/graphql, /docs, /health) to
# `mosaic serve --graphql` on SQLite. Process supervision via supervisord;
# the entrypoint runs the migrate-on-boot step first.
#
# The LinkML Modeler and its cors-proxy sidecar were removed by platform
# ADR-0005: not wired into anything, the only from-source build in a
# production recipe (an exception to decision 1.4), and the last pin on EOL
# Node 20. There is now no Node in this image at all.
# See README.md and proposals/deployment-recipes.md (§2.1).
#
# Built FROM the published, digest-pinned certified pair (platform ADR-0001,
# proposal decision 1.4/§4.4 middle path): the pins below MUST match
# certification/composition.lock.json — CI enforces this via check_pins.py,
# and the digests are recorded as OCI labels so a deploy gate can verify the
# bundle's provenance. Never build components from source in this recipe.
#
# NOTE: the ARGs below are the authoritative pins and are checked against
# certification/composition.lock.json by `check_pins.py`, which `make gate`
# runs before this image can come up. Do not name a version here — a comment
# cannot be gated, and the previous one sat three releases stale (Mosaic
# 0.12.1) without anything noticing. The CLI inside the image is `mosaic`
# (ADR-0004 rename shipped).

ARG MOSAIC_IMAGE=ghcr.io/datahelix-platform/mosaic@sha256:27ea806f7cb61bd0217b8b247996196cfb4b6241aa9a06800779484c776d87ed
ARG APERTURE_IMAGE=ghcr.io/bu-neuromics/aperture@sha256:dbe6d7b8b8657e27f79f04e9a7b987df7b32813a3bb5f43b21dcbd11a8c805f6

# The authenticating proxy (platform ADR-0006). Digest-pinned like the pair
# above, but NOT part of the certified frontier: it is infrastructure, not a
# DataHelix component, and ADR-0001's ledger governs component composition.
# v7.13.0, multi-arch (amd64 + arm64), verified against the quay.io index.
# Inert unless AUTH_MODE != none — the entrypoint decides whether to start it.
# GovCloud/air-gapped deployments must mirror this into their own registry.
ARG OAUTH2_PROXY_IMAGE=quay.io/oauth2-proxy/oauth2-proxy@sha256:56e3daedf765c7a1eea6e366fbe684be7d3084830ade14b6174570d3c7960954

FROM ${APERTURE_IMAGE} AS aperture

FROM ${OAUTH2_PROXY_IMAGE} AS oauth2-proxy

# ── Final stage: the bundle ─────────────────────────────────────────────────
FROM ${MOSAIC_IMAGE}

ARG MOSAIC_IMAGE
ARG APERTURE_IMAGE
ARG OAUTH2_PROXY_IMAGE
ARG VERSION=dev
ARG REVISION=unknown

# Inner-pair provenance: a deploy gate can read these labels and verify the
# pair against the certification ledger (proposal §4.4).
LABEL org.opencontainers.image.title="datahelix-solo" \
      org.opencontainers.image.description="DataHelix solo recipe — Aperture + Mosaic, single container, SQLite" \
      org.opencontainers.image.source="https://github.com/datahelix-platform/datahelix" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.datahelix.solo.mosaic-image="${MOSAIC_IMAGE}" \
      org.datahelix.solo.aperture-image="${APERTURE_IMAGE}" \
      org.datahelix.solo.oauth2-proxy-image="${OAUTH2_PROXY_IMAGE}"

USER root

# git: Mode R schema pull-on-boot (entrypoint.sh). libstdc++6 is gone with the
# node binary it supported.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor git \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default

# Static bundle
COPY --from=aperture /usr/share/nginx/html /srv/aperture

# The authenticating proxy binary (platform ADR-0006). Present always, run
# only when AUTH_MODE != none.
COPY --from=oauth2-proxy /bin/oauth2-proxy /usr/local/bin/oauth2-proxy

# nginx and supervisor configs are STAGED, not installed: the entrypoint picks
# the gated or ungated variant from AUTH_MODE at container start (ADR-0006).
COPY nginx.conf nginx-auth.conf supervisord-auth.conf /etc/datahelix/
COPY supervisord.conf /etc/supervisor/conf.d/solo.conf
COPY entrypoint.sh /usr/local/bin/solo-entrypoint
RUN chmod +x /usr/local/bin/solo-entrypoint && mkdir -p /project /etc/datahelix/auth /run/datahelix

WORKDIR /project
EXPOSE 8080

# Healthy = nginx is up AND the data plane behind it answers. /health is
# exempt from auth_request in both nginx variants, so this works in every mode.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

ENTRYPOINT ["/usr/local/bin/solo-entrypoint"]
