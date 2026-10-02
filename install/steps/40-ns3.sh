#!/bin/bash
# NS-3 with only the modules the network federate needs, linked against HELICS.
source "$(dirname "$0")/common.sh"
if [ -d "$PREFIX/ns-3/build/lib" ] && ls "$PREFIX"/ns-3/build/lib/libns3*-core*.so >/dev/null 2>&1; then
  log "NS-3 already built"; exit 0
fi
log "building NS-3 ($NS3_TAG)"
[ -d "$PREFIX/ns-3" ] || git clone -q --depth 1 --branch "$NS3_TAG" https://gitlab.com/nsnam/ns-3-dev.git "$PREFIX/ns-3"
cd "$PREFIX/ns-3"
# ./ns3 refuses to run when USER is root (as under sudo); the installer builds as root on purpose
export USER=cps-install
./ns3 configure --build-profile=optimized --disable-examples --disable-tests \
  --enable-modules="core;network;internet;point-to-point;applications" \
  -- -DCMAKE_CXX_FLAGS="-I$PREFIX/helics/include" \
     "-DCMAKE_EXE_LINKER_FLAGS=-L$PREFIX/helics/lib -Wl,--no-as-needed -lhelicscpp -lhelics -Wl,--as-needed"
./ns3 build
