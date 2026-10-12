"""Redraw thesis curves as vectors from the current selected-run statistics."""
import csv
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[2] / "message-overlap-dashboard" / "overlap-current.csv"


THESIS_CASE = {"01": "01", "03": "02", "06": "03", "09": "04"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--on-off-only", action="store_true", help="Regenerate only the progress on/off comparisons")
    parser.add_argument("--comparisons-only", action="store_true", help="Regenerate comparison legends without touching single-case plots")
    args = parser.parse_args()
    with SOURCE.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    plt.rcParams.update({"font.size": 10, "xtick.labelsize": 9,
                         "ytick.labelsize": 9, "axes.labelsize": 10,
                         "legend.fontsize": 9, "pdf.fonttype": 42})
    for mpi in ("intelmpi", "intelmpi_tcp", "openmpi", "mpich"):
        pairs = (("01", "06"),) if args.on_off_only else (("01",), ("06",), ("01", "03"), ("06", "09"), ("01", "06"))
        for cases in pairs:
            if args.comparisons_only and len(cases) == 1:
                continue
            fig, ax = plt.subplots(figsize=(6.4, 3.25), layout="constrained")
            for case, color, marker, style in zip(
                    cases, ("#0065bd", "#e25d3f"), ("o", "D"), ("-", "--")):
                points = [r for r in rows if r["mpi"] == mpi and r["case"] == case]
                assert len(points) == 19, (mpi, case, len(points))
                labels = [r["payload"] for r in points]
                means = [float(r["mean"]) for r in points]
                label = f"Case {THESIS_CASE[case]}: " + ("wait_all" if case in ("01", "06") else "test_all")
                if cases == ("01", "06"):
                    label = f"Case {THESIS_CASE[case]}: progress " + ("off" if case == "01" else "on")
                if len(cases) == 1:
                    errors = [[float(r["mean"]) - float(r["min"]) for r in points],
                              [float(r["max"]) - float(r["mean"]) for r in points]]
                    ax.errorbar(range(19), means, yerr=errors, color=color,
                                marker=marker, markersize=3.5, linewidth=1.2,
                                elinewidth=.8, capsize=2, label="Mean and run min-max")
                else:
                    ax.plot(range(19), means, color=color, marker=marker,
                            linestyle=style, markersize=3.5, linewidth=1.2, label=label)
            ax.set_xticks(range(19), labels, rotation=60, ha="right")
            ax.set_xlabel("Peer payload (equally spaced categories)")
            ax.set_ylabel("Normalized wait reduction (%)")
            ax.axhline(0, color="#777777", linewidth=.6)
            ax.grid(axis="y", alpha=.25)
            ax.spines[["top", "right"]].set_visible(False)
            ax.legend(frameon=False, loc="best")
            folder = "msgsize-vs-overlap" if len(cases) == 1 else "testall"
            target = ROOT / folder / f"{mpi}-case{'-'.join(cases)}-overlap-vs-message-size.pdf"
            if cases == ("01", "06"):
                target = ROOT / "on_off" / f"inter-{mpi}-case01-06-overlap-vs-message-size.pdf"
            fig.savefig(target)
            plt.close(fig)
            print(target)


if __name__ == "__main__":
    main()
