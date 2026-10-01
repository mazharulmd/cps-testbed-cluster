# Shared settings for the build steps (sourced). Used by install/install.sh on an
# Ubuntu 24.04 server and by docker/Dockerfile, so both installations are identical.
set -euo pipefail
PREFIX=${CPS_PREFIX:-/opt/cps}          # software
SHARED=${CPS_SHARED:-/srv/cps}          # runs, uploaded grids, cluster files
JOBS=${JOBS:-$(nproc)}
GA_VERSION=5.9
GRIDPACK_VERSION=v3.5
HELICS_VERSION=3.6.1
NS3_TAG=${NS3_TAG:-ns-3.48}
NODE_RED_VERSION=4.1.11
log() { echo "[cps-install] $*"; }
