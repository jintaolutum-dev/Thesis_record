"""Build the new MPI-only batch from its manifest, without mixing historical cohorts.

Run with ../venv/bin/python build_latest.py. The existing historical, polling,
compute-window and cm4_std datasets retain their original run selections.
"""
import csv
import json
import re
from collections import defaultdict
from statistics import mean

from build_data import ROOT, BASE, CASES, PAIRS
from analyze_overlap import actual_send_payloads, parse_summary

BATCH = BASE / "topup_MPIonly_2nodes_to10_20261015"
RESOURCE_CASES = {"04": ("wait_all", 1), "05": ("wait_all", 12), "06": ("wait_all", 23)}


def capture(text, expression):
    match = re.search(expression, text, re.M)
    if not match:
        raise ValueError(f"Missing field: {expression}")
    return match[1]


def verify_run(directory):
    expected = re.findall(r"^#======== (\d+)", (directory / "run.sh").read_text(), re.M)
    logs = sorted(directory.glob("run.*.out"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise ValueError(f"No completion log: {directory}")
    text = logs[-1].read_text(errors="replace")
    exits = re.findall(r"^===== (\d+)_\S+ exit code: (-?\d+) =====$", text, re.M)
    if ([case for case, _ in exits] != expected or not expected
            or any(code != "0" for _, code in exits) or "All cases done." not in text):
        raise ValueError(f"Incomplete or failed run: {directory}")
    for case in expected:
        if not (directory / f"Comb_{case}_summary.csv").is_file():
            raise ValueError(f"Missing case {case} result: {directory}")


def read_sample(directory, run, case, policy):
    blocks, arguments, targets, texts = {}, {}, {}, {}
    wait, threads = {**CASES, **RESOURCE_CASES}[case]
    for mode in ("midcomm", "no_midcomm"):
        path = directory / mode / run / f"Comb_{case}_summary.csv"
        text = texts[mode] = path.read_text()
        if any(f"Wait {phase} using {wait} method" not in text for phase in ("Recv", "Send")):
            raise ValueError(f"Wrong wait mode: {path}")
        if int(capture(text, r"^OMP num threads\s+(\d+)$")) != threads:
            raise ValueError(f"Wrong OMP threads: {path}")
        args = capture(text, r"^Args\s+(.*)$")
        targets[mode] = float(capture(args, r"-compute_target_us;([\d.]+)"))
        arguments[mode] = re.sub(r"-compute_target_us;[^;\s]+", "-compute_target_us;PAIRED", args)
        if "-comm;enable;mock" in args or "-comm;enable;mpi" not in args:
            raise ValueError(f"Not MPI-only: {path}")
        polling = re.search(r"-compute_poll_count;(\d+)", args)
        if polling and int(polling[1]):
            raise ValueError(f"Unexpected polling cohort: {path}")
        blocks[mode] = parse_summary(path)[("mpi", *policy)]
    if arguments["midcomm"] != arguments["no_midcomm"] or targets["no_midcomm"] != 0:
        raise ValueError(f"Mismatched pair: {directory}/{run}/{case}")
    mid, no = blocks["midcomm"], blocks["no_midcomm"]
    compute = mid.get("mid-comm", {}).get("average", 0) * 1e6
    if targets["midcomm"] > 0 and compute <= 0:
        raise ValueError(f"Missing positive compute measurement: {directory}/{run}/{case}")
    wait_mid, wait_no = mid["wait-recv"]["average"] * 1e6, no["wait-recv"]["average"] * 1e6
    return dict(run=run, case=case, policy="/".join(policy),
                cycles=int(capture(arguments["midcomm"], r"-cycles;(\d+)")),
                target_us=targets["midcomm"], wait_no_us=wait_no, wait_mid_us=wait_mid,
                compute_us=compute, denominator_us=compute,
                overlap=(wait_no - wait_mid) / compute * 100 if targets["midcomm"] > 0 else None,
                bench_mid=mid["bench-comm"]["max"], pre_us=mid["pre-comm"]["average"] * 1e6,
                post_us=mid["post-comm"]["average"] * 1e6,
                config_signature=arguments["midcomm"])


def stats(values):
    valid = [v for v in values if v is not None]
    return (min(valid), mean(valid), max(valid)) if valid else (None, None, None)


def csv_text(rows):
    from io import StringIO
    stream = StringIO(newline="")
    if rows:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return stream.getvalue()


def main():
    from pathlib import Path
    scripts = [Path(line) for line in (BATCH / "new_scripts.txt").read_text().splitlines() if line]
    if len(set(scripts)) != len(scripts):
        raise ValueError("Duplicate scripts in manifest")
    grouped = defaultdict(lambda: defaultdict(set))
    for script in scripts:
        relative = script.relative_to(BASE)
        mpi, topology, message, mode, run, filename = relative.parts
        if topology != "2n2r_c24" or mode not in {"midcomm", "no_midcomm"} or filename != "run.sh" or not re.fullmatch(r"run_\d+_MPIonly", run):
            raise ValueError(f"Unexpected manifest path: {script}")
        verify_run(script.parent)
        grouped[(mpi, message)][run].add(mode)

    singles, comparisons, resources, raw, coverage = [], [], [], [], []
    for (mpi, message), runs in sorted(grouped.items()):
        directory = BASE / mpi / "2n2r_c24" / message
        if any(modes != {"midcomm", "no_midcomm"} for modes in runs.values()):
            raise ValueError(f"Unpaired manifest: {directory}")
        samples = defaultdict(list)
        sizes = set()
        grids = set()
        for run in sorted(runs):
            for mode in ("midcomm", "no_midcomm"):
                payloads = actual_send_payloads(directory / mode / run)
                remote = {size for rank, sends in payloads.items() for peer, size in sends if peer != rank}
                if len(remote) != 1:
                    raise ValueError(f"Unexpected remote payload: {directory}/{mode}/{run}")
                sizes.update(remote)
                grids.add(capture((directory / mode / run / "run.sh").read_text(), r'^GRID_SIZE="([^"]+)"$'))
            for policy, cases in ((('seq', 'seq', 'seq'), CASES), (('omp', 'seq', 'seq'), RESOURCE_CASES)):
                for case in cases:
                    samples[(policy, case)].append(read_sample(directory, run, case, policy))
        if len(sizes) != 1 or len(grids) != 1:
            raise ValueError(f"Mixed payload/grid: {directory}")
        size, grid = sizes.pop(), grids.pop()
        values = samples[(('seq', 'seq', 'seq'), '01')]
        configs = {(v['target_us'], v['cycles']) for v in values}
        if len(configs) != 1:
            raise ValueError(f"Mixed compute settings in batch: {directory}")
        target, cycles = configs.pop()
        payload = f"{size / (1024 if size < 1048576 else 1048576):.2f} " + ('KiB' if size < 1048576 else 'MiB')
        meta = dict(mpi=mpi, topology="2n2r_c24", directory=message, payload=payload,
                    payload_bytes=size, grid_size=grid, runs=", ".join(sorted(runs)), run_count=len(runs),
                    cycles=str(cycles), target_us=target, source="new_batch", baseline_us=None,
                    normalization="measured_compute", note="Zero compute target; overlap is undefined" if target == 0 else "")
        coverage.append(dict(meta, successful_pairs=len(runs), scripts=2 * len(runs)))
        for (policy, case), values in samples.items():
            if len({v['config_signature'] for v in values}) != 1:
                raise ValueError(f"Mixed case configuration: {directory}/{case}")
            raw.extend(dict(meta, **{k: v for k, v in value.items() if k != 'config_signature'}) for value in values)
            if policy == ('seq', 'seq', 'seq'):
                low, avg, high = stats(v['overlap'] for v in values)
                singles.append(dict(meta, case=case, min=low, mean=avg, max=high,
                    anomaly=low is not None and (low < 0 or high > 100 or high - low > 30)))
            else:
                row = dict(meta, case=case, policy='/'.join(policy))
                for metric in ('overlap', 'wait_no_us', 'wait_mid_us', 'bench_mid', 'pre_us', 'post_us', 'compute_us'):
                    low, avg, high = stats(v[metric] for v in values)
                    row.update({metric: avg, metric + '_min': low, metric + '_max': high})
                resources.append(row)
        for first, second in PAIRS.values():
            a = samples[(('seq', 'seq', 'seq'), first)]
            b = samples[(('seq', 'seq', 'seq'), second)]
            assert [v['run'] for v in a] == [v['run'] for v in b]
            low, avg, high = stats(right['overlap'] - left['overlap'] if left['overlap'] is not None and right['overlap'] is not None else None for left, right in zip(a, b))
            comparisons.append(dict(meta, pair=f"{first}-{second}", first_run_count=len(a), second_run_count=len(b),
                **{first + '_overlap': stats(v['overlap'] for v in a)[1], second + '_overlap': stats(v['overlap'] for v in b)[1]},
                delta=avg, delta_min=low, delta_max=high,
                bench_change_pct=mean((right['bench_mid'] / left['bench_mid'] - 1) * 100 for left, right in zip(a, b))))

    for rows in (singles, comparisons, resources, raw, coverage):
        rows.sort(key=lambda r: (r['mpi'], r['payload_bytes'], r.get('case', ''), r.get('pair', ''), r.get('run', '')))
    summary = dict(batch=BATCH.name, scripts=len(scripts), complete_pairs=len(scripts)//2,
                   experiment_groups=len(grouped), zero_compute_groups=sum(r['target_us'] == 0 for r in coverage),
                   scope="Only runs in this batch's new_scripts.txt; historical cohorts are separate")
    datasets = dict(LATEST_DATA=singles, LATEST_COMPARISONS=comparisons, LATEST_RESOURCES=resources,
                    LATEST_COVERAGE=coverage, LATEST_SUMMARY=summary)
    # Finish all validation and serialization before replacing any dashboard asset.
    output = ''.join(f'const {name} = {json.dumps(data, ensure_ascii=False, allow_nan=False)};\n' for name, data in datasets.items())
    files = {'latest-data.js': output, 'latest-overlap.csv': csv_text(singles),
             'latest-comparisons.csv': csv_text(comparisons), 'latest-resources.csv': csv_text(resources),
             'latest-runs.csv': csv_text(raw), 'latest-coverage.csv': csv_text(coverage)}
    for name, content in files.items():
        temporary = ROOT / (name + '.tmp')
        temporary.write_text(content)
        temporary.replace(ROOT / name)
    print(json.dumps(summary, indent=2))
    print(f"Built {len(singles)} overlap points, {len(comparisons)} comparisons, {len(resources)} resource points, {len(raw)} paired case samples.")


if __name__ == '__main__':
    main()
