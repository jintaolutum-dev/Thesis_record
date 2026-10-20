"""Audit the October MPIonly top-up against its sources and dashboard cohorts.

Read-only for experiments and dashboard assets; writes CSV/JSON audit reports.
Run: PYTHONDONTWRITEBYTECODE=1 venv/bin/python audit_inter_topup.py
"""
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'generated/cm4_inter'
DASH = ROOT / 'message-overlap-dashboard'
BATCH = BASE / 'topup_MPIonly_2nodes_to10_20261015'
OUT = BATCH / 'parameter_audit_20261019'


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def capture(text, regex):
    found = re.search(regex, text, re.M)
    if not found:
        raise ValueError(f'Missing field {regex}')
    return found[1]


def read_csv(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


@lru_cache(None)
def script_info(path):
    text = path.read_text()
    header = text.split('ln -sf', 1)[0]
    params = dict(re.findall(r'^(NTASKS|NTASKS_PER_NODE|GRID_SIZE|DIVIDE|PERIODIC|GHOST|VARS|COMM_CUTOFF)="?([^"\n]+)"?$', text, re.M))
    cases = {}
    for part in re.split(r'(?m)^#======== ', text)[1:]:
        case = capture(part, r'^(\d+)')
        label = capture(part, r'"(\d+_async[01]_(?:at\d+_)?c\d+_\w+)"')
        cases[case] = dict(label=label, omp=int(capture(part, r'^export OMP_NUM_THREADS=(\d+)$')),
                           wait=label.split('_c', 1)[1].split('_', 1)[1],
                           exports=re.findall(r'^(?:export|unset) .+$', part, re.M))
    # Preserve binding / launcher differences while excluding the intentional backend change.
    launcher = text[text.index('_comb_args()'):text.index('#========')]
    launcher = re.sub(r'^-comm enable mock.*\n', '', launcher, flags=re.M)
    launcher = '\n'.join(line.rstrip() for line in launcher.splitlines() if line.strip())
    return dict(path=str(path), sha256=digest(text),
                target_us=float(re.search(r'-compute_target_us ([\d.]+)', text)[1]) if '-compute_target_us ' in text else 0.0,
                cycles=int(capture(text, r'^CYCLE_ARGS="-cycles (\d+)"$')),
                geometry=params,
                modules=re.findall(r'^module .+$', header, re.M),
                protocol_env=re.findall(r'^export .+$', header, re.M),
                binary=capture(text, r'^ln -sf (\S+) ./comb$'),
                resources=re.findall(r'^#SBATCH --(?:nodes|ntasks-per-node|cpus-per-task|clusters|partition)=.+$', text, re.M),
                backends=sorted(set(re.findall(r'-comm enable (\w+)', text))),
                backends_explicit='-comm disable all' in text,
                post_methods=re.findall(r'-comm post_(?:recv|send) (\w+)', text),
                cases=cases, launcher_sha256=digest(launcher))


@lru_cache(None)
def runtime_info(path):
    lines = []
    with path.open() as handle:
        for line in handle:
            if line.startswith('Starting test'):
                break
            lines.append(line)
    text = ''.join(lines)
    args = capture(text, r'^Args\s+(.*)$')
    geometry = dict(GRID_SIZE=args.split(';')[1])
    for field, flag in [('DIVIDE', 'divide'), ('PERIODIC', 'periodic'), ('GHOST', 'ghost'), ('VARS', 'vars')]:
        geometry[field] = capture(args, rf'-{flag};([^;]+)')
    geometry['COMM_CUTOFF'] = capture(text, r'^Message policy cutoff (\d+)')
    geometry['NTASKS'] = capture(text, r'^Started rank 0 of (\d+)')
    enabled = sorted(set(re.findall(r'-comm;enable;(\w+)', args)))
    # Without disable-all, unmentioned default backends can still execute.
    if '-comm;disable;all' not in args:
        enabled = sorted(set(re.findall(r'^Starting test Comm (\w+)', path.read_text(), re.M)))
    return dict(path=str(path), target_us=float(re.search(r'-compute_target_us;([\d.]+)', args)[1]) if '-compute_target_us;' in args else 0.0,
                cycles=int(capture(args, r'-cycles;(\d+)')), geometry=geometry,
                backends=enabled,
                post_methods=re.findall(r'-comm;post_(?:recv|send);(\w+)', args),
                omp=int(capture(text, r'^OMP num threads\s+(\d+)')),
                wait_methods=re.findall(r'^Wait (?:Recv|Send) using (\w+) method', text, re.M),
                compiler=capture(text, r'^Compiler (.+)$'),
                version=capture(text, r'^Comb version (.+)$'),
                args=args)


def runtime_diffs(script, result, case):
    keys = ['target_us', 'cycles', 'post_methods'] + (['backends'] if script['backends_explicit'] else [])
    differences = [key for key in keys if script[key] != result[key]]
    differences += ['geometry.' + key for key, value in result['geometry'].items() if key in script['geometry'] and script['geometry'][key] != value]
    expected = script['cases'][case]
    if expected['omp'] != result['omp']:
        differences.append('omp')
    if result['wait_methods'] != [expected['wait'], expected['wait']]:
        differences.append('wait_methods')
    return differences


def compact(values):
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def main():
    coverage = read_csv(DASH / 'latest-coverage.csv')
    inventory = {(r['mpi'], r['message']): r for r in read_csv(BATCH / 'inventory.csv')}
    sources = json.loads((BATCH / 'source_hashes.json').read_text())
    manifest = [Path(line) for line in (BATCH / 'new_scripts.txt').read_text().splitlines() if line]
    historical = defaultdict(list)
    for table in ['overlap-current.csv', 'resources-current.csv']:
        for row in read_csv(DASH / table):
            historical[row['mpi'], row['directory']].append(dict(row, table=table))
    source_changed = [p for p, value in sources.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest() != value]
    errors, runtimes, groups, comparisons, script_rows, affected = [], [], [], [], [], []
    fields = ['target_us', 'cycles', 'geometry', 'modules', 'protocol_env', 'binary', 'resources',
              'backends', 'post_methods', 'cases', 'launcher_sha256']
    for group in coverage:
        key = (group['mpi'], group['directory'])
        item = inventory[key]
        directory = BASE / group['mpi'] / group['topology'] / group['directory']
        new_paths = [p for p in manifest if p.parent.parent.parent == directory]
        new = {}
        group_scripts = []
        group_runtime_count = 0
        new_runtime_records, old_runtime_records = [], []
        for path in new_paths:
            mode = path.parent.parent.name
            info = script_info(path)
            new.setdefault(mode, info)
            source = script_info(Path(item['source_' + mode]))
            changed = [field for field in fields if info[field] != source[field]]
            record = dict(mpi=group['mpi'], directory=group['directory'], mode=mode, run=path.parent.name,
                          script=str(path), source=source['path'], byte_identical=info['sha256'] == source['sha256'],
                          source_case_summaries=sum((Path(source['path']).parent / f'Comb_{case}_summary.csv').is_file() for case in source['cases']),
                          source_diff_fields=','.join(changed), runtime_cases_checked=0, runtime_errors=0)
            for case in info['cases']:
                result_path = path.parent / f'Comb_{case}_summary.csv'
                try:
                    actual = runtime_info(result_path)
                    new_runtime_records.append(dict(actual, mode=mode))
                    diffs = runtime_diffs(info, actual, case)
                    runtimes.append(dict(actual, mpi=group['mpi'], directory=group['directory'],
                                         mode=mode, run=path.parent.name, case=case, origin='new', script_diffs=diffs))
                    record['runtime_cases_checked'] += 1
                    group_runtime_count += 1
                    if diffs:
                        errors.append(dict(path=str(result_path), differences=diffs))
                        record['runtime_errors'] += 1
                except (ValueError, OSError) as exc:
                    errors.append(dict(path=str(result_path), error=str(exc)))
                    record['runtime_errors'] += 1
            script_rows.append(record)
            group_scripts.append(record)

        references = {}
        for old in historical[key]:
            for run in old['runs'].split(', '):
                for mode in ['midcomm', 'no_midcomm']:
                    references.setdefault((mode, run), set()).add(old['case'])
        old_targets, old_cycles, changed_fields, runtime_changes = set(), set(), set(), set()
        old_scripts = []
        historical_runtime_errors = []
        for (mode, run), cases in sorted(references.items()):
            old_path = directory / mode / run / 'run.sh'
            old_info = script_info(old_path)
            old_scripts.append(old_info)
            diffs = {field: dict(historical=old_info[field], new=new[mode][field]) for field in fields if old_info[field] != new[mode][field]}
            changed_fields.update(diffs)
            actual_targets, actual_cycles = set(), set()
            for case in sorted(cases):
                result_path = old_path.parent / f'Comb_{case}_summary.csv'
                actual = runtime_info(result_path)
                old_runtime_records.append(dict(actual, mode=mode))
                script_diffs = runtime_diffs(old_info, actual, case)
                new_diffs = runtime_diffs(new[mode], actual, case)
                runtime_changes.update(new_diffs)
                actual_targets.add(actual['target_us'])
                actual_cycles.add(actual['cycles'])
                runtimes.append(dict(actual, mpi=group['mpi'], directory=group['directory'],
                                     mode=mode, run=run, case=case, origin='historical', script_diffs=script_diffs))
                if script_diffs:
                    historical_runtime_errors.append(dict(path=str(result_path), differences=script_diffs))
            if mode == 'midcomm':
                old_targets.update(actual_targets)
                old_cycles.update(actual_cycles)
            comparisons.append(dict(mpi=group['mpi'], directory=group['directory'], mode=mode,
                                    historical_script=str(old_path), new_script=new[mode]['path'],
                                    cases=sorted(cases), historical_runtime_targets=sorted(actual_targets),
                                    historical_runtime_cycles=sorted(actual_cycles), differences=diffs))
        # Classify by actual recorded parameters, not merely present-day script content.
        scientific_diffs = runtime_changes - {'backends'}
        other_setup_diffs = changed_fields - {'target_us', 'cycles', 'backends'}
        for field in ['compiler', 'version']:
            if old_runtime_records and {r[field] for r in new_runtime_records} != {r[field] for r in old_runtime_records}:
                scientific_diffs.add(field)
                runtime_changes.add(field)
        historical_heterogeneous = [field for field in ['target_us', 'cycles', 'geometry', 'backends', 'compiler', 'version']
                                    if len({compact(r[field]) for r in old_runtime_records if r['mode'] == 'midcomm'}) > 1]
        status = ('no_dashboard_reference' if not references else
                  'parameter_mismatch' if scientific_diffs or other_setup_diffs else
                  'backend_only_difference' if 'backends' in runtime_changes else 'same_parameters')
        normalizations = sorted({r['normalization'] for r in historical[key]})
        row = dict(mpi=group['mpi'], payload=group['payload'], directory=group['directory'],
                   new_pairs=int(group['run_count']), new_scripts=len(new_paths),
                   new_runs=group['runs'], new_target_us=new['midcomm']['target_us'],
                   historical_target_us=compact(sorted(old_targets)), new_cycles=new['midcomm']['cycles'],
                   historical_cycles=compact(sorted(old_cycles)), status=status,
                   script_diff_fields=','.join(sorted(changed_fields)),
                   runtime_diff_fields=','.join(sorted(runtime_changes)),
                   historical_normalization=','.join(normalizations), new_normalization=group['normalization'],
                   historical_baselines_us=','.join(sorted({r['baseline_us'] for r in historical[key] if r['baseline_us']})),
                   historical_midcomm_runs=', '.join(sorted(run for mode, run in references if mode == 'midcomm')),
                   source_midcomm=item['source_midcomm'], source_no_midcomm=item['source_no_midcomm'],
                   source_midcomm_case_summaries=sum((Path(item['source_midcomm']).parent / f'Comb_{case}_summary.csv').is_file() for case in new['midcomm']['cases']),
                   source_no_midcomm_case_summaries=sum((Path(item['source_no_midcomm']).parent / f'Comb_{case}_summary.csv').is_file() for case in new['no_midcomm']['cases']),
                   historical_heterogeneous_fields=','.join(historical_heterogeneous),
                   all_new_scripts_byte_identical_to_source=all(r['byte_identical'] for r in group_scripts),
                   new_runtime_cases_checked=group_runtime_count,
                   new_runtime_errors=sum(r['runtime_errors'] for r in group_scripts),
                   historical_script_runtime_mismatches=len(historical_runtime_errors))
        groups.append(row)
        if status == 'parameter_mismatch':
            affected.extend(str(p) for p in new_paths)
        errors.extend(historical_runtime_errors)
        print(f"{group['mpi']:12} {group['payload']:12} {status}: target {sorted(old_targets)} -> {new['midcomm']['target_us']}, cycles {sorted(old_cycles)} -> {new['midcomm']['cycles']}", flush=True)

    summary = dict(groups=len(groups), scripts=len(script_rows),
                   pairs=sum(r['new_pairs'] for r in groups),
                   status_groups=dict(Counter(r['status'] for r in groups)),
                   status_pairs={status: sum(r['new_pairs'] for r in groups if r['status'] == status) for status in sorted({r['status'] for r in groups})},
                   parameter_mismatch_scripts=len(affected),
                   new_scripts_byte_identical_to_source=sum(r['byte_identical'] for r in script_rows),
                   source_hash_changes=source_changed,
                   new_runtime_cases_checked=sum(r['runtime_cases_checked'] for r in script_rows),
                   new_runtime_errors=sum(r['runtime_errors'] for r in script_rows),
                   historical_runtime_cases_checked=sum(r['origin'] == 'historical' for r in runtimes),
                   historical_script_runtime_mismatches=sum(r['historical_script_runtime_mismatches'] for r in groups),
                   zero_target_groups=sum(r['new_target_us'] == 0 for r in groups),
                   normalization_changed_groups=sum(bool(r['historical_normalization']) and r['historical_normalization'] != r['new_normalization'] for r in groups),
                   historical_heterogeneous_groups=sum(bool(r['historical_heterogeneous_fields']) for r in groups),
                   source_scripts_without_case_summaries=sum(not any(Path(p).parent.glob('Comb_*_summary.csv')) for p in sources),
                   limitation='Compares recorded arguments and declared MPI/binary/binding settings; does not prove identical binary contents, CPU placement or network conditions across dates. Historical references are current dashboard-selected runs, not an assumption that every old run is a valid baseline.')
    OUT.mkdir(exist_ok=True)
    for name, rows in [('groups.csv', groups), ('new_scripts.csv', script_rows)]:
        with (OUT / name).open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    for name, obj in [('summary.json', summary), ('differences.json', comparisons),
                      ('runtime_evidence.json', runtimes), ('errors.json', errors)]:
        (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    (OUT / 'parameter_mismatch_scripts.txt').write_text(''.join(p + '\n' for p in affected))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(OUT)


if __name__ == '__main__':
    main()
