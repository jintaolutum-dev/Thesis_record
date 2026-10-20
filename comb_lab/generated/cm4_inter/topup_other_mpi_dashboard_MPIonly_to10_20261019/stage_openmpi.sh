#!/bin/bash
#SBATCH --job-name=openmpi_dashboard_topup
#SBATCH --clusters=inter
#SBATCH --partition=cm4_inter
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --ntasks=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --time=04:00:00
#SBATCH --chdir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019
#SBATCH --output=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019/batch.%j.out
#SBATCH --get-user-env
#SBATCH --export=NONE

set -euo pipefail
: "${SLURM_JOB_ID:?Run this wrapper through sbatch}"
batch_dir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019
exec 9>"${batch_dir}/openmpi.lock"
flock -n 9 || { echo 'This batch is already running'; exit 1; }
export TZ=Europe/Berlin
module load slurm_setup
module unload openmpi/4.1.8-gcc13
module load stack/24.4.0
module use /lrz/sys/spack/release/24.4.0/modules/MPI-icelake
module load openmpi/4.1.8-intel24
mpi_version=$(mpirun --version)
printf '%s\n' "$mpi_version"
[[ "$mpi_version" == *"Open MPI) 4.1.8"* ]] || { echo 'Unexpected MPI version'; exit 1; }
binary=/dss/dsshome1/02/ge63neh3/comb_with_compute/build_2_openmpi_dummy_OMP/bin/comb
libraries=$(ldd "$binary")
printf '%s\n' "$libraries"
if [[ "$libraries" == *"not found"* ]]; then
    echo 'Missing binary dependencies'
    exit 1
fi
module list 2>&1
export SLURM_EXPORT_ENV=ALL
sha256sum --check --quiet "${batch_dir}/scripts_openmpi.sha256"
progress="${batch_dir}/progress.openmpi.${SLURM_JOB_ID}.tsv"
printf 'time\tmanifest_line\tstate\tscript\tlog\n' > "$progress"
line=0
script=''
log=''
trap 'printf "%s\t%s\tINTERRUPTED\t%s\t%s\n" "$(date -Is)" "$line" "$script" "$log" >> "$progress"; exit 143' TERM INT
total=$(wc -l < "${batch_dir}/new_scripts_openmpi.txt")
echo "Started $(date -Is), job ${SLURM_JOB_ID}, nodes ${SLURM_JOB_NODELIST}, scripts ${total}"
while IFS= read -r script; do
    line=$((line + 1))
    run_dir=$(dirname "$script")
    log="${run_dir}/run.${SLURM_JOB_ID}.out"
    # Initial submission must never overwrite previously generated results.
    if compgen -G "${run_dir}/Comb_*_summary.csv" >/dev/null || compgen -G "${run_dir}/run.*.out" >/dev/null; then
        printf '%s\t%s\tEXISTING_RESULTS\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
        echo "Existing results at manifest line ${line}; stopped for explicit resume selection"
        exit 1
    fi
    expected=$(grep -c '^#======== ' "$script")
    printf '%s\t%s\tSTART\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
    echo "Running ${line}/${total}: ${script}"
    if (cd "$run_dir" && bash run.sh </dev/null) > "$log" 2>&1; then rc=0; else rc=$?; fi
    valid=1
    if ! awk -v expected="$expected" '
        /^===== .* exit code: / { count++; if ($(NF-1) != "0") bad++ }
        /^All cases done\.$/ { done=1 }
        END { exit !(done && count == expected && bad == 0) }
    ' "$log"; then valid=0; fi
    while IFS= read -r case_id; do
        result="${run_dir}/Comb_${case_id}_summary.csv"
        if [[ ! -s "$result" ]] || ! grep -q '^Starting test Comm mpi ' "$result"; then valid=0; fi
    done < <(awk '/^#======== / {print $2}' "$script")
    if (( rc != 0 || valid == 0 )); then
        printf '%s\t%s\tFAILED\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
        echo "Stopped at ${line}/${total}; inspect ${log}"
        exit 1
    fi
    printf '%s\t%s\tDONE\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
    echo "Completed ${line}/${total} at $(date -Is)"
done < "${batch_dir}/new_scripts_openmpi.txt"
echo "All ${total} scripts completed successfully at $(date -Is)"
