# Polling builds for the thesis configurations

All directories below are relative to this `comb_with_compute` directory.
The executable in each directory is `bin/comb`.

| Experiment group | Build directory | MPI library |
| --- | --- | --- |
| Intel verbs | `build_1_intel_dummy_com_polling_OMP` | Intel MPI 2021.16.0 |
| Intel TCP | `build_1_intel_dummy_com_polling_OMP` | Intel MPI 2021.16.0 |
| Open MPI TCP | `build_2_openmpi_dummy_polling_OMP` | Open MPI 4.1.8-intel24 |
| MPICH TCP | `build_3_mpich_dummy_polling_OMP` | Local MPICH 4.2.2-gcc-spr |

These are Release builds with MPI, OpenMP, and RAJA enabled, matching the
previous dummy-compute builds. Intel and Open MPI use Intel 2024.1.0 C/C++
compilers; MPICH uses `/usr/bin/cc` and `/usr/bin/c++`, as before.
The original build directories and generated experiment scripts are retained.

Rebuild from this directory:

```bash
bash scripts/build_polling.bash intelmpi
bash scripts/build_polling.bash openmpi
bash scripts/build_polling.bash mpich
```

The script saves `configure.log`, `build.log`, `modules.log`, source checksums,
and the binary checksum in each build directory. MPICH's copied wrapper
scripts have stale installation prefixes; relocated copies are generated in
the new build's `mpi-wrappers` directory, without changing the MPI installation.

Use the same launch settings as the previous experiment scripts, changing the
binary path to the appropriate polling build and adding, for example:

```bash
-compute_target_us 1000 -compute_poll_count 4
```

Intel verbs and Intel TCP deliberately share a binary. Keep their existing
runtime settings (`I_MPI_OFI_PROVIDER=verbs` or `tcp`, respectively).
Open MPI TCP uses `openmpi/4.1.8-intel24`, `OMPI_MCA_pml=ob1`, and
`OMPI_MCA_btl=self,vader,tcp`. MPICH TCP uses the existing local MPICH runtime
environment and `FI_PROVIDER=tcp`. Progress-thread and affinity settings
remain experiment choices; compiling these binaries does not enable them.

## Validation (2026-09-13)

All three Release builds completed, and runtime dependency checks found no
missing libraries in their configured environments. Four small two-rank
checks passed with sequential/OpenMP execution combinations and exactly
12 polling steps per variant per rank (3 cycles, 4 steps per cycle):

- Intel TCP: login-node check `check-intel_tcp.kaGLig`.
- Open MPI TCP: login-node check `check-openmpi_tcp.QBdftz`.
- MPICH TCP: CM4 node `cm4r15c06s04`, check `check-mpich_tcp.ZYSlle`.
- Intel verbs: same CM4 node, check `check-intel_verbs.3KdJCY`.

Check directories are inside their corresponding build directories and
contain `run.log`, `linkage.log`, rank logs, and a `PASS` marker. The CM4
validation used Slurm job 390585 and has completed. These are single-node
functionality checks, not inter-node performance measurements.

The copied MPICH library targets Sapphire Rapids and raised an illegal
instruction on the Ice Lake login node; run it on the intended CM4 compute
nodes. Intel verbs also required a compute node for an available OFI provider.
To reproduce a check in a suitable environment:

```bash
bash scripts/check_polling_build.bash intel_tcp
bash scripts/check_polling_build.bash openmpi_tcp
bash scripts/check_polling_build.bash mpich_tcp
bash scripts/check_polling_build.bash intel_verbs
```
