# COMB with computation

Based on [LLNL COMB](https://github.com/LLNL/Comb). See the upstream repository for general build instructions and usage.

Changes in this version:

- [`include/do_cycles.hpp`](include/do_cycles.hpp): Added time-budgeted dummy computation between posting communication and waiting for completion, with `mid-comm` timing and polling statistics.
- [`src/comb.cpp`](src/comb.cpp) and [`include/comb.hpp`](include/comb.hpp): Added `-compute_target_us` (computation time budget in microseconds) and `-compute_poll_count` (polling points per compute phase; `0` disables polling).
- [`include/comm.hpp`](include/comm.hpp): Added `MPI_Testall` polling of receive and send requests during computation, with completion tracking for the final wait and cleanup.
- [`scripts/build_polling.bash`](scripts/build_polling.bash) and [`scripts/check_polling_build.bash`](scripts/check_polling_build.bash): Added cluster-specific build and validation scripts. See [POLLING_BUILDS.md](POLLING_BUILDS.md) for details.

License: [MIT](LICENSE). See also [NOTICE](NOTICE).
