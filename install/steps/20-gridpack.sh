#!/bin/bash
# GridPACK 3.5 (libraries and applications) against Ubuntu's PETSc and the Global Arrays above,
# with the testbed's patches (gridpack/patches: exciter voltage references that can be changed
# while a dynamic simulation runs). An installation built with other patches is rebuilt.
#
#   20-gridpack.sh [patch directory]                 [<repo>/gridpack/patches]
source "$(dirname "$0")/common.sh"
PATCHES=${1:-$(cd "$(dirname "$0")/../.." && pwd)/gridpack/patches}
stamp=$(cat "$PATCHES"/*.patch 2>/dev/null | sha256sum | cut -c1-16)
if [ -f "$PREFIX/gridpack/lib/GridPACK.cmake" ] && [ "$(cat "$PREFIX/gridpack/.cps-patches" 2>/dev/null)" = "$stamp" ]; then
  log "GridPACK already installed"; exit 0
fi
log "building GridPACK $GRIDPACK_VERSION"
tmp=$(mktemp -d)
git clone -q --depth 1 --branch "$GRIDPACK_VERSION" https://github.com/GridOPTICS/GridPACK "$tmp/gridpack"
for p in "$PATCHES"/*.patch; do
  [ -f "$p" ] || continue
  log "applying $(basename "$p")"
  git -C "$tmp/gridpack" apply "$p"
done
cmake -S "$tmp/gridpack/src" -B "$tmp/build" -G Ninja \
  -D CMAKE_BUILD_TYPE=Release -D BUILD_SHARED_LIBS=ON \
  -D GRIDPACK_ENABLE_TESTS=OFF -D ENABLE_ENVIRONMENT_FROM_COMM=YES \
  -D GA_DIR="$PREFIX/ga" -D PETSC_DIR=/usr/lib/petsc -D PARMETIS_DIR=/usr \
  -D MPI_CXX_COMPILER=mpicxx -D MPI_C_COMPILER=mpicc -D MPIEXEC=mpiexec \
  -D CMAKE_INSTALL_PREFIX="$PREFIX/gridpack"
cmake --build "$tmp/build" -j "$JOBS"
cmake --install "$tmp/build"
echo "$stamp" > "$PREFIX/gridpack/.cps-patches"
rm -rf "$tmp"
