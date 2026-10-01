#!/bin/bash
# Global Arrays (GridPACK's distributed data layer), configured as in GridPACK's own install script.
source "$(dirname "$0")/common.sh"
if [ -f "$PREFIX/ga/lib/libga.so" ]; then log "Global Arrays already installed"; exit 0; fi
log "building Global Arrays $GA_VERSION"
tmp=$(mktemp -d); cd "$tmp"
wget -q "https://github.com/GlobalArrays/ga/releases/download/v$GA_VERSION/ga-$GA_VERSION.tar.gz"
tar xzf "ga-$GA_VERSION.tar.gz"; cd "ga-$GA_VERSION"
./configure --with-mpi-ts --disable-f77 --without-blas --without-lapack --without-scalapack \
  --enable-cxx --enable-i4 --enable-shared=yes --enable-static=no --prefix="$PREFIX/ga" \
  CFLAGS=-Wno-implicit-function-declaration
make -j"$JOBS" install
cd /; rm -rf "$tmp"
