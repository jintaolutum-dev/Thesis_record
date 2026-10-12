"""Fill missing completion plots from current selected-run dashboard data."""
import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[3] / "message-overlap-dashboard"
THESIS_CASE = {"01": "01", "03": "02", "06": "03", "09": "04"}
for mpi, first, second in [("intelmpi", "01", "03"), ("intelmpi_tcp", "01", "03"), ("intelmpi_tcp", "06", "09")]:
    with (SOURCE / f"case{first}_vs_case{second}-current.csv").open() as handle:
        rows = [r for r in csv.DictReader(handle) if r["mpi"] == mpi]
    assert len(rows) == 19
    fig, ax = plt.subplots(figsize=(10, 4.4), layout="constrained")
    for case, color, marker, style in [(first, "#0065bd", "o", "-"), (second, "#e25d3f", "D", "--")]:
        ax.plot(range(19), [float(r[f"{case}_overlap"]) for r in rows],
                color=color, marker=marker, linestyle=style, markersize=4,
                label=f"Case {THESIS_CASE[case]}: {'wait_all' if case in ['01', '06'] else 'test_all'}")
    ax.axhline(0, color="#777777", linewidth=.7)
    ax.axvline(7.5, color="#777777", linestyle="--", linewidth=1)
    ax.set_xticks(range(19), [r["payload"].replace(" ", "\n") for r in rows], fontsize=7)
    ax.set_xlabel("Peer payload (equally spaced categories)")
    ax.set_ylabel("Normalized wait reduction (%)")
    ax.grid(alpha=.2)
    ax.legend(frameon=False)
    fig.savefig(ROOT / f"{mpi}-case{first}-{second}-overlap-vs-message-size.pdf")
    plt.close(fig)
