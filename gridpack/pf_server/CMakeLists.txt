# Builds pf_server against an installed GridPACK:
#   cmake -S gridpack/pf_server -B build -D GRIDPACK_DIR=/opt/cps/gridpack && cmake --build build
cmake_minimum_required(VERSION 3.5)

if (NOT GRIDPACK_DIR)
  set(GRIDPACK_DIR /opt/cps/gridpack CACHE PATH "GridPACK installation directory")
endif()

include("${GRIDPACK_DIR}/lib/GridPACK.cmake")

project(CPSPowerFlowServer)
enable_language(CXX)
gridpack_setup()

add_definitions(${GRIDPACK_DEFINITIONS})
include_directories(BEFORE ${GRIDPACK_INCLUDE_DIRS})

# Ubuntu's PETSc names "-lhdf5" among its libraries; the MPI build of HDF5 lives in its own directory
foreach(dir /usr/lib/x86_64-linux-gnu/hdf5/openmpi /usr/lib/aarch64-linux-gnu/hdf5/openmpi)
  if (EXISTS ${dir})
    link_directories(${dir})
  endif()
endforeach()

add_executable(pf_server pf_server.cpp)
target_link_libraries(pf_server ${GRIDPACK_LIBS})
install(TARGETS pf_server DESTINATION bin)
