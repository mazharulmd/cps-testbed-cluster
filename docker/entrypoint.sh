#!/bin/bash
# Container start-up. CPS_ROLE=head runs the experiment API (8080) and Node-RED (1880);
# CPS_ROLE=node is a compute node (sshd only). The cluster layout and the SSH key are set up
# by install/configure.py, the same script a native installation uses (see its variables).
set -e
# variables for processes started over ssh (MPI ranks, remote federates)
env | grep -E '^(PATH|LD_LIBRARY_PATH|OMPI_|CPS_[A-Z_]*)=' | grep -v '^CPS_WEB_PASSWORD=' > /etc/environment
if [ "${CPS_ROLE:-head}" = node ]; then
  python3 /opt/cps/testbed/install/configure.py
  /usr/sbin/sshd
  exec sleep infinity
fi
/usr/sbin/sshd
python3 /opt/cps/testbed/install/configure.py
cd /opt/cps/testbed/webapp
uvicorn app:app --host 0.0.0.0 --port 8080 &
node-red -u /opt/cps/node-red &
wait -n
exit $?
