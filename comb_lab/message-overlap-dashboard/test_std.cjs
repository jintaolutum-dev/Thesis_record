const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', options: [], parentElement: {}, style: {},
    addEventListener() {}, append() {}, replaceChildren(...children) { this.children = children; },
    getContext() { return {}; },
  });
  return elements.get(id);
}
for (const [id, values] of Object.entries({
  'mpi-select': ['openmpi', 'intelmpi', 'intelmpi_tcp', 'mpich'],
  'case-select': ['01', '06', '01-06', '06-09', '03-06', '03-09', '01-03', 'resources'],
  'dataset-select': ['inter', 'unfiltered', 'before', 'latest', '2n2r_c24', '4n4r_c24'],
})) {
  element(id).options = values.map(value => ({value}));
  element(id).value = values[0];
}
class Chart {
  static defaults = {font: {}};
  constructor(_, config) { this.data = config.data; this.options = config.options; }
  update() {}
}
const context = vm.createContext({Chart, URLSearchParams, console,
  window: {location: {search: ''}}, lucide: {createIcons() {}},
  document: {documentElement: {style: {setProperty() {}}}, getElementById: element, querySelector: element,
    createElement: () => ({children: [], append(child) { this.children.push(child); }})},
});
for (const file of ['data.js', 'before-data.js', 'unfiltered-data.js', 'std-data.js', 'std-comparisons-data.js', 'resources-data.js', 'latest-data.js', 'resources.js', 'app.js']) {
  const directory = process.env.DASHBOARD_DATA_DIR && ['data.js', 'resources-data.js'].includes(file) ? process.env.DASHBOARD_DATA_DIR : __dirname;
  vm.runInContext(fs.readFileSync(`${directory}/${file}`, 'utf8'), context);
}
assert.equal(element('dataset-select').value, 'inter');
assert.equal(element('latest-summary').hidden, true);
assert.equal(element('supplement-summary').hidden, false);
assert.equal(vm.runInContext('chart.data.labels.length', context), 19);
element('dataset-select').value = 'latest';
vm.runInContext('updateChart()', context);
assert.equal(element('latest-summary').hidden, false);
assert.equal(vm.runInContext('chart.data.labels.length', context), 9);
assert.equal(vm.runInContext('LATEST_SUMMARY.complete_pairs', context), 254);
for (const [mpi, count] of Object.entries({openmpi: 9, intelmpi: 7, intelmpi_tcp: 5, mpich: 9})) {
  element('mpi-select').value = mpi;
  for (const caseId of ['01', '06', '01-06', '06-09', '03-06', '03-09', '01-03', 'resources']) {
    element('case-select').value = caseId;
    for (const metric of (caseId === 'resources' ? ['overlap', 'bench_mid', 'wait_mid_us', 'wait_no_us', 'pre_us', 'post_us', 'compute_us'] : ['overlap'])) {
      element('resource-metric').value = metric;
      element('resource-metric').selectedOptions = [{textContent: metric}];
      vm.runInContext('updateChart()', context);
      assert.equal(vm.runInContext('chart.data.labels.length', context), count);
      const series = vm.runInContext('chart.data.datasets.map(d => d.data)', context);
      assert(series.every(data => data.length === count));
      const hasZeroCompute = ['intelmpi_tcp', 'mpich'].includes(mpi) && metric === 'overlap';
      for (const data of series) {
        assert.equal(data.filter(v => v === null).length, hasZeroCompute ? 1 : 0);
        assert(data.every(v => v === null || Number.isFinite(v)));
      }
      assert.equal(element('runs-csv').href, 'latest-runs.csv');
      assert.equal(element('comparison-csv').href, caseId === 'resources' ? 'latest-resources.csv' : caseId.includes('-') ? 'latest-comparisons.csv' : 'latest-overlap.csv');
      if (hasZeroCompute) assert(element('comparison-body').children.some(row => row.children.some(cell => cell.textContent === 'N/A')));
      if (caseId !== 'resources') {
        assert(Number.isFinite(vm.runInContext('chart.options.scales.y.min', context)));
        assert(Number.isFinite(vm.runInContext('chart.options.scales.y.max', context)));
      }
    }
  }
}
console.log('PASS: historical default, latest MPI/case/metric switches, zero-compute gaps, table N/A, CSV links');
function check(dataset, mpi, count) {
  element('dataset-select').value = dataset;
  element('mpi-select').value = mpi;
  for (const caseId of ['01', '06']) {
    element('case-select').value = caseId;
    vm.runInContext('updateChart()', context);
    assert.equal(vm.runInContext('chart.data.labels.length', context), count);
    assert.equal(element('runs-csv').href, dataset === 'inter' ? 'overlap-runs-current.csv' : 'std-runs-current.csv');
  }
}
check('2n2r_c24', 'intelmpi', 19);
check('2n2r_c24', 'mpich', 18);
check('4n4r_c24', 'intelmpi', 12);
check('4n4r_c24', 'mpich', 19);
check('4n4r_c24', 'openmpi', 0);
element('mpi-select').value = 'mpich';
for (const topology of ['2n2r_c24', '4n4r_c24']) {
  element('dataset-select').value = topology;
  for (const pair of ['01-06', '01-03', '03-06', '03-09', '06-09']) {
    element('case-select').value = pair;
    vm.runInContext('updateChart()', context);
    assert(vm.runInContext('chart.data.labels.length > 0', context));
    assert.equal(vm.runInContext('chart.data.datasets.length', context), 2);
    assert.equal(element('comparison-csv').href, 'std-comparisons-current.csv');
  }
  element('case-select').value = 'resources';
  for (const metric of ['overlap', 'wait_mid_us', 'bench_mid']) {
    element('resource-metric').value = metric;
    element('resource-metric').selectedOptions = [{textContent: metric}];
    vm.runInContext('updateChart()', context);
    assert.equal(vm.runInContext('chart.data.datasets.length', context), 3);
    assert.equal(vm.runInContext('chart.options.scales.y.ticks.callback(10)', context), metric === 'overlap' ? '10%' : '10');
    assert.equal(element('comparison-csv').href, 'std-resources-current.csv');
  }
}
check('inter', 'mpich', 19);
assert.equal(element('latest-summary').hidden, true);
assert(element('case-select').options.every(option => !option.disabled));
console.log('PASS: std topology/case switches, missing-data state, CSV links, and inter restoration');

for (const mpi of ['openmpi', 'intelmpi', 'intelmpi_tcp', 'mpich']) {
  element('dataset-select').value = 'inter';
  element('mpi-select').value = mpi;
  element('case-select').value = '01-06';
  vm.runInContext('updateChart()', context);
  assert.equal(vm.runInContext('chart.data.labels.length', context), 19);
  assert.equal(vm.runInContext('chart.data.datasets.length', context), 2);
  assert.equal(element('comparison-csv').href, 'case01_vs_case06-current.csv');
  assert(element('configuration').textContent.includes('01: ASYNC OFF'));
}
console.log('PASS: Case 01 vs 06 for all four inter MPI configurations');

element('dataset-select').value = 'before';
element('mpi-select').value = 'mpich';
for (const caseId of ['01', '06', '01-06', '01-03', '03-06', '03-09', '06-09', 'resources']) {
  element('case-select').value = caseId;
  element('resource-metric').value = 'overlap';
  element('resource-metric').selectedOptions = [{textContent: 'overlap'}];
  vm.runInContext('updateChart()', context);
  const rows = vm.runInContext('isResource() ? resourceRows("04") : isComparison() ? comparisonRows() : selectedRows()', context);
  for (const [payload, count] of [['144.50 KiB', 11], ['289.00 KiB', 9]]) {
    const row = rows.find(r => r.payload === payload);
    assert.equal(row.run_count, count);
    assert.equal(row.source, 'original+supplement');
    assert.equal(row.normalization, 'measured_compute');
    assert.equal(new Set(row.runs.split(', ')).size, count);
  }
  assert.equal(element('supplement-summary').hidden, false);
  assert(element('data-status').textContent.includes('2 original + supplement points'));
  assert.equal(element('runs-csv').href, 'before-update/' + (caseId === 'resources' ? 'resources-runs-current.csv' : 'overlap-runs-current.csv'));
}
console.log('PASS: combined historical/supplement counts, provenance, normalization and downloads across every view');

for (const mpi of ['openmpi', 'intelmpi', 'intelmpi_tcp', 'mpich']) {
  element('mpi-select').value = mpi;
  for (const caseId of ['01', '06', '01-06', '06-09', '03-06', '03-09', '01-03', 'resources']) {
    element('case-select').value = caseId;
    for (const metric of (caseId === 'resources' ? ['overlap', 'bench_mid', 'compute_us', 'wait_mid_us', 'wait_no_us', 'pre_us', 'post_us'] : ['overlap'])) {
      element('resource-metric').value = metric;
      element('resource-metric').selectedOptions = [{textContent: metric}];
      for (const dataset of ['before', 'unfiltered', 'inter', 'before', 'inter']) {
        element('dataset-select').value = dataset;
        vm.runInContext('updateChart()', context);
        const rows = vm.runInContext('isResource() ? resourceRows("04") : isComparison() ? comparisonRows() : selectedRows()', context);
        assert.equal(rows.length, 19);
        assert(vm.runInContext('chart.data.datasets.every(d => d.data.every(Number.isFinite))', context));
        assert.equal(element('mpi-select').value, mpi);
        assert.equal(element('case-select').value, caseId);
        const prefix = dataset === 'before' ? 'before-update/' : dataset === 'unfiltered' ? 'unfiltered-update/' : '';
        const csv = caseId === 'resources' ? 'resources-current.csv' : caseId.includes('-') ? `case${caseId.replace('-', '_vs_case')}-current.csv` : 'overlap-current.csv';
        assert.equal(element('comparison-csv').href, prefix + csv);
        assert.equal(element('runs-csv').href, prefix + (caseId === 'resources' ? 'resources-runs-current.csv' : 'overlap-runs-current.csv'));
        assert(element('supplement-summary').textContent.startsWith(dataset === 'before' ? 'v1:' : dataset === 'unfiltered' ? 'Unfiltered merged snapshot:' : 'v2:'));
        assert.equal(element('exclusions-link').hidden, dataset !== 'inter');
        if (dataset === 'inter' || dataset === 'unfiltered') {
          assert(rows.every(row => row.run_count >= (dataset === 'inter' ? 8 : 10)));
          for (const row of rows) assert.equal(row.previous_run_count + row.added_run_count, row.run_count);
          if (mpi === 'openmpi') {
            const row = rows.find(r => r.payload === '1.13 MiB');
            assert.equal(row.cycles, '100');
            assert(!row.runs.split(', ').includes('run_020_MPIonly'));
            assert.equal(row.added_run_count, 8);
          }
          if (mpi === 'intelmpi_tcp') assert(!rows.find(r => r.payload === '3.39 MiB').runs.split(', ').includes('run_003'));
          if (mpi === 'mpich') assert.equal(rows.find(r => r.payload === '289.00 KiB').run_count, dataset === 'inter' ? 9 : 10);
          const exclusions = JSON.parse(fs.readFileSync(`${__dirname}/run-exclusions.json`, 'utf8'));
          for (const row of rows) {
            const removed = exclusions.filter(e => e.mpi === row.mpi && e.directory === row.directory);
            if (dataset === 'inter') {
              assert.equal(row.excluded_run_count, removed.length);
              for (const rule of removed) assert(!row.runs.split(', ').includes(rule.run));
              if (removed.length) {
                context.testRow = row;
                assert(vm.runInContext('sourceLabel(testRow)', context).includes('Excluded'));
              }
            } else {
              for (const rule of removed) assert(row.runs.split(', ').includes(rule.run));
            }
          }
        }
      }
    }
  }
}
console.log('PASS: before/after switches across all MPI/case/metric selections, counts, approved exclusions, matching CSV exports');
