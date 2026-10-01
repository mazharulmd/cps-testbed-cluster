/*
 * pf_server: a persistent, MPI-parallel GridPACK power-flow solver for the CPS testbed.
 *
 * Started once per experiment with   mpirun -np N [--hostfile H] pf_server input.xml
 * GridPACK reads and partitions the network across the N ranks a single time; the
 * grid federate then drives it over rank 0's stdin, one batch of changes per grid step:
 *
 *   LOAD <bus> <P MW> <Q Mvar>      set the load at a bus (loads present in the .raw file)
 *   VSET <bus> <gen id> <V pu>      set a generator voltage setpoint
 *   SOLVE                           apply the batch on every rank, solve, return all voltages
 *   QUIT
 *
 * Rank 0 answers on stdout with lines prefixed "@@" (anything else is GridPACK/MPI chatter):
 *
 *   @@READY nbus=<n> nranks=<p> t_setup=<s>
 *   @@RESULT ok=<0|1> nbus=<n> t_apply=<s> t_solve=<s>
 *   @@V <bus> <Vm pu> <Va deg>      one line per bus, ascending bus number
 *   @@END
 */
#include "mpi.h"
#include <ga.h>
#include <macdecls.h>
#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "gridpack/include/gridpack.hpp"
#include "gridpack/applications/modules/powerflow/pf_app_module.hpp"

namespace {

struct Batch {
  std::vector<int> load_bus;
  std::vector<double> load_p, load_q;
  std::vector<int> gen_bus, gen_id;
  std::vector<double> gen_v;
  int quit = 0;
};

// rank 0 reads commands until SOLVE or QUIT (or end of input)
Batch read_batch()
{
  Batch b;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd;
    if (!(in >> cmd)) continue;
    if (cmd == "LOAD") {
      int bus; double p, q;
      if (in >> bus >> p >> q) {
        b.load_bus.push_back(bus); b.load_p.push_back(p); b.load_q.push_back(q);
      }
    } else if (cmd == "VSET") {
      int bus, id; double v;
      if (in >> bus >> id >> v) {
        b.gen_bus.push_back(bus); b.gen_id.push_back(id); b.gen_v.push_back(v);
      }
    } else if (cmd == "SOLVE") {
      return b;
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
  bcast_vec(b.load_bus, MPI_INT, comm);
  bcast_vec(b.load_p, MPI_DOUBLE, comm);
  bcast_vec(b.load_q, MPI_DOUBLE, comm);
  bcast_vec(b.gen_bus, MPI_INT, comm);
  bcast_vec(b.gen_id, MPI_INT, comm);
  bcast_vec(b.gen_v, MPI_DOUBLE, comm);
}

// collect (bus, Vm, Va) of the buses each rank owns onto rank 0, sorted by bus number
std::vector<double> gather_voltages(
    boost::shared_ptr<gridpack::powerflow::PFNetwork> &net, MPI_Comm comm)
{
  const double pi = 4.0 * atan(1.0);
  std::vector<double> mine;
  for (int i = 0; i < net->numBuses(); i++) {
    if (!net->getActiveBus(i)) continue;
    gridpack::powerflow::PFBus *bus =
      dynamic_cast<gridpack::powerflow::PFBus*>(net->getBus(i).get());
    mine.push_back(net->getOriginalBusIndex(i));
    mine.push_back(bus->getVoltage());
    mine.push_back(180.0 * bus->getPhase() / pi);
  }
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
  if (rank == 0) {
    std::vector<std::vector<double> > rows;
    for (size_t k = 0; k + 2 < all.size(); k += 3) rows.push_back({all[k], all[k + 1], all[k + 2]});
    std::sort(rows.begin(), rows.end());
    all.clear();
    for (auto &r : rows) all.insert(all.end(), r.begin(), r.end());
  }
  return all;
}

}  // namespace

const char* help = "CPS testbed persistent MPI power-flow server";

int main(int argc, char **argv)
{
  gridpack::Environment env(argc, argv, help);
  {
    gridpack::parallel::Communicator world;
    MPI_Comm comm = MPI_COMM_WORLD;
    int rank = world.rank();
    double t0 = MPI_Wtime();

    gridpack::utility::Configuration *config =
      gridpack::utility::Configuration::configuration();
    config->open(argc >= 2 ? argv[1] : "input.xml", world);

    boost::shared_ptr<gridpack::powerflow::PFNetwork>
      network(new gridpack::powerflow::PFNetwork(world));
    gridpack::powerflow::PFAppModule pf;
    pf.suppressOutput(true);
    pf.readNetwork(network, config);
    pf.initialize();

    int nbus = network->totalBuses();
    if (rank == 0) {
      std::cout << "@@READY nbus=" << nbus << " nranks=" << world.size()
                << " t_setup=" << MPI_Wtime() - t0 << std::endl;
    }

    while (true) {
      Batch b;
      if (rank == 0) b = read_batch();
      bcast_batch(b, comm);
      if (b.quit) break;

      double ta = MPI_Wtime();
      // only the ranks that hold a bus can change it; the others return false
      for (size_t k = 0; k < b.load_bus.size(); k++) {
        pf.modifyDataCollectionLoadParam(b.load_bus[k], "1", LOAD_PL, b.load_p[k]);
        pf.modifyDataCollectionLoadParam(b.load_bus[k], "1", LOAD_QL, b.load_q[k]);
      }
      for (size_t k = 0; k < b.gen_bus.size(); k++) {
        pf.modifyDataCollectionGenParam(b.gen_bus[k], std::to_string(b.gen_id[k]),
                                        GENERATOR_VS, b.gen_v[k]);
      }
      pf.reload();
      double ts = MPI_Wtime();
      bool ok = pf.solve();
      double te = MPI_Wtime();

      std::vector<double> v = gather_voltages(network, comm);
      if (rank == 0) {
        std::ostringstream out;
        out.precision(10);
        out << "@@RESULT ok=" << (ok ? 1 : 0) << " nbus=" << v.size() / 3
            << " t_apply=" << ts - ta << " t_solve=" << te - ts << "\n";
        for (size_t k = 0; k + 2 < v.size(); k += 3) {
          out << "@@V " << static_cast<int>(v[k]) << " " << v[k + 1] << " " << v[k + 2] << "\n";
        }
        out << "@@END\n";
        std::cout << out.str() << std::flush;
      }
    }
  }
  return 0;
}
