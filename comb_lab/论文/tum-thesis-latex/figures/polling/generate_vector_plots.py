"""Generate thesis polling figures from the current dashboard statistics."""
import json
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[3] / 'message-overlap-dashboard/polling-data.js'
rows = json.loads(SOURCE.read_text().split('=', 1)[1].strip().rstrip(';'))
plt.rcParams.update({'font.size':10, 'xtick.labelsize':9, 'ytick.labelsize':9,
                     'axes.labelsize':10, 'legend.fontsize':9, 'pdf.fonttype':42})
parser = argparse.ArgumentParser()
parser.add_argument('--mpi', choices=('intelmpi', 'openmpi'), default='intelmpi')
mpi = parser.parse_args().mpi
for case in (('01', '03') if mpi == 'openmpi' else ('01', '06')):
    selected = [r for r in rows if r['case'] == case and r['mpi'] == mpi]
    assert len(selected) == 4
    fig, ax = plt.subplots(figsize=(6.4,3.25), layout='constrained')
    for offset, key, color, label in [(-.18,'no_polling','#0065bd','No polling'),(.18,'polling','#e25d3f','Polling (count=2)')]:
        groups = [r[key] for r in selected]
        means = np.array([r['overlap'] for r in groups])
        errors = [means-np.array([r['min'] for r in groups]),np.array([r['max'] for r in groups])-means]
        ax.bar(np.arange(4)+offset,means,.32,color=color,label=label,zorder=3)
        ax.errorbar(np.arange(4)+offset,means,yerr=errors,fmt='none',ecolor='#17202a',elinewidth=.8,capsize=3,zorder=4)
    ax.set_xticks(range(4),[r['payload'] for r in selected])
    ax.set_xlabel('Peer payload');ax.set_ylabel('Measured overlap (%)')
    ax.axhline(0,color='#777777',linewidth=.6);ax.grid(axis='y',alpha=.25)
    ax.spines[['top','right']].set_visible(False)
    ax.margins(y=.15);ax.legend(frameon=False,loc='upper center',bbox_to_anchor=(.5,1.18),ncol=2)
    path=ROOT/f'polling-{mpi}-case{case}-overlap.pdf'
    fig.savefig(path);plt.close(fig);print(path)
