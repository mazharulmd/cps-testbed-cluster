#!/bin/bash
# Ubuntu 24.04 packages: compilers, OpenMPI, PETSc (with MUMPS), ParMETIS, Boost, ZeroMQ,
# Python, Node.js, OpenSSH.
source "$(dirname "$0")/common.sh"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  build-essential gfortran cmake ninja-build pkg-config git wget ca-certificates rsync \
  python3 python3-dev python3-venv \
  openmpi-bin libopenmpi-dev petsc-dev libparmetis-dev libmetis-dev \
  libboost-dev libboost-mpi-dev libboost-serialization-dev libboost-random-dev \
  libboost-filesystem-dev libboost-system-dev libzmq3-dev \
  openssh-server openssh-client nodejs npm procps iproute2 less
