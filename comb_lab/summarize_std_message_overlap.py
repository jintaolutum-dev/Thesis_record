#!/usr/bin/env python3
"""Summarize cm4_std 2n2r message-size overlap for Cases 01 and 06."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import fmean

from analyze_overlap import parse_summary
from summarize_message_overlap import (
    CONFIGURATIONS,
    MPI_NAMES,
    POLICY,
    SPREAD_WARNING_PCT,
    run_overlap,
    run_signature,
)


CASES = ("01", "06")
SECTION_BEGIN = "<!-- std-message-overlap-summary: begin -->"
SECTION_END = "<!-- std-message-overlap-summary: end -->"


def available_runs(base: Path, mpi_name: str, directory: str) -> tuple[int, ...]:
    root = base / mpi_name / "2n2r_c24" / directory
    mid_runs = {path.name for path in (root / "midcomm").glob("run_[0-9][0-9][0-9]")}
    no_runs = {path.name for path in (root / "no_midcomm").glob("run_[0-9][0-9][0-9]")}
    valid = []
    for run_name in sorted(mid_runs & no_runs):
        complete = True
        for case in CASES:
            for mode in ("midcomm", "no_midcomm"):
                summary = root / mode / run_name / f"Comb_{case}_summary.csv"
                if not summary.is_file():
                    complete = False
                    break
                try:
                    complete = POLICY in parse_summary(summary)
                except (OSError, ValueError):
                    complete = False
                if not complete:
                    break
            if not complete:
                break
        if complete:
            valid.append(int(run_name.removeprefix("run_")))
    return tuple(valid)


def calculate(base: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for xyz, payload, directory, _ in CONFIGURATIONS:
        for mpi_name in MPI_NAMES:
            runs = available_runs(base, mpi_name, directory)
            for case in CASES:
                values = [run_overlap(base, mpi_name, directory, run, case) for run in runs]
                reasons = []
                if not values:
                    reasons.append("无可用的 Case 01/06 配对 summary")
                else:
                    if max(values) - min(values) > SPREAD_WARNING_PCT:
                        reasons.append(f"run 间极差 > {SPREAD_WARNING_PCT:.0f} pp")
                    if min(values) < 0.0 or max(values) > 100.0:
                        reasons.append("出现 < 0% 或 > 100%")
                    if len(runs) < 3:
                        reasons.append("有效 run 少于 3 次")
                    if len({run_signature(base, mpi_name, directory, run) for run in runs}) > 1:
                        reasons.append("实验参数不一致")
                rows.append(
                    {
                        "xyz": xyz,
                        "payload": payload,
                        "directory": directory,
                        "mpi": mpi_name,
                        "case": case,
                        "runs": ", ".join(str(run) for run in runs),
                        "min_overlap_pct": min(values) if values else "",
                        "mean_overlap_pct": fmean(values) if values else "",
                        "max_overlap_pct": max(values) if values else "",
                        "anomaly": "yes" if reasons else "no",
                        "anomaly_reasons": "; ".join(reasons),
                    }
                )
    return rows


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def markdown_section(rows: list[dict[str, object]]) -> str:
    lookup = {
        (str(row["xyz"]), str(row["mpi"]), str(row["case"])): row
        for row in rows
    }
    lines = [
        SECTION_BEGIN,
        "## cm4_std 2n2r：消息大小对 overlap 的影响",
        "",
        "统计范围为 `generated/cm4_std` 的 `2n2r_c24`，仅列出 Case 01 和 Case 06。",
        "只接受 midcomm/no_midcomm 成对、两个 Case summary 均完整且包含 MPI `seq/seq/seq` 的 run。",
        "Overlap 计算和异常判定规则与前文相同；`—` 表示没有可用的配对 summary。",
        "",
        "### 可用于统计的 run",
        "",
        "| X / Y / Z 消息大小 | Payload | openmpi | intelmpi | intelmpi_tcp | mpich |",
        "|:---|---:|:---:|:---:|:---:|:---:|",
    ]
    for xyz, payload, _, _ in CONFIGURATIONS:
        run_cells = []
        for mpi_name in MPI_NAMES:
            runs = str(lookup[(xyz, mpi_name, "01")]["runs"])
            run_cells.append(runs or "—")
        lines.append(f"| {xyz} | {payload} | " + " | ".join(run_cells) + " |")

    for case in CASES:
        lines.extend(
            [
                "",
                f"### Case {case}",
                "",
                "| X / Y / Z 消息大小 | Payload | openmpi | intelmpi | intelmpi_tcp | mpich |",
                "|:---|---:|---:|---:|---:|---:|",
            ]
        )
        for xyz, payload, _, _ in CONFIGURATIONS:
            cells = []
            for mpi_name in MPI_NAMES:
                row = lookup[(xyz, mpi_name, case)]
                if row["mean_overlap_pct"] == "":
                    cells.append("—")
                    continue
                warning = "⚠ " if row["anomaly"] == "yes" else ""
                cells.append(
                    f'{warning}{row["min_overlap_pct"]:.2f} / '
                    f'{row["mean_overlap_pct"]:.2f} / {row["max_overlap_pct"]:.2f}'
                )
            lines.append(f"| {xyz} | {payload} | " + " | ".join(cells) + " |")
    lines.extend(["", SECTION_END])
    return "\n".join(lines)


def update_markdown(path: Path, section: str) -> None:
    text = path.read_text()
    if SECTION_BEGIN in text and SECTION_END in text:
        prefix, remainder = text.split(SECTION_BEGIN, 1)
        _, suffix = remainder.split(SECTION_END, 1)
        updated = prefix.rstrip() + "\n\n" + section + suffix
    else:
        request = (
            "现在我打算在这里探究消息大小对 overlap 的影响。由于并非每个 run 都可用，"
            "下面列出 2n2r 拓扑下可用于统计的 run。但是这次是std节点的2n2r "
            "列出来case01 和case 06就可以了"
        )
        prefix = text.rstrip()
        if prefix.endswith(request):
            prefix = prefix[: -len(request)].rstrip()
        updated = prefix + "\n\n" + section + "\n"
    path.write_text(updated)


def main() -> None:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    parser.add_argument("--base", type=Path, default=root / "generated" / "cm4_std")
    parser.add_argument("--csv", type=Path, default=root / "std_message_size_overlap_summary.csv")
    parser.add_argument("--markdown", type=Path, default=root / "消息大小影响.md")
    args = parser.parse_args()

    rows = calculate(args.base)
    write_csv(rows, args.csv)
    update_markdown(args.markdown, markdown_section(rows))
    print(f"Wrote {len(rows)} rows to {args.csv}")
    print(f"Updated {args.markdown}")


if __name__ == "__main__":
    main()