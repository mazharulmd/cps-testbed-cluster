#!/bin/bash
# Install the CPS testbed directly on Ubuntu 24.04 (no containers).
#
#   sudo ./install/install.sh                 single server or cluster head (default)
#   sudo ./install/install.sh --role node     compute node of a cluster
#
# Options:
#   --role head|node   what this machine is                                  [head]
#   --jobs N           parallel compile jobs                                  [all cores]
#   --no-services      build and install only; do not set up systemd services
#
# Software goes to /opt/cps, data to /srv/cps, settings to /etc/cps/cps.env. The services
# run as the system user "cps". Re-running the script updates the testbed code and skips
# the libraries that are already built. The first run takes about an hour (GridPACK,
# HELICS and NS-3 are compiled from source).
set -euo pipefail
ROLE=head
SERVICES=1
while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE=$2; shift 2 ;;
    --jobs) export JOBS=$2; shift 2 ;;
    --no-services) SERVICES=0; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
[ "$ROLE" = head ] || [ "$ROLE" = node ] || { echo "--role must be head or node"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || echo "WARNING: written for Ubuntu 24.04, this is ${PRETTY_NAME:-unknown}"

REPO=$(cd "$(dirname "$0")/.." && pwd)
STEPS=$REPO/install/steps
export CPS_PREFIX=/opt/cps CPS_SHARED=${CPS_SHARED:-/srv/cps}

"$STEPS/00-packages.sh"
"$STEPS/10-ga.sh"
"$STEPS/20-gridpack.sh" "$REPO/gridpack/patches"
"$STEPS/30-helics.sh"
"$STEPS/40-ns3.sh"
"$STEPS/50-python.sh" "$REPO/requirements.txt"
"$STEPS/60-nodered.sh" "$REPO/node-red/package.json"
"$STEPS/70-testbed.sh" "$REPO"

# service user and permissions
id cps >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/cps --shell /bin/bash cps
mkdir -p /etc/cps
if [ ! -f /etc/cps/cps.env ]; then
  sed "s/^CPS_ROLE=.*/CPS_ROLE=$ROLE/" "$REPO/install/cps.env.example" > /etc/cps/cps.env
  echo "[cps-install] wrote /etc/cps/cps.env"
fi
chown root:cps /etc/cps/cps.env && chmod 640 /etc/cps/cps.env
chown -R cps:cps /opt/cps/node-red
chmod 755 "$CPS_SHARED" "$CPS_SHARED"/runs "$CPS_SHARED"/grids "$CPS_SHARED"/legacy 2>/dev/null || true
chown -R cps:cps "$CPS_SHARED" 2>/dev/null || echo "[cps-install] note: could not chown $CPS_SHARED (NFS?); make it writable for user cps"

# command-line runner: cps-run --case 118 --duration 10 ...
cat > /usr/local/bin/cps-run <<'EOF'
#!/bin/bash
# Run one experiment from the command line with the settings of /etc/cps/cps.env.
set -a; . /etc/cps/cps.env; set +a
exec /opt/cps/venv/bin/python /opt/cps/testbed/federates/run_experiment.py "$@"
EOF
chmod 755 /usr/local/bin/cps-run

if [ "$SERVICES" = 1 ]; then
  systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true
  if [ "$ROLE" = head ]; then
    cp "$REPO"/install/systemd/cps-api.service "$REPO"/install/systemd/cps-nodered.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable cps-api cps-nodered
    systemctl restart cps-api cps-nodered
  else
    cp "$REPO"/install/systemd/cps-node.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable cps-node
    systemctl restart --no-block cps-node
  fi
fi

echo
echo "[cps-install] done ($ROLE)."
if [ "$ROLE" = head ]; then
  echo "  Dashboard:  http://$(hostname -I | awk '{print $1}'):1880/dashboard/experiments"
  echo "  API:        http://$(hostname -I | awk '{print $1}'):8080/docs"
  echo "  Settings:   /etc/cps/cps.env (set CPS_WEB_PASSWORD and NODERED_ADMIN_HASH, then"
  echo "              sudo systemctl restart cps-api cps-nodered)"
  echo "  Command line: sudo -u cps cps-run --case 118 --duration 10"
else
  echo "  Mount the cluster's shared directory at $CPS_SHARED, then add this host to"
  echo "  CPS_NODES in /etc/cps/cps.env on the head and restart cps-api there."
fi
