"""Validate the explicitly approved MPIonly supplements before combining cohorts."""
import json
import re
from pathlib import Path

from audit_inter_topup import script_info, runtime_info, runtime_diffs


def include_supplements(selected, base, config_path=None):
    config_path = config_path or Path(__file__).with_name('approved-supplements.json')
    approvals = json.loads(config_path.read_text())
    seen = set()
    for approved in approvals:
        key = (approved['mpi'], approved['directory'])
        if key in seen:
            raise ValueError(f'Duplicate supplement group: {key}')
        seen.add(key)
        entry = selected[key]
        old, added = approved['historical_runs'], approved['supplement_runs']
        if entry['run_names'] != old or len(set(old + added)) != len(old + added):
            raise ValueError(f'Changed historical cohort or duplicate run: {key}')
        # These approvals extend original measured-compute cohorts only.
        if entry['source'] != 'original' or entry['baseline_us'] is not None or entry['expected']:
            raise ValueError(f'Unexpected normalization / retest cohort: {key}')
        directory = base / approved['mpi'] / '2n2r_c24' / approved['directory']
        for mode in ['midcomm', 'no_midcomm']:
            reference = script_info(directory / mode / old[0] / 'run.sh')
            for run in added:
                if not re.fullmatch(r'run_\d+_MPIonly', run):
                    raise ValueError(f'Not an MPIonly supplement: {run}')
                path = directory / mode / run
                script = script_info(path / 'run.sh')
                for field in ['target_us', 'cycles', 'geometry', 'modules', 'protocol_env', 'binary',
                              'resources', 'post_methods', 'cases', 'launcher_sha256']:
                    if script[field] != reference[field]:
                        raise ValueError(f'Supplement changes {field}: {path}')
                if script['backends'] != ['mpi'] or not script['backends_explicit']:
                    raise ValueError(f'Unexpected backend: {path}')
                logs = sorted(path.glob('run.*.out'), key=lambda p: p.stat().st_mtime)
                log = logs[-1].read_text() if logs else ''
                exits = re.findall(r'^===== (\d+)_\S+ exit code: (-?\d+) =====$', log, re.M)
                if ([case for case, _ in exits] != list(script['cases']) or
                        any(code != '0' for _, code in exits) or 'All cases done.' not in log):
                    raise ValueError(f'Incomplete supplement: {path}')
                for case in script['cases']:
                    actual = runtime_info(path / f'Comb_{case}_summary.csv')
                    if runtime_diffs(script, actual, case):
                        raise ValueError(f'Result does not match supplement script: {path}/{case}')
                    for old_run in old:
                        original = runtime_info(directory / mode / old_run / f'Comb_{case}_summary.csv')
                        # MPI-only is the explicitly requested backend change.
                        if set(runtime_diffs(script, original, case)) - {'backends'}:
                            raise ValueError(f'Result differs from historical parameters: {path}/{case}')
                        if any(actual[field] != original[field] for field in ['compiler', 'version']):
                            raise ValueError(f'Compiler/version differs: {path}/{case}')
        entry['run_names'] = old + added
        entry['source'] = 'original+supplement'
    return selected
