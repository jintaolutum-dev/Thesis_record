#!/bin/bash
# Reproduce the three binaries used by the four thesis transport groups.
set -eo pipefail
source /etc/profile.d/modules.sh
# LRZ sticky setup modules remain loaded and make purge return nonzero.
module purge || true
module load stack/24.4.0 cmake/3.29.6

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case "${1:-}" in
  intelmpi)
    module load intel/2024.1.0 intel-mpi/2021.16.0
    build_dir="$source_dir/build_1_intel_dummy_com_polling_OMP"
    compiler_args=(-DCMAKE_C_COMPILER="$(command -v icx)"
      -DCMAKE_CXX_COMPILER="$(command -v icpx)"
      -DMPI_C_COMPILER="$I_MPI_ROOT/bin/mpiicx"
      -DMPI_CXX_COMPILER="$I_MPI_ROOT/bin/mpiicpx" -DBLT_CXX_STD=c++17)
    ;;
  openmpi)
    module load intel/2024.1.0 openmpi/4.1.8-intel24
    build_dir="$source_dir/build_2_openmpi_dummy_polling_OMP"
    compiler_args=(-DCMAKE_C_COMPILER="$(command -v icx)"
      -DCMAKE_CXX_COMPILER="$(command -v icpx)"
      -DMPI_C_COMPILER="$OPENMPI_BASE/bin/mpicc"
      -DMPI_CXX_COMPILER="$OPENMPI_BASE/bin/mpicxx" -DBLT_CXX_STD=c++17)
    ;;
  mpich)
    build_dir="$source_dir/build_3_mpich_dummy_polling_OMP"
    mpi_dir="$(dirname "$source_dir")/local_software/mpich-4.2.2-gcc-spr"
    deps_dir="$(dirname "$source_dir")/local_software/mpich-runtime-deps/lib64"
    rdma_dir=/lrz/sys/spack/release/sles15.5/24.6.0/opt/sapphirerapids/rdma-core/52.0-gcc-sdcyulo/lib64
    export LD_LIBRARY_PATH="$mpi_dir/lib:$deps_dir:$rdma_dir:${LD_LIBRARY_PATH:-}"
    mkdir -p "$build_dir/mpi-wrappers"
    # The copied installation's original wrappers embed its former home path.
    python3 - "$mpi_dir" "$build_dir/mpi-wrappers" <<'PY'
import re, sys
from pathlib import Path
mpi, out = map(Path, sys.argv[1:])
for name in ('mpicc', 'mpicxx'):
    text = (mpi / 'bin' / name).read_text()
    old = re.search(r'^prefix=(.+)$', text, re.M).group(1)
    target = out / name
    target.write_text(text.replace(old, str(mpi)))
    target.chmod(0o755)
PY
    compiler_args=(-DCMAKE_C_COMPILER=/usr/bin/cc -DCMAKE_CXX_COMPILER=/usr/bin/c++
      -DMPI_C_COMPILER="$build_dir/mpi-wrappers/mpicc"
      -DMPI_CXX_COMPILER="$build_dir/mpi-wrappers/mpicxx" -DBLT_CXX_STD=c++14
      -DCMAKE_BUILD_RPATH="$mpi_dir/lib;$deps_dir;$rdma_dir")
    ;;
  *) echo "Usage: $0 {intelmpi|openmpi|mpich}" >&2; exit 2 ;;
esac

mkdir -p "$build_dir"
module list > "$build_dir/modules.log" 2>&1
cmake -S "$source_dir" -B "$build_dir" "${compiler_args[@]}" \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_MPI=ON -DENABLE_OPENMP=ON \
  -DCOMB_ENABLE_RAJA=ON -DENABLE_TESTS=OFF -DENABLE_EXAMPLES=OFF \
  > "$build_dir/configure.log" 2>&1
cmake --build "$build_dir" -j "${COMB_BUILD_JOBS:-2}" > "$build_dir/build.log" 2>&1
sha256sum "$build_dir/bin/comb" > "$build_dir/binary.sha256"
sha256sum "$source_dir/include/do_cycles.hpp" "$source_dir/include/comm.hpp" \
  "$source_dir/include/comb.hpp" "$source_dir/src/comb.cpp" > "$build_dir/source.sha256"
echo "Built $build_dir/bin/comb"
