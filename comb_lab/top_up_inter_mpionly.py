"""Top up existing two-node cm4_inter MPI-only experiments using the web generator.

Dry run by default. Count run.sh files, not completed results. Preserve each
experiment's latest parameters; never overwrite existing scripts or results.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from collections import defaultdict

from core.generator import generate_job, _write_submit_all
from core.matrix import expand_matrix, load_config
from core.run_notes import create_run_notes
from viz.web_gui import ROOT, _apply_run_dir, _next_run_number, _with_cluster_profile

RUN = re.compile(r"run_(\d+)_MPIonly")


def capture(text, pattern):
    match = re.search(pattern, text, re.M)
    if not match:
        raise ValueError(f"Cannot recover parameter: {pattern}")
    return match.group(1)


def recover_job(source: Path, config: dict) -> dict:
    """Recover explicit inputs instead of replacing custom runs with YAML defaults."""
    text = source.read_text()
    mpi, topology, payload, compute = source.relative_to(
        ROOT / "generated" / "cm4_inter"
    ).parts[:4]
    cfg = _with_cluster_profile(copy.deepcopy(config), "cm4_inter", None)
    cfg["mpi_impl"] = {mpi: cfg["mpi_impl"][mpi]}
    mpi_cfg = cfg["mpi_impl"][mpi]
    mpi_cfg.pop("cases", None)
    mpi_cfg["compute_target_us"] = {}
    mpi_cfg["binary"] = capture(text, r"^ln -sf (\S+) ./comb$")
    header = text.split("ln -sf", 1)[0]
    mpi_cfg["modules"] = [
        mod for mod in re.findall(r"^module load (.+)$", header, re.M)
        if mod != "slurm_setup"
    ]
    mpi_cfg["modules_unload"] = re.findall(r"^module unload (.+)$", header, re.M)
    mpi_cfg["protocol_env"] = dict(re.findall(r'^export (\w+)="(.*)"$', header, re.M))
    mpi_cfg["diagnostics"] = {"mca_env": {}, "report_bindings": "--report-bindings" in text}
    topo = next(copy.deepcopy(t) for t in cfg["topology"] if t["name"] == topology)
    topo["nodes"] = int(capture(text, r"^#SBATCH --nodes=(\d+)$"))
    if topo["nodes"] != 2:
        raise ValueError(f"Not a two-node experiment: {source}")
    topo["ntasks_per_node"] = int(capture(text, r"^NTASKS_PER_NODE=(\d+)$"))
    topo["divide"] = capture(text, r'^DIVIDE="([^"]+)"$')
    topo["compute_target_us"] = {}
    cfg["topology"] = [topo]
    cfg["slurm"].pop("total_cpus_per_job", None)
    for key in ("clusters", "partition", "qos", "time", "cpus_per_task"):
        value = capture(text, r"^#SBATCH --" + key.replace("_", "-") + r"=(.+)$")
        cfg["slurm"][key] = int(value) if key == "cpus_per_task" else value
    cfg["slurm"]["runtime_cpus_per_rank"] = int(capture(text, r'echo "runtime_cpus_per_rank=(\d+)"'))
    grid_name = capture(text, r'echo "grid=([^"$]+)"')
    grid = {
        "size": capture(text, r'^GRID_SIZE="([^"]+)"$'),
        "ghost": capture(text, r'^GHOST="([^"]+)"$'),
        "periodic": capture(text, r'^PERIODIC="([^"]+)"$'),
        "vars": int(capture(text, r"^VARS=(\d+)$")),
        "cutoff": int(capture(text, r"^COMM_CUTOFF=(\d+)$")),
        # Keep the numeric spelling, including .0, for reproducible rendering.
        "compute_target_us": capture(text, r'^COMPUTE_ARGS="-compute_target_us ([\d.]+)"$'),
        "cycles": int(capture(text, r'^CYCLE_ARGS="-cycles (\d+)"$')),
    }
    cfg["grid"] = {grid_name: grid}
    cfg.pop("grid_by_topology", None)
    cfg["compute_mode"] = {compute: {"backend_mode": "mpi_only"}}
    if "-comm enable mpi" not in text or "-comm enable mock" in text:
        raise ValueError(f"Unexpected backend flags: {source}")
    cfg["cases"] = []
    labels = re.findall(r'"(\d+)_async([01])_(?:at(\d+)_)?c(\d+)_(\w+)"', text)
    for index, (number, asynchronous, threads, omp, wait) in enumerate(labels):
        if int(number) != index:
            raise ValueError(f"Nonsequential cases: {source}")
        case = {"async": int(asynchronous), "omp_threads": int(omp), "wait_mode": wait}
        if threads:
            case["async_threads"] = int(threads)
        cfg["cases"].append(case)
    if not cfg["cases"]:
        raise ValueError(f"No cases in {source}")
    cfg["comm"] = {key: capture(text, r"-comm " + key + r" (\w+)") for key in ("post_recv", "post_send")}
    cfg["exclude"] = []
    jobs = expand_matrix(cfg)
    assert len(jobs) == 1
    job = jobs[0]
    if Path(job["output_dir"]) != source.parent.parent:
        raise ValueError(f"Recovered parameters change the output directory: {source}")
    return job


def signature(text):
    """Check resources, protocol, payload, compute, backend and case arguments."""
    header = text.split("ln -sf", 1)[0]
    return {
        "slurm": re.findall(r"^#SBATCH.*$", text, re.M),
        "modules": re.findall(r"^module .*$", header, re.M),
        "environment": sorted(re.findall(r"^export .*$", header, re.M)),
        "binary": capture(text, r"^ln -sf (\S+) ./comb$"),
        "parameters": re.findall(r"^(?:NTASKS|NTASKS_PER_NODE|GRID_SIZE|DIVIDE|PERIODIC|GHOST|VARS|COMM_CUTOFF|COMPUTE_ARGS|CYCLE_ARGS)=.*$", text, re.M),
        "cases": text[text.index("#========"):],
        "comm": re.findall(r"-comm (?:enable|post_recv|post_send) \w+", text),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=int, default=10)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.target < 1:
        parser.error("--target must be positive")
    root = ROOT / "generated" / "cm4_inter"
    config = load_config(ROOT / "config" / "comb_cm4.yaml")
    grouped = defaultdict(dict)
    for source in sorted(root.glob("*/2n*/*/*/run_*_MPIonly/run.sh")):
        match = RUN.fullmatch(source.parent.name)
        if match:
            grouped[source.parent.parent][int(match[1])] = source

    rows, planned, sources = [], [], {}
    # Keep the two compute modes on the same run IDs, just as the web UI does.
    for payload in sorted({directory.parent for directory in grouped}):
        directories = [payload / mode for mode in ("midcomm", "no_midcomm")]
        if any(directory not in grouped for directory in directories):
            raise ValueError(f"Missing compute-mode counterpart: {payload}")
        ids = [set(grouped[directory]) for directory in directories]
        if ids[0] != ids[1]:
            raise ValueError(f"Unpaired MPI-only runs need review: {payload}")
        count = len(ids[0])
        missing = max(0, args.target - count)
        jobs = []
        if missing:
            for directory in directories:
                source = grouped[directory][max(grouped[directory])]
                job = recover_job(source, config)
                jobs.append(job)
                sources[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
            first = _next_run_number(jobs)
            for number in range(first, first + missing):
                pair = copy.deepcopy(jobs)
                _apply_run_dir(pair, number, "mpi_only")
                planned.extend(pair)
        else:
            first = None
        mpi, topology, message = payload.relative_to(root).parts
        rows.append({
            "mpi": mpi, "topology": topology, "message": message,
            "existing_runs_per_compute_mode": count,
            "added_runs_per_compute_mode": missing,
            "after_runs_per_compute_mode": count + missing,
            "new_scripts": 2 * missing,
            "new_run_first": f"run_{first:03d}_MPIonly" if missing else "",
            "new_run_last": f"run_{first + missing - 1:03d}_MPIonly" if missing else "",
            "source_midcomm": str(grouped[directories[0]][max(ids[0])]),
            "source_no_midcomm": str(grouped[directories[1]][max(ids[1])]),
        })
        if missing:
            # Validate one representative per compute mode before any production writes.
            with tempfile.TemporaryDirectory(prefix="comb_topup_") as temp:
                for index, job in enumerate(jobs):
                    check = copy.deepcopy(job)
                    check["output_dir"] = str(Path(temp) / str(index))
                    script = generate_job(check)
                    source = grouped[directories[index]][max(ids[index])]
                    before, after = signature(source.read_text()), signature(script.read_text())
                    changed = [key for key in before if before[key] != after[key]]
                    if changed:
                        raise ValueError(f"Regeneration changes {changed}: {source}")
                    subprocess.run(["bash", "-n", str(script)], check=True)

    targets = [Path(job["output_dir"]) / "run.sh" for job in planned]
    if len(set(targets)) != len(targets):
        raise ValueError("Duplicate generated paths")
    for target in targets:
        if target.parent.exists():
            raise FileExistsError(f"Refusing to reuse existing directory: {target.parent}")
    summary = {
        "scope": "existing cm4_inter two-node MPIonly experiments; paired midcomm/no_midcomm",
        "count_basis": "existing run.sh, not successful executions",
        "target": args.target,
        "experiments_scanned": len(rows),
        "experiments_under_target": sum(row["new_scripts"] > 0 for row in rows),
        "scripts_to_add": len(planned),
        "by_mpi": {mpi: {
            "experiments_under_target": sum(row["mpi"] == mpi and row["new_scripts"] > 0 for row in rows),
            "scripts_to_add": sum(row["new_scripts"] for row in rows if row["mpi"] == mpi),
        } for mpi in sorted({row["mpi"] for row in rows})},
        "applied": args.apply,
    }
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    for name, data in (("summary.json", summary), ("jobs.json", planned), ("source_hashes.json", sources)):
        (report / name).write_text(json.dumps(data, indent=2) + "\n")
    for filename, entries in (("inventory.csv", rows), ("underfilled.csv", [row for row in rows if row["new_scripts"]])):
        with (report / filename).open("w", newline="") as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(entries)
    (report / "new_scripts.txt").write_text("".join(str(path) + "\n" for path in targets))
    print(json.dumps(summary, indent=2), flush=True)
    if not args.apply:
        return
    for index, job in enumerate(planned):
        target = targets[index]
        # Check again at the point of writing to guard against another generator.
        target.parent.mkdir(parents=True, exist_ok=False)
        assert generate_job(job) == target
        subprocess.run(["bash", "-n", str(target)], check=True)
        if (index + 1) % 100 == 0:
            print(f"Generated and syntax-checked {index + 1}/{len(planned)}", flush=True)
    notes = create_run_notes(planned)
    submit = _write_submit_all(report, targets) if targets else None
    if submit:
        subprocess.run(["bash", "-n", str(submit)], check=True)
    for source, digest in sources.items():
        assert hashlib.sha256(Path(source).read_bytes()).hexdigest() == digest
    for row in rows:
        for mode in ("midcomm", "no_midcomm"):
            directory = root / row["mpi"] / row["topology"] / row["message"] / mode
            actual = sum(bool(RUN.fullmatch(p.parent.name)) for p in directory.glob("run_*_MPIonly/run.sh"))
            assert actual == row["after_runs_per_compute_mode"], directory
    (report / "verification.json").write_text(json.dumps({
        "new_scripts_syntax_checked": len(targets),
        "experiment_counts_verified": len(rows),
        "source_scripts_unchanged": len(sources),
        "shared_notes": len(notes),
        "submitted_jobs": 0,
    }, indent=2) + "\n")
    print(f"Verified {len(targets)} new scripts; {len(notes)} shared notes; submit manifest: {submit}", flush=True)


if __name__ == "__main__":
    main()
