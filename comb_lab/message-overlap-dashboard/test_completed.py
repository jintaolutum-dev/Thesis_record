"""Verify frozen data, cohort membership, normalization and merged statistics."""
import csv
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
import unittest

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DASHBOARD_DATA_DIR', ROOT / 'unfiltered-update'))


def rows(name, directory=DATA):
    with (directory / name).open() as f:
        return list(csv.DictReader(f))


def key(row):
    return row['mpi'], row['directory'], row['case']


class CompletedTests(unittest.TestCase):
    def test_snapshot_and_membership(self):
        snapshot = ROOT / 'before-update'
        for name, digest in json.loads((snapshot / 'snapshot.json').read_text())['sha256'].items():
            self.assertEqual(hashlib.sha256((snapshot / name).read_bytes()).hexdigest(), digest)
        old = {key(r): r for r in rows('overlap-current.csv', snapshot)}
        new = {key(r): r for r in rows('overlap-current.csv')}
        self.assertEqual(old.keys(), new.keys())
        cohorts = json.loads((DATA / 'cohorts.json').read_text())
        self.assertEqual(sum(len(e['added_runs'] or []) for e in cohorts), 429)
        self.assertEqual(sum(bool(e['added_runs']) for e in cohorts), 63)
        for e in cohorts:
            for case in ('01', '03', '06', '09'):
                k = e['mpi'], e['directory'], case
                before, after = old[k], new[k]
                excluded = {'run_006', 'run_014'} if k == ('mpich', 'msg_x1KiB_y512B_z512B', '06') else set()
                expected = set(e['run_names']) - excluded
                self.assertEqual(set(after['runs'].split(', ')), expected)
                self.assertEqual(int(after['run_count']), len(expected))
                self.assertGreaterEqual(len(expected), 10)
                self.assertEqual(after['normalization'], before['normalization'])
                self.assertEqual(after['baseline_us'], before['baseline_us'])
                if not e['added_runs']:
                    for field, value in before.items():
                        self.assertEqual(after[field], value, (k, field))

    def test_per_run_weighting_and_pairing(self):
        raw = rows('overlap-runs-current.csv')
        indexed = {}
        for row in raw:
            indexed.setdefault(key(row), []).append(row)
            value = (float(row['wait_no_us']) - float(row['wait_mid_us'])) / float(row['denominator_us']) * 100
            self.assertAlmostEqual(float(row['overlap']), value, places=8)
        for point in rows('overlap-current.csv'):
            samples = indexed[key(point)]
            numbers = [float(r['overlap']) for r in samples]
            self.assertEqual(len(numbers), int(point['run_count']))
            self.assertEqual(len({r['run'] for r in samples}), len(numbers))
            for field, value in zip(('min', 'mean', 'max'), (min(numbers), mean(numbers), max(numbers))):
                self.assertAlmostEqual(float(point[field]), value, places=8)
        for first, second in [('01', '06'), ('01', '03'), ('03', '06'), ('03', '09'), ('06', '09')]:
            for point in rows(f'case{first}_vs_case{second}-current.csv'):
                a = {r['run']: r for r in indexed[point['mpi'], point['directory'], first]}
                b = {r['run']: r for r in indexed[point['mpi'], point['directory'], second]}
                paired = set(a) & set(b)
                self.assertEqual(set(point['runs'].split(', ')), paired)
                self.assertEqual(int(point['run_count']), len(paired))
                self.assertGreaterEqual(len(paired), 10)
                delta = [float(b[r]['overlap']) - float(a[r]['overlap']) for r in paired]
                for field, value in zip(('delta_min', 'delta', 'delta_max'), (min(delta), mean(delta), max(delta))):
                    self.assertAlmostEqual(float(point[field]), value, places=8)
                for case, samples in [(first, a), (second, b)]:
                    self.assertAlmostEqual(float(point[case+'_overlap']), mean(float(r['overlap']) for r in samples.values()), places=8)
                self.assertAlmostEqual(float(point['bench_change_pct']), mean((float(b[r]['bench_mid']) / float(a[r]['bench_mid']) - 1) * 100 for r in paired), places=8)

    def test_resource_statistics(self):
        raw = {}
        for row in rows('resources-runs-current.csv'):
            raw.setdefault(key(row), []).append(row)
        for point in rows('resources-current.csv'):
            samples = raw[key(point)]
            self.assertEqual(len(samples), int(point['run_count']))
            self.assertGreaterEqual(len(samples), 10)
            for metric in ('overlap', 'compute_us', 'bench_mid', 'pre_us', 'post_us', 'wait_no_us', 'wait_mid_us'):
                values = [float(r[metric]) for r in samples]
                for suffix, value in [('', mean(values)), ('_min', min(values)), ('_max', max(values))]:
                    self.assertAlmostEqual(float(point[metric+suffix]), value, places=8)


if __name__ == '__main__':
    unittest.main()
