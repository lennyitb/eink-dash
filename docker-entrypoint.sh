#!/bin/sh
# ssh refuses keys with loose permissions; bind mounts keep the host's, so copy it.
set -e
if [ -f "${KINDLE_KEY:-/keys/kindle_dash_ed25519}" ]; then
  install -m 600 "${KINDLE_KEY:-/keys/kindle_dash_ed25519}" /tmp/kindle_key
  export KINDLE_KEY=/tmp/kindle_key
fi
exec "$@"
