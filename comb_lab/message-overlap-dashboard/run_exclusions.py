"""Apply explicit user-selected whole-pair exclusions to dashboard statistics."""
import json
from pathlib import Path


def apply_exclusions(selected):
    config = json.loads(Path(__file__).with_name('run-exclusions.json').read_text())
    seen = set()
    for rule in config:
        key = rule['mpi'], rule['directory']
        run = rule['run']
        identity = (*key, run)
        if identity in seen or rule['scope'] != 'all_cases_all_policies':
            raise ValueError(f'Duplicate or unsupported exclusion: {rule}')
        seen.add(identity)
        entry = selected[key]
        if run not in entry['run_names']:
            raise ValueError(f'Excluded run is absent from selected cohort: {identity}')
        entry.setdefault('run_names_before_filter', list(entry['run_names']))
        entry.setdefault('user_excluded_runs', []).append(run)
        entry['run_names'] = [name for name in entry['run_names'] if name != run]
        if not entry['run_names']:
            raise ValueError(f'No included runs remain: {key}')
    return selected
