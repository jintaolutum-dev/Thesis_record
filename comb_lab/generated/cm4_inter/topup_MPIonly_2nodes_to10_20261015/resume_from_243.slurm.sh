#!/bin/bash
#SBATCH --job-name=comb_MPIonly_resume243
#SBATCH --clusters=inter
#SBATCH --partition=cm4_inter
#SBATCH --qos=normal
#SBATCH --nodes=2
#SBATCH --ntasks=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=56
#SBATCH --time=02:00:00
#SBATCH --chdir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_MPIonly_2nodes_to10_20261015
#SBATCH --output=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_MPIonly_2nodes_to10_20261015/resume243.%j.out
#SBATCH --get-user-env
#SBATCH --export=NONE

set -euo pipefail
: "${SLURM_JOB_ID:?This script must run inside a Slurm allocation}"
export SLURM_EXPORT_ENV=ALL
batch_dir=/dss/dsshome1/02/ge63neh3/comb_lab/generated/cm4_inter/topup_MPIonly_2nodes_to10_20261015
progress="${batch_dir}/resume243.${SLURM_JOB_ID}.tsv"
printf 'time\tmanifest_line\tstate\tscript\tlog\n' > "$progress"
line=242
while IFS= read -r script; do
    line=$((line + 1))
    run_dir=$(dirname "$script")
    log="${run_dir}/run.${SLURM_JOB_ID}.out"
    expected=$(grep -c '^#======== ' "$script")
    printf '%s\t%s\tSTART\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
    echo "Running manifest line ${line}/508: ${script}"
    if (cd "$run_dir" && bash run.sh </dev/null) > "$log" 2>&1; then
        rc=0
    else
        rc=$?
    fi
    # Child scripts can return zero even if an inner case failed.
    if (( rc != 0 )) || ! awk -v expected="$expected" '
        /^===== .* exit code: / { count++; if ($(NF-1) != "0") bad++ }
        /^All cases done\.$/ { done=1 }
        END { exit !(done && count == expected && bad == 0) }
    ' "$log"; then
        printf '%s\t%s\tFAILED\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
        echo "Stopped at manifest line ${line}; inspect ${log}"
        exit 1
    fi
    printf '%s\t%s\tDONE\t%s\t%s\n' "$(date -Is)" "$line" "$script" "$log" >> "$progress"
    echo "Completed manifest line ${line}/508"
done < "${batch_dir}/resume_from_243.txt"
echo 'All remaining 266 scripts completed successfully.'
