#!/bin/bash
# Ubuntu 24.04 packages: compilers, OpenMPI, PETSc (with MUMPS), ParMETIS, Boost, ZeroMQ,
# Python, Node.js, OpenSSH.
source "$(dirname "$0")/common.sh"
export DEBIAN_FRONTEND=noninteractive
# Node.js: Ubuntu's nodejs + npm, unless a Node.js 18 or newer with its own npm is already
# installed (e.g. from NodeSource, whose nodejs package conflicts with Ubuntu's npm)
node_pkgs="nodejs npm"
node_major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
if [ "$node_major" -ge 18 ] && command -v npm >/dev/null; then
  log "using the installed Node.js $(node --version) and npm $(npm --version)"
  node_pkgs=""
fi
apt-get update
apt-get install -y --no-install-recommends \
  build-essential gfortran cmake ninja-build pkg-config git wget ca-certificates rsync \
  python3 python3-dev python3-venv \
  openmpi-bin libopenmpi-dev petsc-dev libparmetis-dev libmetis-dev \
  libboost-dev libboost-mpi-dev libboost-serialization-dev libboost-random-dev \
  libboost-filesystem-dev libboost-system-dev libzmq3-dev \
  openssh-server openssh-client $node_pkgs procps iproute2 less
