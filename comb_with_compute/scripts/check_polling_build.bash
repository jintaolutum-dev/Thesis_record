#!/bin/bash
# Small local functionality check, not a performance measurement.
set -eo pipefail
source /etc/profile.d/modules.sh
module purge || true
module load stack/24.4.0
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
group=${1:-}
case "$group" in
  intel_verbs|intel_tcp)
    module load intel/2024.1.0 intel-mpi/2021.16.0
    build_dir="$source_dir/build_1_intel_dummy_com_polling_OMP"
    export I_MPI_HYDRA_BOOTSTRAP=fork I_MPI_HYDRA_IFACE=lo I_MPI_PIN=0
    unset I_MPI_PMI_LIBRARY
    export I_MPI_FABRICS=ofi I_MPI_OFI_PROVIDER="${group#intel_}"
    export I_MPI_ASYNC_PROGRESS=0 I_MPI_DEBUG=5
    launcher=("$I_MPI_ROOT/bin/mpiexec.hydra" -n 2)
    ;;
  openmpi_tcp)
    module load intel/2024.1.0 openmpi/4.1.8-intel24
    build_dir="$source_dir/build_2_openmpi_dummy_polling_OMP"
    launcher=("$OPENMPI_BASE/bin/mpirun" -np 2 --oversubscribe --bind-to none
      --mca pml ob1 --mca btl self,tcp --mca btl_tcp_if_include lo
      --mca btl_tcp_progress_thread 0)
    ;;
  mpich_tcp)
    build_dir="$source_dir/build_3_mpich_dummy_polling_OMP"
    mpi_dir="$(dirname "$source_dir")/local_software/mpich-4.2.2-gcc-spr"
    deps_dir="$(dirname "$source_dir")/local_software/mpich-runtime-deps/lib64"
    rdma_dir=/lrz/sys/spack/release/sles15.5/24.6.0/opt/sapphirerapids/rdma-core/52.0-gcc-sdcyulo/lib64
    export PATH="$mpi_dir/bin:$PATH"
    export LD_LIBRARY_PATH="$mpi_dir/lib:$deps_dir:$rdma_dir:${LD_LIBRARY_PATH:-}"
    export FI_PROVIDER=tcp MPIR_CVAR_ASYNC_PROGRESS=0
    launcher=("$mpi_dir/bin/mpiexec.hydra" -launcher fork -n 2)
    ;;
  *) echo "Usage: $0 {intel_verbs|intel_tcp|openmpi_tcp|mpich_tcp}" >&2; exit 2 ;;
esac
check_dir=$(mktemp -d "$build_dir/check-${group}.XXXXXX")
cd "$check_dir"
ldd "$build_dir/bin/comb" > linkage.log
if grep -q 'not found' linkage.log; then cat linkage.log; exit 1; fi
export OMP_NUM_THREADS=2
timeout 60 "${launcher[@]}" "$build_dir/bin/comb" 8_8_8 -divide 2_1_1 \
  -vars 1 -cycles 3 -omp_threads 2 -exec disable all \
  -exec enable seq -exec enable omp -comm disable all -comm enable mpi \
  -compute_target_us 100 -compute_poll_count 4 > run.log 2>&1
python3 - <<'PY'
import re
from pathlib import Path
files = list(Path('.').glob('*proc*'))
assert len(files) == 2, 'Expected two rank logs'
for p in sorted(files):
    values = [int(x) for x in re.findall(r'Compute polling totals: steps=(\d+)', p.read_text())]
    assert values and all(v == 12 for v in values), (str(p), values)
    print(str(p), 'polling step counts:', values)
Path('PASS').write_text('Two ranks; seq/OpenMP variants; 3 cycles * 4 polling steps verified.\n')
PY
echo "Passed $group: $check_dir"
