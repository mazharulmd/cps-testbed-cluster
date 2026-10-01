#!/bin/bash
# GridPACK 3.5 (libraries and applications) against Ubuntu's PETSc and the Global Arrays above.
source "$(dirname "$0")/common.sh"
if [ -f "$PREFIX/gridpack/lib/GridPACK.cmake" ]; then log "GridPACK already installed"; exit 0; fi
log "building GridPACK $GRIDPACK_VERSION"
tmp=$(mktemp -d)
git clone -q --depth 1 --branch "$GRIDPACK_VERSION" https://github.com/GridOPTICS/GridPACK "$tmp/gridpack"
cmake -S "$tmp/gridpack/src" -B "$tmp/build" -G Ninja \
  -D CMAKE_BUILD_TYPE=Release -D BUILD_SHARED_LIBS=ON \
  -D GRIDPACK_ENABLE_TESTS=OFF -D ENABLE_ENVIRONMENT_FROM_COMM=YES \
  -D GA_DIR="$PREFIX/ga" -D PETSC_DIR=/usr/lib/petsc -D PARMETIS_DIR=/usr \
  -D MPI_CXX_COMPILER=mpicxx -D MPI_C_COMPILER=mpicc -D MPIEXEC=mpiexec \
  -D CMAKE_INSTALL_PREFIX="$PREFIX/gridpack"
cmake --build "$tmp/build" -j "$JOBS"
cmake --install "$tmp/build"
rm -rf "$tmp"
