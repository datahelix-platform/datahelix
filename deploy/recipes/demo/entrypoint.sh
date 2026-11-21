#!/bin/sh
# DataHelix demo recipe — entrypoint. The dataset is baked into the image, so
# there is no migrate/pull loop: resolve the config, write Aperture's runtime
# config (same-origin /graphql), and serve.
set -eu

PROJECT=/project

MOSAIC_BIN=mosaic
export MOSAIC_BIN

if [ -f "$PROJECT/mosaic.yaml" ]; then
  MOSAIC_CONFIG="$PROJECT/mosaic.yaml"
else
  echo "demo: /project has no mosaic.yaml — image build is broken" >&2
  exit 1
fi
export MOSAIC_CONFIG

: "${VITE_GRAPHQL_URL:=/graphql}"
export VITE_GRAPHQL_URL
OUT=/srv/aperture/config.js
{
  printf 'window.__APERTURE_CONFIG__ = {'
  sep=''
  for key in VITE_GRAPHQL_URL VITE_CONTROL_PLANE_URL VITE_WORKFLOWS VITE_NAV; do
    value=$(printenv "$key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
      printf '%s\n  "%s": "%s"' "$sep" "$key" "$escaped"
      sep=','
    fi
  done
  printf '\n};\n'
} > "$OUT"
echo "demo: aperture runtime config written (endpoint: $VITE_GRAPHQL_URL)"

exec supervisord -n -c /etc/supervisor/supervisord.conf
