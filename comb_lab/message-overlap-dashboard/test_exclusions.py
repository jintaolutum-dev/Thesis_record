"""Whole-pair exclusion regression tests against the frozen full dataset."""
import csv
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
import unittest

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DASHBOARD_DATA_DIR', ROOT))
FULL = ROOT / 'unfiltered-update'
RULES = json.loads((ROOT / 'run-exclusions.json').read_text())
EXCLUDED = {(r['mpi'], r['directory'], r['run']) for r in RULES}


def rows(name, directory=DATA):
    with (directory / name).open() as f:
        return list(csv.DictReader(f))


def identity(row):
    return row['mpi'], row['directory'], row['case']


class ExclusionTests(unittest.TestCase):
    def test_scope_and_preservation(self):
        self.assertEqual(len(EXCLUDED), 8)
        for folder in (FULL, ROOT / 'before-update'):
            for name, digest in json.loads((folder / 'snapshot.json').read_text())['sha256'].items():
                self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        for filename, removed_count in [('overlap-runs-current.csv', 32), ('resources-runs-current.csv', 24)]:
            original = rows(filename, FULL)
            expected = [r for r in original if (r['mpi'], r['directory'], r['run']) not in EXCLUDED]
            actual = rows(filename)
            self.assertEqual(len(original) - len(actual), removed_count)
            self.assertEqual([(identity(r), r['run']) for r in actual], [(identity(r), r['run']) for r in expected])
            for a, b in zip(actual, expected):
                for field in ('overlap', 'wait_no_us', 'wait_mid_us', 'compute_us', 'denominator_us', 'bench_mid', 'cycles'):
                    self.assertEqual(float(a[field]), float(b[field]))
        for mpi, directory, run in EXCLUDED:
            for mode in ('midcomm', 'no_midcomm'):
                path = ROOT.parent / 'generated/cm4_inter' / mpi / '2n2r_c24' / directory / mode / run
                self.assertTrue((path / 'run.sh').is_file())
                self.assertTrue(all((path / f'Comb_{c:02d}_summary.csv').is_file() for c in range(10)))

    def test_recomputed_points(self):
        for points_file, raw_file, metrics in [
            ('overlap-current.csv', 'overlap-runs-current.csv', ['overlap']),
            ('resources-current.csv', 'resources-runs-current.csv', ['overlap','wait_no_us','wait_mid_us','compute_us','bench_mid','pre_us','post_us'])]:
            grouped = {}
            for row in rows(raw_file):
                grouped.setdefault(identity(row), []).append(row)
            full = {identity(r): r for r in rows(points_file, FULL)}
            for point in rows(points_file):
                selected = grouped[identity(point)]
                removed = [r for r in RULES if r['mpi'] == point['mpi'] and r['directory'] == point['directory']]
                self.assertEqual(int(point['run_count']), len(selected))
                self.assertEqual(int(point['run_count']), int(full[identity(point)]['run_count']) - len(removed))
                self.assertEqual(int(point['excluded_run_count']), len(removed))
                self.assertEqual(set(point['runs'].split(', ')), {r['run'] for r in selected})
                for metric in metrics:
                    values = [float(r[metric]) for r in selected]
                    fields = ('min','mean','max') if points_file == 'overlap-current.csv' else (metric+'_min',metric,metric+'_max')
                    for field, value in zip(fields, (min(values), mean(values), max(values))):
                        self.assertAlmostEqual(float(point[field]), value, places=8)
                if not removed:
                    for field, value in full[identity(point)].items():
                        self.assertEqual(point[field], value)

    def test_case_pairs(self):
        raw = {(r['mpi'], r['directory'], r['case'], r['run']): r for r in rows('overlap-runs-current.csv')}
        for a, b in [('01','06'),('01','03'),('03','06'),('03','09'),('06','09')]:
            for point in rows(f'case{a}_vs_case{b}-current.csv'):
                run_names = point['runs'].split(', ')
                self.assertEqual(len(run_names), int(point['run_count']))
                deltas, runtimes = [], []
                for run in run_names:
                    self.assertNotIn((point['mpi'], point['directory'], run), EXCLUDED)
                    left, right = (raw[point['mpi'], point['directory'], case, run] for case in (a,b))
                    deltas.append(float(right['overlap']) - float(left['overlap']))
                    runtimes.append((float(right['bench_mid']) / float(left['bench_mid']) - 1) * 100)
                for field, value in zip(('delta_min','delta','delta_max'), (min(deltas), mean(deltas), max(deltas))):
                    self.assertAlmostEqual(float(point[field]), value, places=8)
                self.assertAlmostEqual(float(point['bench_change_pct']), mean(runtimes), places=8)


if __name__ == '__main__':
    unittest.main()
