#!/bin/bash
# The testbed itself: code into $PREFIX/testbed, the NS-3 network federate, the GridPACK MPI
# power-flow server, library paths, Node-RED flows and the data directory.
# Usage: 70-testbed.sh <repository directory>
source "$(dirname "$0")/common.sh"
src=$(cd "${1:?repository directory}" && pwd)
log "installing the testbed from $src"
mkdir -p "$PREFIX/testbed"
rsync -a --delete --exclude .git --exclude __pycache__ \
  "$src/cases" "$src/federates" "$src/webapp" "$src/tools" "$src/gridpack" "$src/legacy" \
  "$src/ns3-scratch" "$src/install" "$src/docker" "$src/requirements.txt" "$PREFIX/testbed/"

# NS-3 network federate
rm -rf "$PREFIX/ns-3/scratch/helicstest"
cp -r "$src/ns3-scratch/helicstest" "$PREFIX/ns-3/scratch/helicstest"
(cd "$PREFIX/ns-3" && USER=cps-install ./ns3 build helicstest)    # ./ns3 refuses USER=root
ln -sf "$(find "$PREFIX/ns-3/build/scratch/helicstest" -maxdepth 1 -type f -name '*helicstest*' | head -1)" \
  "$PREFIX/ns-3/helicstest"

# shared libraries for every process, including MPI ranks and federates started over ssh
cat > /etc/ld.so.conf.d/cps-testbed.conf <<LIBS
$PREFIX/helics/lib
$PREFIX/gridpack/lib
$PREFIX/ga/lib
$PREFIX/ns-3/build/lib
LIBS
ldconfig

# GridPACK MPI servers: power flow (pf_server) and dynamic simulation (dsf_server)
for server in pf_server dsf_server; do
  tmp=$(mktemp -d)
  cmake -S "$src/gridpack/$server" -B "$tmp" -D GRIDPACK_DIR="$PREFIX/gridpack" -D CMAKE_INSTALL_PREFIX="$PREFIX/gridpack"
  cmake --build "$tmp" -j "$JOBS" && cmake --install "$tmp"
  rm -rf "$tmp"
done

# Node-RED flows and settings (an existing flows.json is kept as a backup)
if [ -f "$PREFIX/node-red/flows.json" ] && ! cmp -s "$src/node-red/flows.json" "$PREFIX/node-red/flows.json"; then
  cp "$PREFIX/node-red/flows.json" "$PREFIX/node-red/flows.json.bak-$(date +%Y%m%d%H%M%S)"
fi
cp "$src/node-red/flows.json" "$src/node-red/settings.js" "$PREFIX/node-red/"

mkdir -p "$SHARED/runs" "$SHARED/grids" "$SHARED/legacy"
chmod +x "$PREFIX"/testbed/legacy/*.sh "$PREFIX"/testbed/docker/*.sh "$PREFIX"/testbed/install/*.sh 2>/dev/null || true
