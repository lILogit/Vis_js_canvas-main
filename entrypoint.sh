#!/bin/sh
set -e

CHAIN_FILE="${CHAIN_FILE:-chains/default.causal.json}"

# Create a default chain if none exists
if [ ! -f "$CHAIN_FILE" ]; then
  echo "  No chain found at $CHAIN_FILE — creating default chain..."
  python3 cli.py new "Default" --domain custom --file "$CHAIN_FILE" --no-editor
fi

exec python3 cli.py open "$CHAIN_FILE" \
  --host 0.0.0.0 \
  --port "${PORT:-7331}" \
  --no-browser
