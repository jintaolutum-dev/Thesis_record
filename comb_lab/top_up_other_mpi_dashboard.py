"""Generate Intel MPI / Intel MPI TCP / OpenMPI dashboard supplements only.

Reuse the Web writer and run-number helpers with the exact historical scripts as
templates. Only backend flags, approved binary paths and the known OpenMPI module
search path change. No submission and no dashboard data changes.
"""
import argparse
import copy
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from collections import defaultdict

from audit_inter_topup import BASE, ROOT, script_info, runtime_info, runtime_diffs
from core.generator import generate_job, _write_submit_all, TEMPLATE_MAP
from core.run_notes import create_run_notes
from viz.web_gui import _next_run_number, _apply_run_dir
from top_up_mpich_dashboard import sha, match, without_backends, script_args, mpionly, case_logs, SCRIPT_FIELDS

MPIS = ('intelmpi', 'intelmpi_tcp', 'openmpi')
DASH = ROOT / 'message-overlap-dashboard'
OPENMPI_MODULE_PATH = '/lrz/sys/spack/release/24.4.0/modules/MPI-icelake'


def normalized_logs(path):
    logs = case_logs(path)
    for value in logs.values():
        # Hostfiles contain the allocated nodes and have a per-launch temp name.
        value['launcher'] = re.sub(r'--hostfile\s+\S+', '--hostfile <allocated-hostfile>', value['launcher'])
    return logs


def prepare_group(mpi, message, points, decisions, temporary, input_hashes):
    directory = BASE / mpi / '2n2r_c24' / message
    key = mpi + '/' + message
    dashboard_runs = sorted({run for row in points for run in row['runs'].split(', ')})
    selected = decisions.get('reference_runs', {}).get(key, dashboard_runs)
    if len(selected) != len(set(selected)) or not selected or not set(selected) <= set(dashboard_runs):
        raise ValueError(f'Invalid reference-run selection: {key}')
    counts, original_counts = {}, {}
    for point in points:
        included = point['runs'].split(', ')
        if len(included) != len(set(included)) or len(included) != int(point['run_count']):
            raise ValueError(f'Invalid dashboard counts: {key}')
        case = point['policy'] + '/' + point['case']
        original_counts[case] = len(included)
        counts[case] = len(set(included) & set(selected))
    missing = max(0, 10 - min(counts.values()))
    group = dict(mpi=mpi, payload=points[0]['payload'], message=message,
                 dashboard_runs=', '.join(dashboard_runs), reference_runs=', '.join(selected),
                 incompatible_runs_not_counted=', '.join(sorted(set(dashboard_runs) - set(selected))),
                 dashboard_counts=json.dumps(original_counts, sort_keys=True),
                 compatible_counts=json.dumps(counts, sort_keys=True),
                 minimum_before=min(counts.values()), pairs_to_add=missing, scripts_to_add=2 * missing,
                 counts_after_success=json.dumps({case: n + missing for case, n in counts.items()}, sort_keys=True),
                 status='already_at_target' if not missing else 'ready', new_run_first='', new_run_last='',
                 midcomm_target_us='', cycles='', grid_size='', ghost='', vars='',
                 source_midcomm='', source_no_midcomm='', binary_relocated=False,
                 openmpi_module_path_added=False)
    if not missing:
        return group, [], [], {}
    bases, evidence, templates, mode_actual = [], [], {}, {}
    for mode in ('midcomm', 'no_midcomm'):
        sources = [directory / mode / run / 'run.sh' for run in selected]
        infos = [script_info(path) for path in sources]
        for info in infos[1:]:
            differences = [field for field in SCRIPT_FIELDS if info[field] != infos[0][field]]
            if differences:
                raise ValueError(f'Conflicting selected templates: {info["path"]}: {differences}')
        reference_actual, reference_logs = None, None
        for run, source, info in zip(selected, sources, infos):
            path = source.parent
            logs = normalized_logs(path)
            actual = {case: runtime_info(path / f'Comb_{case}_summary.csv') for case in logs}
            for case, value in actual.items():
                if runtime_diffs(info, value, case):
                    raise ValueError(f'Historical script/result disagree: {path}/{case}')
                if info['cases'][case]['label'] != logs[case]['label']:
                    raise ValueError(f'Historical async/thread label mismatch: {path}/{case}')
                if without_backends(script_args(source.read_text(), logs[case]['wait'])) != without_backends(value['args'].split(';')[1:]):
                    raise ValueError(f'Historical command/result disagree: {path}/{case}')
                if reference_actual:
                    ref = reference_actual[case]
                    for field in ('target_us', 'cycles', 'geometry', 'post_methods', 'omp', 'wait_methods', 'compiler', 'version'):
                        if value[field] != ref[field]:
                            raise ValueError(f'Conflicting selected result {field}: {path}/{case}')
                    if without_backends(value['args'].split(';')[1:]) != without_backends(ref['args'].split(';')[1:]):
                        raise ValueError(f'Conflicting selected arguments: {path}/{case}')
            if reference_logs and logs != reference_logs:
                raise ValueError(f'Conflicting launch/binding settings: {path}')
            reference_actual = reference_actual or actual
            reference_logs = reference_logs or logs
            evidence.append(dict(mpi=mpi, message=message, mode=mode, run=run, cases=actual, case_logs=logs))
            for original in [source, path / 'job_metadata.log']:
                input_hashes[str(original)] = sha(original)
        mode_actual[mode] = reference_actual
        source = sources[0]
        text = source.read_text()
        binary = infos[0]['binary']
        if binary in decisions.get('binary_relocations', {}):
            replacement = decisions['binary_relocations'][binary]
            text = text.replace(f'ln -sf {binary} ./comb', f'ln -sf {replacement} ./comb')
            binary = replacement
            group['binary_relocated'] = True
        if not os.access(binary, os.X_OK):
            raise ValueError(f'Executable inaccessible and no approved replacement: {binary}')
        text = mpionly(text)
        if mpi == 'openmpi':
            load = 'module load openmpi/4.1.8-intel24'
            if load not in text or not Path(OPENMPI_MODULE_PATH, 'openmpi/4.1.8-intel24').is_file():
                raise ValueError(f'Unverified OpenMPI module: {source}')
            directive = f'module use {OPENMPI_MODULE_PATH}'
            if directive not in text:
                text = text.replace(load, directive + '\n' + load)
                group['openmpi_module_path_added'] = True
        template_dir = temporary / 'templates' / mpi / message / mode
        template_dir.mkdir(parents=True)
        (template_dir / TEMPLATE_MAP[mpi]).write_text('{% raw %}' + text + '{% endraw %}')
        templates[mode] = template_dir
        job = dict(mpi={'name': mpi, 'binary': binary}, compute_mode={'name': mode, 'backend_mode': 'mpi_only'},
                   grid={'cycles': reference_actual['00']['cycles'], 'compute_target_us': reference_actual['00']['target_us']},
                   job_name=match(text, r'^#SBATCH -J (.+)$'), output_dir=str(directory / mode))
        rendered = generate_job(dict(job, output_dir=str(temporary / 'rendered' / mpi / message / mode)), templates_dir=template_dir)
        if rendered.read_text() != text:
            raise ValueError('Template rendering changed source body')
        output_info = script_info(rendered)
        for case, actual in reference_actual.items():
            if set(runtime_diffs(output_info, actual, case)) - {'backends'}:
                raise ValueError(f'Generated parameters differ: {key}/{mode}/{case}')
            if without_backends(script_args(text, reference_logs[case]['wait'])) != without_backends(actual['args'].split(';')[1:]):
                raise ValueError(f'Generated arguments differ: {key}/{mode}/{case}')
            if output_info['cases'][case]['label'] != reference_logs[case]['label']:
                raise ValueError(f'Generated Case changed: {key}/{mode}/{case}')
        subprocess.run(['bash', '-n', str(rendered)], check=True)
        group['source_' + mode] = str(source)
        bases.append(job)
    for case, a in mode_actual['midcomm'].items():
        b = mode_actual['no_midcomm'][case]
        if b['target_us'] != 0 or any(a[field] != b[field] for field in ('cycles', 'geometry', 'omp', 'wait_methods', 'post_methods')):
            raise ValueError(f'Inconsistent mid/no pair: {key}/{case}')
    ref = mode_actual['midcomm']['00']
    group.update(midcomm_target_us=ref['target_us'], cycles=ref['cycles'], grid_size=ref['geometry']['GRID_SIZE'],
                 ghost=ref['geometry']['GHOST'], vars=ref['geometry']['VARS'])
    planned, names = [], []
    number = _next_run_number(bases)
    for _ in range(missing):
        while any((Path(job['output_dir']) / f'run_{number:03d}_MPIonly').exists() for job in bases):
            number += 1
        pair = copy.deepcopy(bases)
        names.append(_apply_run_dir(pair, number, 'mpi_only'))
        planned.extend((mpi, message, mode, job) for mode, job in zip(('midcomm', 'no_midcomm'), pair))
        number += 1
    group['new_run_first'], group['new_run_last'] = names[0], names[-1]
    return group, planned, evidence, templates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--decisions', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    options = parser.parse_args()
    report = options.report_dir.resolve()
    if report.exists():
        raise FileExistsError(report)
    decisions = json.loads(options.decisions.read_text())
    input_hashes = {str(options.decisions.resolve()): sha(options.decisions)}
    groups = defaultdict(list)
    for name, policy in [('overlap-current.csv', 'seq'), ('resources-current.csv', 'omp')]:
        path = DASH / name
        input_hashes[str(path)] = sha(path)
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row['mpi'] in MPIS:
                    groups[row['mpi'], row['directory']].append(dict(row, policy=policy))
    if len(groups) != 57:
        raise ValueError('Expected 19 dashboard message sizes for each of three MPIs')
    inventory, planned, evidence, templates, issues = [], [], [], {}, []
    with tempfile.TemporaryDirectory(prefix='other_mpi_dashboard_', dir='/tmp') as scratch:
        for (mpi, message), points in groups.items():
            try:
                group, jobs, records, sources = prepare_group(mpi, message, points, decisions, Path(scratch), input_hashes)
            except (ValueError, OSError, KeyError) as exc:
                issues.append(dict(mpi=mpi, message=message, payload=points[0]['payload'], error=str(exc)))
                print(f'BLOCKED {mpi} {points[0]["payload"]}: {exc}', flush=True)
                continue
            inventory.append(group)
            planned.extend(jobs)
            evidence.extend(records)
            templates.update({(mpi, message, mode): path for mode, path in sources.items()})
            print(f"{mpi} {group['payload']}: {group['minimum_before']} + {group['pairs_to_add']} pairs; {group['midcomm_target_us']} us / {group['cycles']} cycles", flush=True)
        for path, digest in input_hashes.items():
            if sha(Path(path)) != digest:
                raise ValueError(f'Input changed during validation: {path}')
        targets = [Path(job['output_dir']) / 'run.sh' for _, _, _, job in planned]
        if len(targets) != len(set(targets)) or any(path.parent.exists() for path in targets):
            raise ValueError('Duplicate or occupied output directory')
        report.mkdir(parents=True, exist_ok=False)
        summary = dict(scope='cm4_inter / 2n2r_c24 / intelmpi,intelmpi_tcp,openmpi / dashboard-selected runs',
                       count_basis='Minimum compatible dashboard-included paired count across seq/omp cases; retain case exclusions',
                       groups_scanned=len(groups), groups_validated=len(inventory), blocked_groups=len(issues),
                       groups_to_top_up=sum(r['pairs_to_add'] > 0 for r in inventory),
                       pairs_to_generate=len(targets)//2, scripts_to_generate=len(targets),
                       binary_relocated_groups=sum(r['binary_relocated'] for r in inventory),
                       openmpi_module_path_groups=sum(r['openmpi_module_path_added'] for r in inventory),
                       by_mpi={mpi: dict(groups_to_top_up=sum(r['mpi'] == mpi and r['pairs_to_add'] > 0 for r in inventory),
                                        pairs=sum(r['pairs_to_add'] for r in inventory if r['mpi'] == mpi)) for mpi in MPIS},
                       applied=options.apply, submitted_jobs=0)
        for name, value in [('summary.json', summary), ('input_hashes.json', input_hashes), ('decisions.json', decisions),
                            ('jobs.json', [job for _, _, _, job in planned]), ('reference_evidence.json', evidence), ('issues.json', issues)]:
            (report / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        with (report / 'inventory.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(inventory[0]))
            writer.writeheader()
            writer.writerows(inventory)
        (report / 'new_scripts.txt').write_text(''.join(str(path) + '\n' for path in targets))
        for mpi in MPIS:
            (report / f'new_scripts_{mpi}.txt').write_text(''.join(str(path) + '\n' for path in targets if path.parts[-6] == mpi))
        if options.apply:
            hashes = {}
            for (mpi, message, mode, job), path in zip(planned, targets):
                path.parent.mkdir(parents=True, exist_ok=False)
                if generate_job(job, templates_dir=templates[mpi, message, mode]) != path:
                    raise ValueError('Unexpected generated path')
                subprocess.run(['bash', '-n', str(path)], check=True)
                hashes[str(path)] = sha(path)
            notes = create_run_notes([job for _, _, _, job in planned])
            if targets:
                submit = _write_submit_all(report, targets)
                subprocess.run(['bash', '-n', str(submit)], check=True)
            for (mpi, message, mode), template_dir in templates.items():
                dest = report / 'templates' / mpi / message / mode
                dest.mkdir(parents=True)
                (dest / TEMPLATE_MAP[mpi]).write_bytes((template_dir / TEMPLATE_MAP[mpi]).read_bytes())
            if any(sha(Path(path)) != digest for path, digest in input_hashes.items()):
                raise ValueError('Existing inputs modified')
            (report / 'verification.json').write_text(json.dumps(dict(scripts_syntax_checked=len(targets),
                reference_run_modes_checked=len(evidence), source_inputs_unchanged=len(input_hashes), shared_notes=len(notes),
                submitted_jobs=0, generated_hashes=hashes), indent=2) + '\n')
        print(json.dumps(summary, indent=2))
        print(report)


if __name__ == '__main__':
    main()
