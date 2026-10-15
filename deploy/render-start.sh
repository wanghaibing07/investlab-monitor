#!/bin/sh
# Public demonstration only; does not import personal account data.
set -eu
: "${INVESTLAB_HOME:=/tmp/investlab-demo}"
if [ ! -e "$INVESTLAB_HOME/settings.json" ]; then
  investlab --home "$INVESTLAB_HOME" init --demo
fi
investlab --home "$INVESTLAB_HOME" run
investlab --home "$INVESTLAB_HOME" verify
exec investlab --home "$INVESTLAB_HOME" serve --public-demo --port "${PORT:-10000}"
