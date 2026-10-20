"""Merge only completed, parameter-matched runs from the two approved batches."""
import csv
import hashlib
import json
import re
from pathlib import Path

from audit_inter_topup import script_info, runtime_info, runtime_diffs
from top_up_mpich_dashboard import case_logs, without_backends


def normalized_logs(path):
    logs = case_logs(path)
    for case in logs.values():
        case['launcher'] = re.sub(r'--hostfile\s+\S+', '--hostfile <allocated-hostfile>', case['launcher'])
    return logs


def include_completed(selected, base):
    root = Path(__file__).resolve().parent
    batches = json.loads((root / 'completed-batches.json').read_text())
    seen = set()
    for batch_name in batches:
        batch = base / batch_name
        hashes = json.loads((batch / 'verification.json').read_text())['generated_hashes']
        scripts = [Path(s) for s in (batch / 'new_scripts.txt').read_text().splitlines()]
        if len(scripts) != len(set(scripts)) or set(map(str, scripts)) != set(hashes):
            raise ValueError(f'Changed batch manifest: {batch}')
        groups = {}
        for path in scripts:
            mpi, topology, message, mode, run, filename = path.parts[-6:]
            if topology != '2n2r_c24' or filename != 'run.sh' or not re.fullmatch(r'run_\d+_MPIonly', run):
                raise ValueError(f'Unexpected supplement path: {path}')
            if path != base / mpi / topology / message / mode / run / filename:
                raise ValueError(f'Unexpected supplement root: {path}')
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[str(path)]:
                raise ValueError(f'Generated script changed: {path}')
            groups.setdefault((mpi, message), {}).setdefault(run, set()).add(mode)
        decisions = json.loads((batch / 'decisions.json').read_text()) if (batch / 'decisions.json').exists() else {}
        inventory = list(csv.DictReader((batch / 'inventory.csv').open()))
        for row in inventory:
            if not int(row['pairs_to_add']):
                continue
            key = row.get('mpi', 'mpich'), row['message']
            if key in seen:
                raise ValueError(f'Duplicate completed group: {key}')
            seen.add(key)
            entry = selected[key]
            previous = row['dashboard_runs'].split(', ')
            old = row.get('reference_runs', row['dashboard_runs']).split(', ')
            added = sorted(groups[key])
            if (set(entry['run_names']) != set(previous) or not set(old) <= set(previous)
                    or len(set(old + added)) != len(old + added)
                    or len(added) != int(row['pairs_to_add'])
                    or any(modes != {'midcomm', 'no_midcomm'} for modes in groups[key].values())):
                raise ValueError(f'Changed cohort or incomplete pairs: {key}')
            if set(old) != set(previous) and decisions.get('reference_runs', {}).get('/'.join(key)) != old:
                raise ValueError(f'Unapproved historical exclusion: {key}')
            directory = base / key[0] / '2n2r_c24' / key[1]
            for mode in ('midcomm', 'no_midcomm'):
                originals = {run: {f'{c:02d}': runtime_info(directory / mode / run / f'Comb_{c:02d}_summary.csv')
                                   for c in range(10)} for run in old}
                reference_logs = normalized_logs(directory / mode / old[0])
                for run in added:
                    path = directory / mode / run
                    script = script_info(path / 'run.sh')
                    if script['backends'] != ['mpi'] or not script['backends_explicit']:
                        raise ValueError(f'Unexpected backend: {path}')
                    logs = sorted(path.glob('run.*.out'), key=lambda p: p.stat().st_mtime)
                    output = logs[-1].read_text() if logs else ''
                    exits = re.findall(r'^===== (\d+)_\S+ exit code: (-?\d+) =====$', output, re.M)
                    if ([case for case, _ in exits] != [f'{c:02d}' for c in range(10)]
                            or any(code != '0' for _, code in exits) or 'All cases done.' not in output):
                        raise ValueError(f'Incomplete completed supplement: {path}')
                    if normalized_logs(path) != reference_logs:
                        raise ValueError(f'Launch/binding settings changed: {path}')
                    for case in script['cases']:
                        actual = runtime_info(path / f'Comb_{case}_summary.csv')
                        if runtime_diffs(script, actual, case):
                            raise ValueError(f'Script/result mismatch: {path}/{case}')
                        for old_run, cases in originals.items():
                            original = cases[case]
                            fields = ('target_us', 'cycles', 'geometry', 'post_methods', 'omp', 'wait_methods', 'compiler', 'version')
                            differences = [field for field in fields if actual[field] != original[field]]
                            if differences or without_backends(actual['args'].split(';')[1:]) != without_backends(original['args'].split(';')[1:]):
                                raise ValueError(f'Historical parameter mismatch: {path}/{case} vs {old_run}: {differences}')
            entry['run_names'] = old + added
            entry['added_runs'] = added
            entry['excluded_incompatible_runs'] = sorted(set(previous) - set(old))
            if not entry['source'].endswith('+supplement'):
                entry['source'] += '+supplement'
        if set(groups) != {(r.get('mpi', 'mpich'), r['message']) for r in inventory if int(r['pairs_to_add'])}:
            raise ValueError(f'Unaccounted batch groups: {batch}')
    return selected


def cohort_counts(entry, runs):
    added = set(entry.get('added_runs', []))
    return dict(previous_run_count=sum(run not in added for run in runs),
                added_run_count=sum(run in added for run in runs))
