#!/bin/bash
# Legacy single-PMU IEEE 14 demo (Node-RED console): broker + replayed GridPACK solution + NS-3.
# Usage: ./run_scenario.sh --latency=50 --loss=0.2 --name=myrun [--attack=1] [--droppmu=8]

LATENCY=10
LOSS=0.2
NAME="run"
EXTRA=""

for arg in "$@"; do
  case $arg in
    --latency=*) LATENCY="${arg#*=}" ;;
    --loss=*)    LOSS="${arg#*=}" ;;
    --name=*)    NAME="${arg#*=}" ;;
    --attack=*)  EXTRA="$EXTRA --attack=${arg#*=}" ;;
    --droppmu=*) EXTRA="$EXTRA --droppmu=${arg#*=}" ;;
  esac
done

# paths (installation layout of install/install.sh and docker/Dockerfile)
CPS=${CPS_PREFIX:-/opt/cps}
HERE=$(cd "$(dirname "$0")" && pwd)
RESULTS=${CPS_SHARED:-/srv/cps}/legacy
mkdir -p "$RESULTS"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$RESULTS/${NAME}_${STAMP}.log"
export CPS_SHARED=${CPS_SHARED:-/srv/cps}
export LD_LIBRARY_PATH=$CPS/helics/lib:$CPS/ns-3/build/lib:$LD_LIBRARY_PATH

echo "=========================================="
echo " CPS Testbed Scenario: $NAME"
echo " Network latency: ${LATENCY} ms"
echo " Log: $LOG"
echo "=========================================="

# clean any stale processes
pkill -f "helics_broker -f 2 " 2>/dev/null   # only the demo's broker, not those of cluster experiments
pkill -f gridpack_fed 2>/dev/null
sleep 2

# 1. broker
$CPS/helics/bin/helics_broker -f 2 --loglevel=warning > /dev/null 2>&1 &
BROKER_PID=$!

# 2. GridPACK federate
$CPS/venv/bin/python "$HERE/gridpack_fed.py" 2>&1 | tee "$LOG.gridpack" &

# 3. NS-3 network federate
$CPS/ns-3/helicstest --latency=$LATENCY --loss=$LOSS --name=$NAME $EXTRA 2>&1 | tee "$LOG"

wait $BROKER_PID 2>/dev/null

echo ""
echo "=========================================="
echo " Scenario complete. Results saved:"
echo "   NS-3 / PDC log : $LOG"
echo "   GridPACK log   : $LOG.gridpack"
echo "=========================================="
