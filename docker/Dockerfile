# CPS testbed container: the same build as a native installation (install/steps), one image
# for every role. docker/entrypoint.sh starts the services of the role (CPS_ROLE).
#
#   docker build -f docker/Dockerfile -t cps-testbed-cluster .
#
# OpenMPI 4.1, PETSc 3.19 (Ubuntu, MUMPS), ParMETIS, Global Arrays 5.9, GridPACK 3.5 + the
# testbed's MPI power-flow and dynamic simulation servers, HELICS 3.6.1, NS-3.48 + the network federate, Python
# federates and API, Node-RED 4.1 + Dashboard 2, OpenSSH.
ARG BASE=ubuntu:24.04
FROM ${BASE}
ARG JOBS=4
ENV CPS_PREFIX=/opt/cps CPS_SHARED=/srv/cps JOBS=${JOBS} DEBIAN_FRONTEND=noninteractive

# each step is its own layer, so changing the testbed code does not rebuild the libraries
COPY install/steps/common.sh install/steps/00-packages.sh /tmp/steps/
RUN /tmp/steps/00-packages.sh && rm -rf /var/lib/apt/lists/*
COPY install/steps/10-ga.sh /tmp/steps/
RUN /tmp/steps/10-ga.sh
COPY install/steps/20-gridpack.sh /tmp/steps/
COPY gridpack/patches /tmp/steps/gridpack-patches/
RUN /tmp/steps/20-gridpack.sh /tmp/steps/gridpack-patches
COPY install/steps/30-helics.sh /tmp/steps/
RUN /tmp/steps/30-helics.sh
COPY install/steps/40-ns3.sh /tmp/steps/
RUN /tmp/steps/40-ns3.sh
COPY install/steps/50-python.sh requirements.txt /tmp/steps/
RUN /tmp/steps/50-python.sh /tmp/steps/requirements.txt
COPY install/steps/60-nodered.sh node-red/package.json /tmp/steps/
RUN /tmp/steps/60-nodered.sh /tmp/steps/package.json

# OpenSSH for MPI and remote federates between containers (keys are created at start-up)
RUN mkdir -p /run/sshd \
    && printf 'PermitRootLogin prohibit-password\nPasswordAuthentication no\n' > /etc/ssh/sshd_config.d/cps.conf \
    && printf 'Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n  LogLevel ERROR\n' > /etc/ssh/ssh_config.d/cps.conf

# OpenMPI inside containers: run as root, launch over ssh, no CMA single-copy, one interface
ENV OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    OMPI_MCA_plm_rsh_agent=ssh OMPI_MCA_btl_vader_single_copy_mechanism=none \
    OMPI_MCA_btl_tcp_if_include=eth0 OMPI_MCA_oob_tcp_if_include=eth0 \
    OMPI_MCA_plm_rsh_no_tree_spawn=1

# the testbed
COPY . /tmp/repo
RUN /tmp/repo/install/steps/70-testbed.sh /tmp/repo && rm -rf /tmp/repo /tmp/steps

ENV PATH=/opt/cps/venv/bin:/opt/cps/helics/bin:${PATH} \
    CPS_RESULTS=/srv/cps/runs CPS_GRIDS=/srv/cps/grids CPS_CLUSTER_CONFIG=/srv/cps/cluster.json \
    CPS_PF_SERVER=/opt/cps/gridpack/bin/pf_server CPS_DSF_SERVER=/opt/cps/gridpack/bin/dsf_server CPS_NS3_BIN=/opt/cps/ns-3/helicstest \
    CPS_HELICS_BROKER=/opt/cps/helics/bin/helics_broker
EXPOSE 1880 8080 22
ENTRYPOINT ["/opt/cps/testbed/docker/entrypoint.sh"]
