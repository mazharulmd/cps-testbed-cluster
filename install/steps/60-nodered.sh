#!/bin/bash
# Node-RED and FlowFuse Dashboard 2. Usage: 60-nodered.sh <node-red/package.json>
source "$(dirname "$0")/common.sh"
pkg=${1:?package.json}
if [ "$(node-red --version 2>/dev/null | grep -o 'v[0-9.]*' | head -1)" != "v$NODE_RED_VERSION" ]; then
  log "installing Node-RED $NODE_RED_VERSION"
  npm install -g --unsafe-perm --no-audit --no-fund "node-red@$NODE_RED_VERSION"
fi
mkdir -p "$PREFIX/node-red"
cp "$pkg" "$PREFIX/node-red/package.json"
cd "$PREFIX/node-red" && npm install --omit=dev --no-audit --no-fund
