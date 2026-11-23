#!/bin/sh
# DataHelix solo recipe — container entrypoint.
#
# Boot sequence (proposal §1.7 + §2.1a):
#   1. optional pull-on-boot: sync /project/schemas from SCHEMA_GIT_REMOTE
#      (Mode R), staging + migrate dry-run BEFORE touching the live schemas
#   2. migrate-if-db-exists: apply additive DDL for schema changes
#      (first boot needs no migrate — serve self-initializes the database)
#   3. write Aperture's runtime config.js (ADR-0034 pattern; defaults to the
#      same-origin /graphql seam)
#   3a. configure authentication when AUTH_MODE != none (platform ADR-0006):
#      select the gated nginx config and generate the oauth2-proxy args
#   3a′. resolve Mosaic's bind host from AUTH_MODE (or MOSAIC_BIND_HOST)
#   4. exec supervisord (nginx + mosaic serve [+ oauth2-proxy])
#
# "Restart the container" therefore means: pull (if configured) + migrate +
# serve — the restart-on-migrate model in one motion.
set -eu

PROJECT=/project

# The CLI is `mosaic` (ADR-0004 rename shipped); every certified frontier since
# 0.12.0 carries it. Deliberately not naming the current pin — that lives in
# composition.lock.json, which is gated; a version in a comment is not.
MOSAIC_BIN=mosaic
export MOSAIC_BIN

# Resolve the config file explicitly and hand it to serve via --config:
# relying on auto-discovery silently falls back to the default bundled schema
# when no config is found, so we fail loudly instead if the project has none.
if [ -f "$PROJECT/mosaic.yaml" ]; then
  MOSAIC_CONFIG="$PROJECT/mosaic.yaml"
else
  echo "solo: /project has no mosaic.yaml — bind-mount a project directory" >&2
  echo "solo: (see the recipe README; 'make init' scaffolds one)" >&2
  exit 1
fi
export MOSAIC_CONFIG

DB="$PROJECT/data/mosaic.db"
mkdir -p "$PROJECT/data" "$PROJECT/schemas"

# ── 1. Mode R: pull schemas from git before migrating ──────────────────────
if [ -n "${SCHEMA_GIT_REMOTE:-}" ]; then
  echo "solo: syncing schemas from $SCHEMA_GIT_REMOTE (${SCHEMA_GIT_REF:-default branch})"
  STAGING="$(mktemp -d)"
  trap 'rm -rf "$STAGING"' EXIT
  git init -q "$STAGING/repo"
  git -C "$STAGING/repo" remote add origin "$SCHEMA_GIT_REMOTE"
  git -C "$STAGING/repo" fetch -q --depth 1 origin "${SCHEMA_GIT_REF:-HEAD}"
  git -C "$STAGING/repo" checkout -q FETCH_HEAD
  SRC="$STAGING/repo/${SCHEMA_GIT_PATH:-schemas}"
  if [ ! -d "$SRC" ]; then
    echo "solo: ABORT — '$SCHEMA_GIT_PATH' not found in the remote (set SCHEMA_GIT_PATH)" >&2
    exit 1
  fi
  # Dry-run against the staged checkout BEFORE replacing the live schemas:
  # a failure leaves both the database and the old schema dir untouched.
  # Run with cwd = the schema dir itself so schemas using local cross-file
  # `imports:` (sibling files in the same dir) resolve — migrate resolves
  # relative imports against the process cwd, not --schema-dir.
  if [ -f "$DB" ]; then
    if ! (cd "$SRC" && "$MOSAIC_BIN" migrate --dry-run --schema-dir . --db-path "$DB"); then
      echo "solo: ABORT — staged schemas fail migration planning; live schemas untouched." >&2
      echo "solo: inspect with '$MOSAIC_BIN schema safe-deploy' against the remote checkout." >&2
      exit 1
    fi
  fi
  # Swap: replace the live schema dir contents with the staged checkout.
  find "$PROJECT/schemas" -mindepth 1 -delete
  cp -a "$SRC/." "$PROJECT/schemas/"
  echo "solo: schemas synced ($(ls "$PROJECT/schemas" | wc -l) files)"
fi

# ── 2. Migrate-if-db-exists ─────────────────────────────────────────────────
if [ -f "$DB" ]; then
  echo "solo: existing database found — applying schema migrations"
  # cwd = schemas/ itself, not /project: a schema whose tree-root file uses
  # local cross-file `imports:` (sibling files in the same schemas/ dir)
  # resolves those imports relative to the process cwd, not --schema-dir.
  (cd "$PROJECT/schemas" && "$MOSAIC_BIN" migrate --schema-dir . --db-path "$DB")
else
  echo "solo: first boot — database will be initialized by mosaic serve"
fi

# ── 3a. Authentication (platform ADR-0006) ─────────────────────────────────
# none (default) | htpasswd (testing) | oidc (production; PIV/CAC via VA SSOi).
# htpasswd and oidc differ ONLY in credential source: same proxy, same session
# cookie, same nginx wiring, same headers. Switching to SSOi is a flag change.
AUTH_MODE="${AUTH_MODE:-none}"

case "$AUTH_MODE" in
  none)
    cp /etc/datahelix/nginx.conf /etc/nginx/conf.d/solo.conf
    echo "solo: AUTH_MODE=none — no authentication (trusted network only)"
    ;;

  htpasswd|oidc)
    : "${AUTH_COOKIE_SECRET:?AUTH_MODE=$AUTH_MODE requires AUTH_COOKIE_SECRET (32 bytes, base64)}"

    # Cleartext credentials over plain HTTP are worse than the no-auth posture
    # this replaces, so refuse by default. AUTH_COOKIE_SECURE=false is the
    # explicit, deliberate override for a local test on 127.0.0.1.
    AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-true}"
    if [ "$AUTH_COOKIE_SECURE" != "true" ]; then
      echo "solo: WARNING — AUTH_COOKIE_SECURE=false: the session cookie will travel" >&2
      echo "solo: WARNING   over plain HTTP. Acceptable only for a local test." >&2
    fi

    set -- \
      --http-address=127.0.0.1:4180 \
      --reverse-proxy=true \
      --cookie-secret="$AUTH_COOKIE_SECRET" \
      --cookie-secure="$AUTH_COOKIE_SECURE" \
      --cookie-httponly=true \
      --cookie-expire="${AUTH_SESSION_MAX:-12h}" \
      --email-domain=* \
      --set-xauthrequest=true \
      --silence-ping-logging=true \
      --upstream=static://202

    if [ "$AUTH_MODE" = htpasswd ]; then
      : "${AUTH_HTPASSWD_FILE:=/etc/datahelix/auth/users.htpasswd}"
      if [ ! -f "$AUTH_HTPASSWD_FILE" ]; then
        echo "solo: ABORT — AUTH_MODE=htpasswd but $AUTH_HTPASSWD_FILE is missing." >&2
        echo "solo: create it with: htpasswd -B -c users.htpasswd <user>" >&2
        exit 1
      fi
      # The htpasswd form is the credential surface; --skip-provider-button
      # must be off or the sign-in page has nothing to render.
      # The pinned oauth2-proxy validates provider settings even when
      # htpasswd is the credential source: without a client id/secret it
      # exits 1 with "provider missing setting: client-id". These stubs
      # satisfy that check and are never reached — the htpasswd form is the
      # only credential surface, and --skip-provider-button=false is what
      # renders it.
      set -- "$@" \
        --htpasswd-file="$AUTH_HTPASSWD_FILE" \
        --display-htpasswd-form=true \
        --skip-provider-button=false \
        --client-id=htpasswd-unused \
        --client-secret=htpasswd-unused
      echo "solo: AUTH_MODE=htpasswd — username/password sign-in ($AUTH_HTPASSWD_FILE)"
    else
      : "${AUTH_OIDC_ISSUER_URL:?AUTH_MODE=oidc requires AUTH_OIDC_ISSUER_URL}"
      : "${AUTH_OIDC_CLIENT_ID:?AUTH_MODE=oidc requires AUTH_OIDC_CLIENT_ID}"
      : "${AUTH_OIDC_CLIENT_SECRET:?AUTH_MODE=oidc requires AUTH_OIDC_CLIENT_SECRET}"
      : "${AUTH_REDIRECT_URL:?AUTH_MODE=oidc requires AUTH_REDIRECT_URL (registered with the IdP, exactly)}"
      set -- "$@" \
        --skip-provider-button="${AUTH_SKIP_PROVIDER_BUTTON:-true}" \
        --provider=oidc \
        --oidc-issuer-url="$AUTH_OIDC_ISSUER_URL" \
        --client-id="$AUTH_OIDC_CLIENT_ID" \
        --client-secret="$AUTH_OIDC_CLIENT_SECRET" \
        --redirect-url="$AUTH_REDIRECT_URL" \
        --code-challenge-method=S256
      # Group-based authorization, when the IdP releases the claim. This is
      # the coarse "may you use this deployment" decision; per-record and
      # per-slot access remain Bridge's (sec6 §6.3 steps 2-3), unbuilt.
      [ -n "${AUTH_OIDC_GROUPS_CLAIM:-}" ] && set -- "$@" --oidc-groups-claim="$AUTH_OIDC_GROUPS_CLAIM"
      for group in ${AUTH_ALLOWED_GROUPS:-}; do
        set -- "$@" --allowed-group="$group"
      done
      # VA TLS inspection intercepts outbound TLS, so discovery and token
      # calls need the interception CA trusted.
      [ -n "${AUTH_PROVIDER_CA_FILE:-}" ] && set -- "$@" --provider-ca-file="$AUTH_PROVIDER_CA_FILE"
      echo "solo: AUTH_MODE=oidc — issuer $AUTH_OIDC_ISSUER_URL"
    fi

    # Written as a file so the args survive supervisord's exec without
    # another round of shell quoting. NOT under /etc/datahelix/auth — that is
    # a read-only mount point for operator-supplied secrets (the htpasswd
    # file); writing there fails the moment someone mounts it.
    mkdir -p /run/datahelix
    : > /run/datahelix/proxy.args
    for arg in "$@"; do
      printf '%s\n' "$arg" >> /run/datahelix/proxy.args
    done
    chmod 600 /run/datahelix/proxy.args  # carries the cookie secret
    cp /etc/datahelix/supervisord-auth.conf /etc/supervisor/conf.d/oauth2-proxy.conf
    cp /etc/datahelix/nginx-auth.conf /etc/nginx/conf.d/solo.conf

    # Tell the SPA where the identity endpoints are (Aperture ADR-0038).
    # Deployment-provided values win, so a bespoke proxy path still works.
    : "${VITE_AUTH_MODE:=proxy}"
    : "${VITE_AUTH_IDENTITY_URL:=/oauth2/userinfo}"
    : "${VITE_AUTH_LOGIN_URL:=/oauth2/start}"
    : "${VITE_AUTH_LOGOUT_URL:=/oauth2/sign_out}"
    export VITE_AUTH_MODE VITE_AUTH_IDENTITY_URL VITE_AUTH_LOGIN_URL VITE_AUTH_LOGOUT_URL
    ;;

  *)
    echo "solo: ABORT — AUTH_MODE='$AUTH_MODE' is not one of: none, htpasswd, oidc" >&2
    exit 1
    ;;
esac

# ── 3a′. Mosaic bind host ───────────────────────────────────────────────────
# nginx always proxies to 127.0.0.1:8001. The question is only whether
# Mosaic's raw port (8001, unproxied) is reachable from outside the container
# when it is published:
#   AUTH_MODE=none          → 0.0.0.0   (no auth boundary to bypass)
#   AUTH_MODE=htpasswd|oidc → 127.0.0.1 (8001 would bypass the proxy and the
#                                        X-DataHelix-Actor override)
# MOSAIC_BIND_HOST overrides either default. Whatever it is set to MUST still
# answer on 127.0.0.1, or nginx cannot reach Mosaic: 0.0.0.0, :: (dual-stack),
# 127.0.0.1 or localhost are fine; ::1 is IPv6-only and is rejected.
# Exported for supervisord.conf, which splits command= like a shell, so the
# value is restricted to host characters (no spaces, no %).
if [ -n "${MOSAIC_BIND_HOST:-}" ]; then
  case "$MOSAIC_BIND_HOST" in
    *[!0-9A-Za-z.:-]*)
      echo "solo: ABORT — invalid MOSAIC_BIND_HOST='$MOSAIC_BIND_HOST' (expected a host or IP)" >&2
      exit 1
      ;;
    ::1)
      echo "solo: ABORT — MOSAIC_BIND_HOST=::1 binds IPv6 only, but nginx proxies to" >&2
      echo "solo: 127.0.0.1:8001, so every route would 502. Use 127.0.0.1 (loopback)" >&2
      echo "solo: or 0.0.0.0 / :: (all interfaces) instead." >&2
      exit 1
      ;;
    127.*|localhost) loopback=yes ;;
    *) loopback=no ;;
  esac
  if [ "$AUTH_MODE" != none ] && [ "$loopback" = no ]; then
    echo "solo: WARNING ──────────────────────────────────────────────────────" >&2
    echo "solo: WARNING   MOSAIC_BIND_HOST=$MOSAIC_BIND_HOST with AUTH_MODE=$AUTH_MODE." >&2
    echo "solo: WARNING   Mosaic's port 8001 is OUTSIDE the auth boundary: anyone" >&2
    echo "solo: WARNING   who can reach it bypasses sign-in and can forge the" >&2
    echo "solo: WARNING   X-DataHelix-Actor header. Do not publish 8001 unless" >&2
    echo "solo: WARNING   something else restricts who can reach it." >&2
    echo "solo: WARNING ──────────────────────────────────────────────────────" >&2
  fi
elif [ "$AUTH_MODE" = none ]; then
  MOSAIC_BIND_HOST=0.0.0.0
else
  MOSAIC_BIND_HOST=127.0.0.1
fi
export MOSAIC_BIND_HOST
# This records the choice, not the bind: Mosaic starts later under supervisord.
echo "solo: binding Mosaic to $MOSAIC_BIND_HOST:8001 (nginx proxies via 127.0.0.1)"

# ── 3. Aperture runtime config (ADR-0034) ──────────────────────────────────
# Same vocabulary as the Aperture image's own 40-aperture-config.sh, with the
# same-origin seam as the default endpoint.
: "${VITE_GRAPHQL_URL:=/graphql}"
export VITE_GRAPHQL_URL
OUT=/srv/aperture/config.js
{
  printf 'window.__APERTURE_CONFIG__ = {'
  sep=''
  for key in VITE_GRAPHQL_URL VITE_CONTROL_PLANE_URL VITE_WORKFLOWS VITE_NAV \
             VITE_AUTH_MODE VITE_AUTH_IDENTITY_URL VITE_AUTH_LOGIN_URL VITE_AUTH_LOGOUT_URL \
             VITE_AUTH_IDENTITY_CLAIM VITE_AUTH_DISPLAY_CLAIM; do
    value=$(printenv "$key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
      printf '%s\n  "%s": "%s"' "$sep" "$key" "$escaped"
      sep=','
    fi
  done
  printf '\n};\n'
} > "$OUT"
echo "solo: aperture runtime config written (endpoint: $VITE_GRAPHQL_URL)"

# ── 4. Serve ────────────────────────────────────────────────────────────────
exec supervisord -n -c /etc/supervisor/supervisord.conf
