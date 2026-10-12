"""Generate paired completion-method statistics from the dashboard's current run data."""
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[2] / "message-overlap-dashboard/overlap-runs-current.csv"
NAMES = {"openmpi": "Open MPI TCP", "intelmpi": "Intel MPI verbs",
         "intelmpi_tcp": "Intel MPI TCP", "mpich": "MPICH TCP"}
THESIS_CASE = {"01": "01", "03": "02", "06": "03", "09": "04"}
PAIRS = [("01", "03"), ("06", "09"), ("03", "09")]


def main():
    groups = defaultdict(dict)
    with SOURCE.open() as handle:
        for row in csv.DictReader(handle):
            groups[row["mpi"], row["payload"]][row["case"], row["run"]] = row
    points = []
    for (mpi, payload), rows in groups.items():
        for first, second in PAIRS:
            runs = [run for case, run in rows if case == first]
            assert set(runs) == {run for case, run in rows if case == second}
            a, b = [rows[first, run] for run in runs], [rows[second, run] for run in runs]
            assert all(x["normalization"] == y["normalization"] and x["baseline_us"] == y["baseline_us"] for x, y in zip(a, b))
            delta = [float(y["overlap"]) - float(x["overlap"]) for x, y in zip(a, b)]
            runtime = [(float(y["bench_mid"]) / float(x["bench_mid"]) - 1) * 100 for x, y in zip(a, b)]
            points.append(dict(mpi=mpi, payload=payload, pair=f"{first}-{second}",
                runs=", ".join(runs), normalization=a[0]["normalization"],
                delta=mean(delta), low=min(delta), high=max(delta), runtime=mean(runtime)))
    with (ROOT / "completion-paired-points.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=points[0].keys())
        writer.writeheader()
        writer.writerows(points)
    summary = []
    for mpi in NAMES:
        for first, second in PAIRS:
            selected = [r for r in points if r["mpi"] == mpi and r["pair"] == f"{first}-{second}"]
            assert len(selected) == 19
            summary.append(dict(mpi=mpi, pair=f"{first}-{second}",
                higher=sum(r["delta"] > 0 for r in selected),
                median_delta=median(r["delta"] for r in selected),
                median_runtime=median(r["runtime"] for r in selected)))
    with (ROOT / "completion-summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.2), layout="constrained")
    for ax, (mpi, title) in zip(axes.flat, NAMES.items()):
        for pair, color, marker, offset in [("01-03", "#087f73", "o", -0.12), ("06-09", "#c34b36", "s", 0.12)]:
            rows = [r for r in points if r["mpi"] == mpi and r["pair"] == pair]
            y = [r["delta"] for r in rows]
            ax.errorbar([i + offset for i in range(19)], y,
                yerr=[[r["delta"] - r["low"] for r in rows], [r["high"] - r["delta"] for r in rows]],
                color=color, marker=marker, markersize=3, linewidth=0.9, elinewidth=0.7,
                capsize=2, label=f"Case {THESIS_CASE[pair[3:]]} minus {THESIS_CASE[pair[:2]]}")
        ax.axhline(0, color="#444444", linewidth=0.7)
        ax.set_title(title)
        ticks = [0, 4, 8, 12, 18]
        ax.set_xticks(ticks, [rows[i]["payload"].replace(" ", "\n") for i in ticks])
        ax.set_ylabel("Paired overlap difference (pp)")
        ax.set_xlabel("Peer payload (equally spaced)")
        ax.grid(axis="y", alpha=0.2)
    axes[0, 0].legend(fontsize=8)
    fig.savefig(ROOT / "completion-method-differences.pdf")
    fig.savefig(ROOT / "completion-method-differences.png", dpi=180)
    plt.close(fig)
    for row in summary:
        print(f"{row['mpi']} {row['pair']}: {row['higher']}/19 higher; median delta {row['median_delta']:.2f} pp; median runtime {row['median_runtime']:.2f}%")


if __name__ == "__main__":
    main()
