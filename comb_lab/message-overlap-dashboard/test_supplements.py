"""Regression checks for approved historical supplements and per-run weighting."""
import csv
import json
from pathlib import Path
from statistics import mean
import tempfile
import unittest

from build_data import BASE, ROOT
from supplement_runs import include_supplements


def rows(name):
    with (ROOT / 'before-update' / name).open() as handle:
        return list(csv.DictReader(handle))


class SupplementTests(unittest.TestCase):
    def test_combined_per_run_statistics_and_case_pairs(self):
        approved = json.loads((ROOT / 'approved-supplements.json').read_text())
        raw = rows('overlap-runs-current.csv')
        points = rows('overlap-current.csv')
        resources = rows('resources-current.csv')
        resource_raw = rows('resources-runs-current.csv')
        for group in approved:
            expected = set(group['historical_runs'] + group['supplement_runs'])
            def in_group(row):
                return row['mpi'] == group['mpi'] and row['directory'] == group['directory']
            for point in filter(in_group, points):
                samples = [r for r in raw if in_group(r) and r['case'] == point['case']]
                self.assertEqual(len(samples), len(expected))
                self.assertEqual({r['run'] for r in samples}, expected)
                # Every run has equal weight, regardless of old/new cohort size.
                numbers = [(float(r['wait_no_us']) - float(r['wait_mid_us'])) / float(r['compute_us']) * 100 for r in samples]
                for key, value in zip(['min', 'mean', 'max'], [min(numbers), mean(numbers), max(numbers)]):
                    self.assertAlmostEqual(float(point[key]), value, places=8)
            for pair in ['01-06', '01-03', '03-06', '03-09', '06-09']:
                a, b = pair.split('-')
                point = next(filter(in_group, rows(f'case{a}_vs_case{b}-current.csv')))
                samples = {(r['case'], r['run']): float(r['overlap']) for r in raw if in_group(r)}
                deltas = [samples[b, run] - samples[a, run] for run in sorted(expected)]
                self.assertEqual(int(point['run_count']), len(expected))
                self.assertAlmostEqual(float(point['delta']), mean(deltas), places=8)
                self.assertAlmostEqual(float(point['delta_min']), min(deltas), places=8)
                self.assertAlmostEqual(float(point['delta_max']), max(deltas), places=8)
            for point in filter(in_group, resources):
                samples = [r for r in resource_raw if in_group(r) and r['case'] == point['case']]
                self.assertEqual({r['run'] for r in samples}, expected)
                for metric in ['overlap', 'compute_us', 'bench_mid', 'pre_us', 'post_us', 'wait_no_us', 'wait_mid_us']:
                    self.assertAlmostEqual(float(point[metric]), mean(float(r[metric]) for r in samples), places=8)

    def test_rejects_mismatched_compute_target(self):
        # This is an actual rejected October group: 20 us versus historical 851 us.
        bad = dict(mpi='openmpi', directory='msg_x1.00MiB_y512KiB_z512KiB',
                   historical_runs=['run_003', 'run_004', 'run_005'], supplement_runs=['run_016_MPIonly'])
        selected = {(bad['mpi'], bad['directory']): dict(run_names=bad['historical_runs'],
                    source='original', baseline_us=None, expected={})}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.json'
            path.write_text(json.dumps([bad]))
            with self.assertRaisesRegex(ValueError, 'target_us'):
                include_supplements(selected, BASE, path)


if __name__ == '__main__':
    unittest.main()
