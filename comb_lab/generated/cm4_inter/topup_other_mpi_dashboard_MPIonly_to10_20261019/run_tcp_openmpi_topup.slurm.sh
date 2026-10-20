#!/bin/bash
#SBATCH --job-name=tcp_openmpi_dashboard_topup
#SBATCH --clusters=inter
#SBATCH --partition=cm4_inter
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --ntasks=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --time=06:00:00
#SBATCH --chdir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019
#SBATCH --output=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019/batch.%j.out
#SBATCH --get-user-env
#SBATCH --export=NONE

set -euo pipefail
: "${SLURM_JOB_ID:?Run this wrapper through sbatch}"
batch_dir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_other_mpi_dashboard_MPIonly_to10_20261019
export TZ=Europe/Berlin
exec 8>"${batch_dir}/tcp_openmpi.lock"
flock -n 8 || { echo 'This combined batch is already running'; exit 1; }
sha256sum --check --quiet "${batch_dir}/stages.sha256"
for mpi in intelmpi_tcp openmpi; do
    log="${batch_dir}/batch.${mpi}.${SLURM_JOB_ID}.out"
    [[ ! -e "$log" ]] || { echo "Existing stage log: $log"; exit 1; }
    echo "Starting $mpi at $(date -Is); stage log: $log"
    if bash "${batch_dir}/stage_${mpi}.sh" > "$log" 2>&1; then
        echo "Completed $mpi at $(date -Is)"
    else
        rc=$?
        echo "Stage $mpi failed with exit code $rc; inspect $log"
        exit "$rc"
    fi
done
echo "All 400 scripts completed successfully at $(date -Is)"
