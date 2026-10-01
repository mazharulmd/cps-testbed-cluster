#!/bin/bash
# HELICS (C++ shared library for the NS-3 federate, and helics_broker).
source "$(dirname "$0")/common.sh"
if [ -x "$PREFIX/helics/bin/helics_broker" ]; then log "HELICS already installed"; exit 0; fi
log "building HELICS $HELICS_VERSION"
tmp=$(mktemp -d); cd "$tmp"
wget -q "https://github.com/GMLC-TDC/HELICS/releases/download/v$HELICS_VERSION/Helics-v$HELICS_VERSION-source.tar.gz"
mkdir src; tar xzf "Helics-v$HELICS_VERSION-source.tar.gz" -C src
cmake -S src -B build -G Ninja -D CMAKE_BUILD_TYPE=Release \
  -D HELICS_BUILD_CXX_SHARED_LIB=ON -D HELICS_BUILD_EXAMPLES=OFF -D HELICS_BUILD_TESTS=OFF \
  -D CMAKE_INSTALL_PREFIX="$PREFIX/helics"
cmake --build build -j "$JOBS"
cmake --install build
cd /; rm -rf "$tmp"
