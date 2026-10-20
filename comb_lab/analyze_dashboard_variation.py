"""Screen the updated dashboard's actual included runs; never exclude results."""
import csv
import hashlib
import json
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from statistics import median, mean, stdev
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DASH = ROOT / 'message-overlap-dashboard'
OUT = DASH / 'variation-audit-20261020'


def write_csv(name, rows):
    with (OUT / name).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    cohorts = {(e['mpi'], e['directory']): set(e.get('added_runs') or [])
               for e in json.loads((DASH / 'cohorts.json').read_text())}
    groups = defaultdict(list)
    inputs = ['cohorts.json', 'overlap-runs-current.csv', 'resources-runs-current.csv']
    for filename, policy in [('overlap-runs-current.csv', 'seq/seq/seq'), ('resources-runs-current.csv', 'omp/seq/seq')]:
        for row in csv.DictReader((DASH / filename).open()):
            for field in ('overlap', 'wait_no_us', 'wait_mid_us', 'compute_us', 'denominator_us', 'bench_mid'):
                row[field] = float(row[field])
            row['origin'] = 'new_supplement' if row['run'] in cohorts[row['mpi'], row['directory']] else 'previous_dashboard'
            groups[policy, row['mpi'], row['directory'], row['case']].append(row)
    summaries, samples, candidates = [], [], []
    for (policy, mpi, directory, case), rows in groups.items():
        assert len(rows) == int(rows[0]['run_count']) == len({r['run'] for r in rows})
        values = [r['overlap'] for r in rows]
        center = median(values)
        mad = median(abs(v - center) for v in values)
        low, high = min(rows, key=lambda r: r['overlap']), max(rows, key=lambda r: r['overlap'])
        meta = dict(policy=policy, mpi=mpi, payload=rows[0]['payload'], directory=directory, case=case, run_count=len(rows))
        flagged = []
        for row in rows:
            deviation = abs(row['overlap'] - center)
            # A screening rule, not a significance test or deletion criterion.
            threshold = max(20.0, 3.5 * 1.4826 * mad)
            flag = deviation > threshold
            base = ROOT / 'generated/cm4_inter' / mpi / '2n2r_c24' / directory
            item = dict(meta, run=row['run'], origin=row['origin'], overlap_pct=row['overlap'],
                        median_overlap_pct=center, deviation_pp=deviation,
                        candidate=flag, threshold_pp=threshold, mad_pp=mad,
                        wait_no_us=row['wait_no_us'], wait_mid_us=row['wait_mid_us'],
                        median_wait_no_us=median(r['wait_no_us'] for r in rows),
                        median_wait_mid_us=median(r['wait_mid_us'] for r in rows),
                        compute_us=row['compute_us'], median_compute_us=median(r['compute_us'] for r in rows),
                        denominator_us=row['denominator_us'], normalization=row['normalization'],
                        cycles=row['cycles'], midcomm_runtime_s=row['bench_mid'],
                        mean_overlap_pct=mean(values),
                        mean_without_this_run_pct=mean(r['overlap'] for r in rows if r['run'] != row['run']),
                        midcomm_summary=str(base / 'midcomm' / row['run'] / f'Comb_{case}_summary.csv'),
                        no_midcomm_summary=str(base / 'no_midcomm' / row['run'] / f'Comb_{case}_summary.csv'))
            samples.append(item)
            if flag:
                candidates.append(item)
                flagged.append(row['run'])
        old = [r['overlap'] for r in rows if r['origin'] == 'previous_dashboard']
        new = [r['overlap'] for r in rows if r['origin'] == 'new_supplement']
        summary = dict(meta, minimum_pct=low['overlap'], maximum_pct=high['overlap'],
                       range_pp=max(values)-min(values), sample_sd_pp=stdev(values),
                       median_pct=center, mean_pct=mean(values), mad_pp=mad,
                       minimum_run=low['run'], maximum_run=high['run'],
                       minimum_origin=low['origin'], maximum_origin=high['origin'],
                       candidate_count=len(flagged), candidate_runs=', '.join(flagged),
                       previous_runs=len(old), new_runs=len(new),
                       previous_mean_pct=mean(old) if old else '', new_mean_pct=mean(new) if new else '',
                       previous_range_pp=max(old)-min(old) if old else '',
                       new_range_pp=max(new)-min(new) if new else '',
                       compute_min_us=min(r['compute_us'] for r in rows),
                       compute_max_us=max(r['compute_us'] for r in rows),
                       wait_no_min_us=min(r['wait_no_us'] for r in rows),
                       wait_no_max_us=max(r['wait_no_us'] for r in rows),
                       wait_mid_min_us=min(r['wait_mid_us'] for r in rows),
                       wait_mid_max_us=max(r['wait_mid_us'] for r in rows))
        summaries.append(summary)
    summaries.sort(key=lambda r: r['range_pp'], reverse=True)
    candidates.sort(key=lambda r: r['deviation_pp'], reverse=True)
    by_run = defaultdict(list)
    for item in candidates:
        by_run[item['mpi'], item['directory'], item['run']].append(item)
    priority = []
    for (mpi, directory, run), rows in by_run.items():
        priority.append(dict(mpi=mpi, payload=rows[0]['payload'], directory=directory, run=run,
                             origin=rows[0]['origin'], flagged_policy_cases=len(rows),
                             policy_cases=', '.join(r['policy']+'/Case'+r['case'] for r in rows),
                             maximum_deviation_pp=max(r['deviation_pp'] for r in rows),
                             midcomm_directory=str(Path(rows[0]['midcomm_summary']).parent),
                             no_midcomm_directory=str(Path(rows[0]['no_midcomm_summary']).parent)))
    priority.sort(key=lambda r: (r['maximum_deviation_pp'], r['flagged_policy_cases']), reverse=True)
    OUT.mkdir(exist_ok=True)
    write_csv('groups-ranked.csv', summaries)
    write_csv('candidate-runs.csv', candidates)
    write_csv('run-priority.csv', priority)
    write_csv('all-run-details.csv', samples)
    report = dict(checked_at=datetime.now(ZoneInfo('Europe/Berlin')).isoformat(),
                  dataset='updated dashboard; actual included 10-12 paired runs; existing exclusions retained',
                  group_definition='MPI + message size + policy + Case',
                  range_unit='percentage points (max overlap percent minus min overlap percent)',
                  candidate_rule='abs(overlap - group median) > max(20 pp, 3.5 * 1.4826 * MAD)',
                  caution='Candidates for investigation only; small samples and cohort differences can produce flags. No data excluded or changed.',
                  groups=len(summaries), sample_policy_cases=len(samples), candidates=len(candidates),
                  candidate_paired_runs=len(priority), candidate_origins=dict(Counter(r['origin'] for r in candidates)),
                  by_policy={policy: dict(groups=sum(r['policy']==policy for r in summaries),
                             range_over_30pp=sum(r['policy']==policy and r['range_pp']>30 for r in summaries),
                             range_over_100pp=sum(r['policy']==policy and r['range_pp']>100 for r in summaries),
                             candidate_groups=sum(r['policy']==policy and bool(r['candidate_count']) for r in summaries))
                             for policy in ('seq/seq/seq', 'omp/seq/seq')},
                  input_sha256={name:hashlib.sha256((DASH/name).read_bytes()).hexdigest() for name in inputs})
    (OUT/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report,indent=2))
    print('TOP CANDIDATES')
    for row in candidates[:12]:
        print(json.dumps({k:row[k] for k in ('policy','mpi','payload','case','run','origin','overlap_pct','median_overlap_pct','deviation_pp','wait_no_us','median_wait_no_us','wait_mid_us','median_wait_mid_us','compute_us','median_compute_us')}))


if __name__ == '__main__':
    main()
