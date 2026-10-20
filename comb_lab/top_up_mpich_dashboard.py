"""Generate paired MPICH MPIonly supplements from the dashboard's actual runs.

Preserve historical script bodies, changing only backend selection and explicitly
approved binary relocation. Reconstruct missing scripts from recorded arguments
with the shared Web generator. Never submit jobs or overwrite existing runs.
"""
import argparse
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from collections import defaultdict

from audit_inter_topup import BASE, ROOT, script_info, runtime_info, runtime_diffs
from core.generator import generate_job, _write_submit_all
from core.matrix import expand_matrix, load_config
from core.run_notes import create_run_notes
from viz.web_gui import _next_run_number, _apply_run_dir, _with_cluster_profile

DASH = ROOT / 'message-overlap-dashboard'
OLD_BINARY = '/dss/dsshome1/08/ge63neh2/comb_with_compute/build_3_mpich_dummy_OMP/bin/comb'
NEW_BINARY = str(ROOT.parent / 'comb_with_compute/build_3_mpich_dummy_OMP/bin/comb')
SCRIPT_FIELDS = ['target_us', 'cycles', 'geometry', 'modules', 'protocol_env', 'binary',
                 'resources', 'post_methods', 'cases', 'launcher_sha256']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def match(text, pattern):
    found = re.search(pattern, text, re.M)
    if not found:
        raise ValueError(f'Missing field: {pattern}')
    return found[1]


def without_backends(tokens):
    result = []
    i = 0
    while i < len(tokens):
        if tokens[i] == '-comm' and tokens[i + 1] in ('enable', 'disable'):
            i += 3
        else:
            result.append(tokens[i])
            i += 1
    return result


def script_args(text, wait):
    body = re.search(r'_comb_args\(\).*?echo "(.*?)"\n}', text, re.S)[1]
    variables = dict(re.findall(r'^(\w+)="([^"\n]*)"$', text, re.M))
    variables.update(dict(re.findall(r'^(\w+)=(\d+)$', text, re.M)))
    variables['wait_mode'] = wait
    body = re.sub(r'\$\{(\w+)\}', lambda m: variables[m[1]], body)
    return shlex.split(body.replace('\\\n', ' '))


def mpionly(text):
    # Keep all other shell commands, including historical launch/binding logic.
    text = re.sub(r'^-comm (?:enable|disable) \w+[^\n]*\n', '', text, flags=re.M)
    anchor = '-comm post_recv '
    if text.count(anchor) != 1:
        raise ValueError('Ambiguous backend insertion point')
    return text.replace(anchor, '-comm disable all \\\n-comm enable mpi \\\n' + anchor)


def metadata(path):
    return dict(re.findall(r'^(\w+)=(.*)$', path.read_text(), re.M))


def case_logs(path):
    result = {}
    for log in sorted(path.glob('[0-9][0-9]_async*.log')):
        label = log.stem
        case, asynchronous, at, omp, wait = re.fullmatch(r'(\d+)_async([01])_(?:at(\d+)_)?c(\d+)_(\w+)', label).groups()
        text = log.read_text()
        result[case] = dict(async_flag=int(asynchronous), async_threads=int(at) if at else None,
                            omp=int(omp), wait=wait, label=label,
                            launcher=match(text, r'^launcher=(.+)$'),
                            binding_mode=match(text, r'^binding_mode=(.+)$'))
    if list(result) != [f'{n:02d}' for n in range(10)]:
        raise ValueError(f'Missing case logs: {path}')
    return result


def recover_missing(directory, mode, run, actual, logs, config, temporary):
    """Use original result/metadata settings, never current YAML timing defaults."""
    path = directory / mode / run
    meta = metadata(path / 'job_metadata.log')
    cfg = _with_cluster_profile(copy.deepcopy(config), 'cm4_inter', None)
    mpi = cfg['mpi_impl']['mpich']
    cfg['mpi_impl'] = {'mpich': mpi}
    mpi.pop('cases', None)
    mpi['compute_target_us'] = {}
    mpi['binary'] = meta['comb_binary_realpath']
    # Recorded local MPICH prefix and transport must agree with the Web config.
    evidence = (path / 'job_metadata.log').read_text()
    if 'MPICH Version:    4.2.2' not in evidence and not re.search(r'MPICH Version:\s+4\.2\.2', evidence):
        raise ValueError(f'Unverified MPICH version: {path}')
    if 'FI_PROVIDER=tcp' not in evidence or '/local_software/mpich-4.2.2-gcc-spr' not in evidence:
        raise ValueError(f'Unverified MPICH transport/prefix: {path}')
    topo = next(copy.deepcopy(t) for t in cfg['topology'] if t['name'] == '2n2r_c24')
    topo.update(nodes=int(meta['nodes']), ntasks_per_node=int(meta['ntasks_per_node']), divide=meta['divide'], compute_target_us={})
    cfg['topology'] = [topo]
    cfg.pop('grid_by_topology', None)
    g = actual['00']['geometry']
    cfg['grid'] = {'custom': dict(size=g['GRID_SIZE'], ghost=g['GHOST'], periodic=g['PERIODIC'],
                                vars=int(g['VARS']), cutoff=int(g['COMM_CUTOFF']),
                                compute_target_us=actual['00']['target_us'], cycles=actual['00']['cycles'])}
    cfg['compute_mode'] = {mode: {'backend_mode': 'mpi_only'}}
    cfg['slurm'].pop('total_cpus_per_job', None)
    for field in ['clusters', 'partition', 'qos']:
        cfg['slurm'][field] = meta[field]
    cfg['slurm'].update(cpus_per_task=int(meta['cpus_per_task_request']), runtime_cpus_per_rank=int(meta['runtime_cpus_per_rank']), time='00:30:00')
    cfg['cases'] = []
    for case in logs.values():
        item = {'async': case['async_flag'], 'omp_threads': case['omp'], 'wait_mode': case['wait']}
        if case['async_threads'] is not None:
            item['async_threads'] = case['async_threads']
        cfg['cases'].append(item)
    cfg['exclude'] = []
    cfg['comm'] = {'post_recv': actual['00']['post_methods'][0], 'post_send': actual['00']['post_methods'][1]}
    jobs = expand_matrix(cfg)
    if len(jobs) != 1:
        raise ValueError('Ambiguous recovered matrix')
    job = jobs[0]
    job['output_dir'] = str(temporary / mode)
    script = generate_job(job)
    return script.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-binary-relocation', action='store_true')
    parser.add_argument('--report-dir', type=Path, required=True)
    options = parser.parse_args()
    report = options.report_dir.resolve()
    if report.exists():
        raise FileExistsError(report)
    config = load_config(ROOT / 'config/comb_cm4.yaml')
    groups = defaultdict(list)
    input_hashes = {}
    for name, policy in [('overlap-current.csv', 'seq'), ('resources-current.csv', 'omp')]:
        path = DASH / name
        input_hashes[str(path)] = sha(path)
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row['mpi'] == 'mpich':
                    groups[row['directory']].append(dict(row, policy=policy))
    if len(groups) != 19:
        raise ValueError('Unexpected dashboard MPICH scope')
    inventory, planned, evidence, templates = [], [], [], {}
    with tempfile.TemporaryDirectory(prefix='mpich_dashboard_validate_', dir='/tmp') as scratch:
        temporary = Path(scratch)
        for message, points in groups.items():
            directory = BASE / 'mpich/2n2r_c24' / message
            counts = {f"{row['policy']}/{row['case']}": int(row['run_count']) for row in points}
            for row in points:
                if len(set(row['runs'].split(', '))) != int(row['run_count']):
                    raise ValueError('Dashboard count does not match run list')
            missing = max(0, 10 - min(counts.values()))
            runs = sorted({run for row in points for run in row['runs'].split(', ')})
            group = dict(payload=points[0]['payload'], message=message, dashboard_runs=', '.join(runs),
                         counts_before=json.dumps(counts, sort_keys=True), minimum_before=min(counts.values()),
                         pairs_to_add=missing, scripts_to_add=2 * missing,
                         counts_after_success=json.dumps({k: n + missing for k, n in counts.items()}, sort_keys=True),
                         new_run_first='', new_run_last='', midcomm_target_us='', cycles='',
                         source_midcomm='', source_no_midcomm='', binary_relocated=False, reconstructed=False)
            bases = []
            mode_actual = {}
            for mode in ['midcomm', 'no_midcomm']:
                existing = [directory / mode / run / 'run.sh' for run in runs if (directory / mode / run / 'run.sh').is_file()]
                infos = [script_info(path) for path in existing]
                if infos:
                    for info in infos[1:]:
                        differences = [field for field in SCRIPT_FIELDS if info[field] != infos[0][field]]
                        if differences:
                            raise ValueError(f'Conflicting dashboard scripts: {info["path"]}: {differences}')
                reference_actual, reference_logs = None, None
                for run in runs:
                    path = directory / mode / run
                    logs = case_logs(path)
                    actual = {case: runtime_info(path / f'Comb_{case}_summary.csv') for case in logs}
                    for case, value in actual.items():
                        if value['omp'] != logs[case]['omp'] or value['wait_methods'] != [logs[case]['wait']] * 2:
                            raise ValueError(f'Case log and result disagree: {path}/{case}')
                        if reference_actual:
                            ref = reference_actual[case]
                            for field in ['target_us', 'cycles', 'geometry', 'post_methods', 'omp', 'wait_methods', 'compiler', 'version']:
                                if value[field] != ref[field]:
                                    raise ValueError(f'Conflicting dashboard results {field}: {path}/{case}')
                            if without_backends(value['args'].split(';')[1:]) != without_backends(ref['args'].split(';')[1:]):
                                raise ValueError(f'Different command arguments: {path}/{case}')
                    if reference_logs and logs != reference_logs:
                        raise ValueError(f'Conflicting launcher/case logs: {path}')
                    reference_actual, reference_logs = reference_actual or actual, reference_logs or logs
                    evidence.append(dict(directory=message, mode=mode, run=run,
                                         cases={case: {k: v for k, v in value.items() if k != 'path'} for case, value in actual.items()},
                                         case_logs=logs))
                    for f in [path / 'run.sh', path / 'job_metadata.log']:
                        if f.is_file():
                            input_hashes[str(f)] = sha(f)
                mode_actual[mode] = reference_actual
                if not missing:
                    continue
                source = existing[0] if existing else directory / mode / runs[0] / 'job_metadata.log'
                if existing:
                    text = source.read_text()
                else:
                    text = recover_missing(directory, mode, runs[0], reference_actual, reference_logs, config, temporary / message)
                    group['reconstructed'] = True
                binary = match(text, r'^ln -sf (\S+) ./comb$')
                if binary == OLD_BINARY:
                    if not options.allow_binary_relocation:
                        raise ValueError('Binary relocation requires explicit approval')
                    text = text.replace(f'ln -sf {OLD_BINARY} ./comb', f'ln -sf {NEW_BINARY} ./comb')
                    binary = NEW_BINARY
                    group['binary_relocated'] = True
                if not os.access(binary, os.X_OK):
                    raise ValueError(f'Binary unavailable: {binary}')
                text = mpionly(text)
                for case, actual in reference_actual.items():
                    if without_backends(script_args(text, reference_logs[case]['wait'])) != without_backends(actual['args'].split(';')[1:]):
                        raise ValueError(f'Generated command differs from dashboard run: {message}/{mode}/{case}')
                template_dir = temporary / 'templates' / message / mode
                template_dir.mkdir(parents=True)
                (template_dir / 'comb_mpich.slurm.j2').write_text('{% raw %}' + text + '{% endraw %}')
                templates[message, mode] = template_dir
                job = dict(mpi={'name': 'mpich', 'binary': binary}, compute_mode={'name': mode, 'backend_mode': 'mpi_only'},
                           grid={'cycles': reference_actual['00']['cycles'], 'compute_target_us': reference_actual['00']['target_us']},
                           job_name=match(text, r'^#SBATCH -J (.+)$'), output_dir=str(directory / mode))
                test_job = dict(job, output_dir=str(temporary / 'rendered' / message / mode))
                rendered = generate_job(test_job, templates_dir=template_dir)
                if rendered.read_text() != text:
                    raise ValueError('Source template rendering changes script body')
                output_info = script_info(rendered)
                for case, actual in reference_actual.items():
                    if output_info['cases'][case]['label'] != reference_logs[case]['label']:
                        raise ValueError(f'Async/thread Case label differs: {message}/{mode}/{case}')
                    if set(runtime_diffs(output_info, actual, case)) - {'backends'}:
                        raise ValueError(f'Generated configuration differs from original result: {message}/{mode}/{case}')
                subprocess.run(['bash', '-n', str(rendered)], check=True)
                group['source_' + mode] = str(source)
                bases.append(job)
            for case in mode_actual['midcomm']:
                a, b = mode_actual['midcomm'][case], mode_actual['no_midcomm'][case]
                if b['target_us'] != 0 or any(a[field] != b[field] for field in ['cycles', 'geometry', 'omp', 'wait_methods', 'post_methods']):
                    raise ValueError(f'Inconsistent mid/no pair: {message}/{case}')
            group['midcomm_target_us'] = mode_actual['midcomm']['00']['target_us']
            group['cycles'] = mode_actual['midcomm']['00']['cycles']
            if missing:
                number = _next_run_number(bases)
                names = []
                for _ in range(missing):
                    while any((Path(job['output_dir']) / f'run_{number:03d}_MPIonly').exists() for job in bases):
                        number += 1
                    pair = copy.deepcopy(bases)
                    name = _apply_run_dir(pair, number, 'mpi_only')
                    names.append(name)
                    planned.extend((message, mode, job) for mode, job in zip(['midcomm', 'no_midcomm'], pair))
                    number += 1
                group['new_run_first'], group['new_run_last'] = names[0], names[-1]
            inventory.append(group)
            print(f"{group['payload']}: minimum {min(counts.values())}, add {missing} pairs; target {group['midcomm_target_us']} us, cycles {group['cycles']}", flush=True)
        for path, digest in input_hashes.items():
            if sha(Path(path)) != digest:
                raise ValueError(f'Input changed during planning: {path}')
        targets = [Path(job['output_dir']) / 'run.sh' for _, _, job in planned]
        if len(set(targets)) != len(targets) or any(path.parent.exists() for path in targets):
            raise ValueError('Duplicate or occupied destination')
        report.mkdir(parents=True, exist_ok=False)
        summary = dict(scope='cm4_inter / 2n2r_c24 / MPICH / dashboard-selected message sizes',
                       count_basis='Minimum dashboard-included valid paired-run count across seq/omp cases; preserve exclusions',
                       groups=len(inventory), groups_to_top_up=sum(r['pairs_to_add'] > 0 for r in inventory),
                       pairs_to_generate=len(targets)//2, scripts_to_generate=len(targets),
                       binary_relocated_groups=sum(r['binary_relocated'] for r in inventory),
                       reconstructed_groups=sum(r['reconstructed'] for r in inventory),
                       applied=options.apply, submitted_jobs=0)
        for name, value in [('summary.json', summary), ('input_hashes.json', input_hashes),
                            ('jobs.json', [job for _, _, job in planned]), ('reference_evidence.json', evidence)]:
            (report / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        with (report / 'inventory.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(inventory[0]))
            writer.writeheader()
            writer.writerows(inventory)
        (report / 'new_scripts.txt').write_text(''.join(str(path) + '\n' for path in targets))
        if options.apply:
            generated_hashes = {}
            for (message, mode, job), path in zip(planned, targets):
                path.parent.mkdir(parents=True, exist_ok=False)
                generated = generate_job(job, templates_dir=templates[message, mode])
                if generated != path:
                    raise ValueError('Output path changed')
                subprocess.run(['bash', '-n', str(path)], check=True)
                generated_hashes[str(path)] = sha(path)
            notes = create_run_notes([job for _, _, job in planned])
            submit = _write_submit_all(report, targets)
            subprocess.run(['bash', '-n', str(submit)], check=True)
            for key, template_dir in templates.items():
                destination = report / 'templates' / key[0] / key[1]
                destination.mkdir(parents=True)
                (destination / 'comb_mpich.slurm.j2').write_bytes((template_dir / 'comb_mpich.slurm.j2').read_bytes())
            if any(sha(Path(path)) != digest for path, digest in input_hashes.items()):
                raise ValueError('Existing input modified')
            (report / 'verification.json').write_text(json.dumps(dict(scripts_syntax_checked=len(targets),
                dashboard_groups_checked=len(inventory), reference_run_modes_checked=len(evidence),
                source_inputs_unchanged=len(input_hashes), shared_notes=len(notes), submitted_jobs=0,
                generated_hashes=generated_hashes), indent=2) + '\n')
        print(json.dumps(summary, indent=2))
        print(report)


if __name__ == '__main__':
    main()
