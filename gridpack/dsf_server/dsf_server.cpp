/*
 * dsf_server: a persistent, MPI-parallel GridPACK dynamic simulation for the CPS testbed.
 *
 * Started once per experiment with   mpirun -np N [--hostfile H] dsf_server input.xml
 * The input file names the network (.raw), the machine data (.dyr), the integration time step
 * and the scheduled grid events (bus faults, line and generator trips). GridPACK solves the
 * initial power flow, initialises the machines and then integrates in steps of <timeStep>
 * seconds; the grid federate drives it over rank 0's stdin:
 *
 *   DVREF <bus> <gen id> <dV pu>    move an exciter's voltage reference to its initial value + dV
 *   STEP <t>                        apply the batch on every rank, integrate up to time t (s),
 *                                   return the state
 *   QUIT
 *
 * Rank 0 answers on stdout with lines prefixed "@@" (anything else is GridPACK/MPI chatter):
 *
 *   @@RANK <rank> <host> <buses> <branches>   once per rank at start: how the grid is partitioned
 *   @@READY nbus=<n> ngen=<g> nranks=<p> t_setup=<s> dt=<s>
 *   @@RESULT t=<s> nbus=<n> ngen=<g> t_apply=<s> t_solve=<s>
 *   @@V <bus> <Vm pu> <Va deg> <f Hz>       one line per bus, ascending bus number
 *   @@G <bus> <gen id> <speed pu> <rotor angle deg> <P pu> <Q pu> <in service 0|1>
 *                                           one line per generator (P, Q on the system base)
 *
 * The states are read from the network directly (DSFullApp::getNetwork, added by
 * gridpack/patches) and gathered on rank 0, as pf_server does.
 *   @@WARN <text>
 *   @@END
 */
#include "mpi.h"
#include <ga.h>
#include <macdecls.h>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "gridpack/include/gridpack.hpp"
#include "gridpack/applications/modules/dynamic_simulation_full_y/dsf_app_module.hpp"

namespace {

struct Batch {
  std::vector<int> bus, id;
  std::vector<double> dv;
  double t = 0.0;
  int quit = 0;
};

// rank 0 reads commands until STEP or QUIT (or end of input)
Batch read_batch()
{
  Batch b;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    if (!(in >> cmd)) continue;
    if (cmd == "DVREF") {
      int bus, id; double dv;
      if (in >> bus >> id >> dv) {
        b.bus.push_back(bus); b.id.push_back(id); b.dv.push_back(dv);
      }
    } else if (cmd == "STEP") {
      if (in >> b.t) return b;
    } else if (cmd == "QUIT") {
      b.quit = 1;
      return b;
    }
  }
  b.quit = 1;
  return b;
}

template <typename T>
void bcast_vec(std::vector<T> &v, MPI_Datatype type, MPI_Comm comm)
{
  int n = static_cast<int>(v.size());
  MPI_Bcast(&n, 1, MPI_INT, 0, comm);
  v.resize(n);
  if (n > 0) MPI_Bcast(v.data(), n, type, 0, comm);
}

void bcast_batch(Batch &b, MPI_Comm comm)
{
  MPI_Bcast(&b.quit, 1, MPI_INT, 0, comm);
  MPI_Bcast(&b.t, 1, MPI_DOUBLE, 0, comm);
  bcast_vec(b.bus, MPI_INT, comm);
  bcast_vec(b.id, MPI_INT, comm);
  bcast_vec(b.dv, MPI_DOUBLE, comm);
}

// exciter voltage reference of one generator; collective, NAN where it has no exciter
double get_vref(gridpack::dynamic_simulation::DSFullApp &ds, int bus, const std::string &id,
                MPI_Comm comm)
{
  double v = 0.0, mine = -1.0e300, all;
  if (ds.getState(bus, id, "EXCITER", "VREF", &v)) mine = v;
  MPI_Allreduce(&mine, &all, 1, MPI_DOUBLE, MPI_MAX, comm);
  return all > -1.0e299 ? all : NAN;
}

typedef gridpack::dynamic_simulation::DSFullNetwork Network;
typedef gridpack::dynamic_simulation::DSFullBus Bus;

// gather fixed-width rows of doubles from every rank onto rank 0, sorted
std::vector<std::vector<double> > gather_rows(const std::vector<double> &mine, int width, MPI_Comm comm)
{
  int rank, size;
  MPI_Comm_rank(comm, &rank);
  MPI_Comm_size(comm, &size);
  int n = static_cast<int>(mine.size());
  std::vector<int> counts(size), displs(size);
  MPI_Gather(&n, 1, MPI_INT, counts.data(), 1, MPI_INT, 0, comm);
  std::vector<double> all;
  if (rank == 0) {
    int total = 0;
    for (int r = 0; r < size; r++) { displs[r] = total; total += counts[r]; }
    all.resize(total);
  }
  MPI_Gatherv(mine.data(), n, MPI_DOUBLE, all.data(), counts.data(), displs.data(),
              MPI_DOUBLE, 0, comm);
  std::vector<std::vector<double> > rows;
  for (size_t k = 0; k + width <= all.size(); k += width)
    rows.push_back(std::vector<double>(all.begin() + k, all.begin() + k + width));
  std::sort(rows.begin(), rows.end());
  return rows;
}

// (bus, Vm, Va deg, f Hz) of every bus
std::vector<std::vector<double> > bus_states(boost::shared_ptr<Network> &net, MPI_Comm comm)
{
  const double pi = 4.0 * atan(1.0);
  std::vector<double> mine;
  for (int i = 0; i < net->numBuses(); i++) {
    if (!net->getActiveBus(i)) continue;
    Bus *bus = net->getBus(i).get();
    gridpack::ComplexType v = bus->getComplexVoltage();
    mine.push_back(net->getOriginalBusIndex(i));
    mine.push_back(std::abs(v));
    mine.push_back(180.0 * std::arg(v) / pi);
    mine.push_back(bus->getBusVolFrequency());
  }
  return gather_rows(mine, 4, comm);
}

// (bus, id, speed pu, rotor angle deg, P, Q, in service) of every generator
std::vector<std::vector<double> > gen_states(boost::shared_ptr<Network> &net, MPI_Comm comm)
{
  const double pi = 4.0 * atan(1.0);
  std::vector<double> mine;
  for (int i = 0; i < net->numBuses(); i++) {
    if (!net->getActiveBus(i)) continue;
    Bus *bus = net->getBus(i).get();
    std::vector<std::string> ids = bus->getGenerators();
    for (size_t j = 0; j < ids.size(); j++) {
      // generators out of service in the network file have no machine model
      gridpack::dynamic_simulation::BaseGeneratorModel *gen = bus->getGenerator(ids[j]);
      if (gen == NULL) continue;
      std::vector<double> w;      // rotor angle (rad), speed (pu), P, Q
      gen->getWatchValues(w);
      if (w.size() < 4) continue;
      mine.push_back(net->getOriginalBusIndex(i));
      mine.push_back(atoi(ids[j].c_str()));
      mine.push_back(w[1]);
      mine.push_back(180.0 * w[0] / pi);
      mine.push_back(w[2]);
      mine.push_back(w[3]);
      mine.push_back(bus->getGenStatus(ids[j]) ? 1.0 : 0.0);
    }
  }
  return gather_rows(mine, 7, comm);
}


// where the grid lives: host, buses and branches owned by every rank (printed once at start)
template <typename Net>
void print_rank_map(boost::shared_ptr<Net> &net, MPI_Comm comm)
{
  int rank, size;
  MPI_Comm_rank(comm, &rank);
  MPI_Comm_size(comm, &size);
  int counts[2] = {0, 0};
  for (int i = 0; i < net->numBuses(); i++) if (net->getActiveBus(i)) counts[0]++;
  for (int i = 0; i < net->numBranches(); i++) if (net->getActiveBranch(i)) counts[1]++;
  char host[MPI_MAX_PROCESSOR_NAME] = {0};
  int len = 0;
  MPI_Get_processor_name(host, &len);
  std::vector<int> all(2 * size);
  std::vector<char> hosts(size * MPI_MAX_PROCESSOR_NAME);
  MPI_Gather(counts, 2, MPI_INT, all.data(), 2, MPI_INT, 0, comm);
  MPI_Gather(host, MPI_MAX_PROCESSOR_NAME, MPI_CHAR, hosts.data(), MPI_MAX_PROCESSOR_NAME, MPI_CHAR, 0, comm);
  if (rank == 0) {
    for (int r = 0; r < size; r++) {
      std::cout << "@@RANK " << r << " " << std::string(&hosts[r * MPI_MAX_PROCESSOR_NAME])
                << " " << all[2 * r] << " " << all[2 * r + 1] << "\n";
    }
    std::cout << std::flush;
  }
}

}  // namespace

const char* help = "CPS testbed persistent MPI dynamic simulation server";

int main(int argc, char **argv)
{
  gridpack::Environment env(argc, argv, help);
  {
    gridpack::parallel::Communicator world;
    MPI_Comm comm = MPI_COMM_WORLD;
    int rank = world.rank();
    double t0 = MPI_Wtime();

    gridpack::dynamic_simulation::DSFullApp ds;
    ds.solvePowerFlowBeforeDynSimu(argc >= 2 ? argv[1] : "input.xml");
    ds.readGenerators();
    ds.initialize();
    ds.setup();
    boost::shared_ptr<Network> net = ds.getNetwork();
    for (int i = 0; i < net->numBuses(); i++) net->getBus(i)->setBusVolFrequencyFlag(true);

    // every generator (bus, id) on every rank, and its initial exciter reference, so that
    // commands can move the references relative to the start
    std::vector<std::vector<double> > g0 = gen_states(net, comm);
    std::vector<int> gbus, gid;
    for (auto &r : g0) { gbus.push_back(static_cast<int>(r[0])); gid.push_back(static_cast<int>(r[1])); }
    bcast_vec(gbus, MPI_INT, comm);
    bcast_vec(gid, MPI_INT, comm);
    std::vector<double> vref0(gbus.size());
    for (size_t k = 0; k < gbus.size(); k++) vref0[k] = get_vref(ds, gbus[k], std::to_string(gid[k]), comm);

    int nbus = net->totalBuses();      // collective
    print_rank_map(net, comm);
    if (rank == 0) {
      std::cout << "@@READY nbus=" << nbus << " ngen=" << gbus.size()
                << " nranks=" << world.size() << " t_setup=" << MPI_Wtime() - t0
                << " dt=" << ds.getTimeStep() << std::endl;
    }

    while (true) {
      Batch b;
      if (rank == 0) b = read_batch();
      bcast_batch(b, comm);
      if (b.quit) break;

      double ta = MPI_Wtime();
      std::ostringstream warn;
      for (size_t k = 0; k < b.bus.size(); k++) {
        size_t g = 0;
        while (g < gbus.size() && !(gbus[g] == b.bus[k] && gid[g] == b.id[k])) g++;
        bool ok = g < gbus.size() && !std::isnan(vref0[g]);
        // setState searches the buses on every rank, so all ranks call it
        int any = 0, all = 0;
        if (ok) any = ds.setState(b.bus[k], std::to_string(b.id[k]), "EXCITER", "VREF",
                                  vref0[g] + b.dv[k]) ? 1 : 0;
        MPI_Allreduce(&any, &all, 1, MPI_INT, MPI_MAX, comm);
        if (!all) warn << "@@WARN generator " << b.bus[k] << "/" << b.id[k] << " has no exciter reference\n";
      }
      double ts = MPI_Wtime();
      ds.run(b.t);
      double te = MPI_Wtime();

      std::vector<std::vector<double> > v = bus_states(net, comm);
      std::vector<std::vector<double> > gs = gen_states(net, comm);
      if (rank == 0) {
        std::ostringstream out;
        out.precision(10);
        out << warn.str();
        out << "@@RESULT t=" << ds.getCurrentTime() << " nbus=" << v.size() << " ngen=" << gs.size()
            << " t_apply=" << ts - ta << " t_solve=" << te - ts << "\n";
        for (auto &r : v)
          out << "@@V " << static_cast<int>(r[0]) << " " << r[1] << " " << r[2] << " " << r[3] << "\n";
        for (auto &r : gs)
          out << "@@G " << static_cast<int>(r[0]) << " " << static_cast<int>(r[1]) << " " << r[2] << " "
              << r[3] << " " << r[4] << " " << r[5] << " " << static_cast<int>(r[6]) << "\n";
        out << "@@END\n";
        std::cout << out.str() << std::flush;
      }
    }
  }
  return 0;
}
