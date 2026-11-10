#!/usr/bin/env python3
"""Create a Windows Performance Monitor report from live counters, BLG, or CSV.

Examples:
    python perfmon_report.py
    python perfmon_report.py --interval 5 --samples 12
    python perfmon_report.py --blg 'C:\\PerfLogs\\Admin\\sample.blg'
    python perfmon_report.py --csv 'C:\\PerfLogs\\sample.csv'
"""

import argparse
import csv
import html
import io
import math
import subprocess
from datetime import datetime
from pathlib import Path
from statistics import mean

__version__ = "1.0.0"

import matplotlib
matplotlib.use("Agg")  # Chart generation works without a desktop GUI.
import matplotlib.pyplot as plt

# These are real Windows Performance Monitor counter paths, not psutil metrics.
COUNTERS = [
    r"\Processor(_Total)\% Processor Time",
    r"\Memory\Available MBytes",
    r"\Memory\% Committed Bytes In Use",
    r"\PhysicalDisk(_Total)\Disk Read Bytes/sec",
    r"\PhysicalDisk(_Total)\Disk Write Bytes/sec",
    r"\Network Interface(*)\Bytes Total/sec",
]

# Tuple: display name, matching suffix, conversion factor, plot unit.
METRICS = [
    ("CPU utilization", r"\processor(_total)\% processor time", 1.0, "%"),
    ("Available memory", r"\memory\available mbytes", 1.0, "MB"),
    ("Committed memory (of commit limit)", r"\memory\% committed bytes in use", 1.0, "%"),
    ("Disk read throughput", r"\physicaldisk(_total)\disk read bytes/sec", 1 / 1048576, "MiB/s"),
    ("Disk write throughput", r"\physicaldisk(_total)\disk write bytes/sec", 1 / 1048576, "MiB/s"),
    ("Network throughput (sum of interfaces)", r"\network interface(*)\bytes total/sec", 1 / 1048576, "MiB/s"),
]


def run_command(command):
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Windows utility not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{details}") from exc


def load_csv(file_path):
    raw = file_path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        content = raw.decode("utf-16")
    elif raw[:200].count(b"\x00") > 30:
        content = raw.decode("utf-16-le")
    else:
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("cp1252")

    reader = csv.reader(io.StringIO(content, newline=""))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ValueError("No readable performance counter columns found in CSV.")
    rows = [row for row in reader if row and len(row) >= len(header)]
    if not rows:
        raise ValueError("The performance log contains no data samples.")
    return header, rows


def numeric(value):
    try:
        number = float(value.strip().replace(",", "."))
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, AttributeError):
        return None


def extract_metrics(header, rows):
    timestamps = [row[0].strip() for row in rows]
    columns = [name.strip().lower() for name in header]
    values = {}
    units = {}

    for name, suffix, multiplier, unit in METRICS:
        if name.startswith("Network"):
            # Wildcard counters expand to individual NIC names in CSV headers.
            matching = [i for i, col in enumerate(columns)
                        if "\\network interface(" in col and col.endswith(r"\bytes total/sec")]
        else:
            matching = [i for i, col in enumerate(columns) if col.endswith(suffix)]
        if not matching:
            continue  # A BLG/CSV may contain only a subset of the default counters.
        series = []
        for row in rows:
            items = [numeric(row[i]) for i in matching]
            items = [v for v in items if v is not None]
            if not items:
                series.append(None)
            else:
                value = sum(items) if name.startswith("Network") else items[0]
                series.append(value * multiplier)
        if any(v is not None for v in series):
            values[name] = series
            units[name] = unit

    if not values:
        raise ValueError(
            "The log contains no recognized counters. Check the log's column "
            "names (or customize METRICS in this script)."
        )
    return timestamps, values, units


def save_normalized_csv(path, timestamps, values):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Timestamp", *values.keys()])
        for index, timestamp in enumerate(timestamps):
            writer.writerow([timestamp, *["" if series[index] is None else f"{series[index]:.4f}"
                                           for series in values.values()]])


def create_chart(path, timestamps, values, units):
    count = len(values)
    fig, axes = plt.subplots(count, 1, figsize=(13, 2.25 * count + 0.7), sharex=True)
    if count == 1:
        axes = [axes]
    x = list(range(len(timestamps)))
    for ax, (name, series) in zip(axes, values.items()):
        ax.plot(x, series, linewidth=1.7)
        ax.set_ylabel(units[name])
        ax.set_title(name, loc="left", fontsize=10)
        ax.grid(alpha=0.3)
        if name == "CPU utilization" or name == "Committed memory (of commit limit)":
            ax.set_ylim(0, max(100, max((v for v in series if v is not None), default=0) * 1.1))
    step = max(1, len(timestamps) // 6)
    ticks = sorted(set([*range(0, len(timestamps), step), len(timestamps) - 1]))
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([timestamps[i] for i in ticks], rotation=18, ha="right", fontsize=8)
    axes[-1].set_xlabel("Performance Monitor sample timestamp")
    fig.tight_layout()
    fig.savefig(path, dpi=135, bbox_inches="tight")
    plt.close(fig)


def build_html_report(path, csv_name, chart_name, timestamps, values, units, source):
    table_rows = []
    for name, series in values.items():
        valid = [v for v in series if v is not None]
        latest = valid[-1] if valid else float("nan")
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{mean(valid):,.2f}</td><td>{max(valid):,.2f}</td>"
            f"<td>{latest:,.2f}</td><td>{html.escape(units[name])}</td>"
            "</tr>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Windows Performance Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; background:#f4f7fb; color:#1b2635;
       margin:0 auto; padding:30px; max-width:1080px; }}
main {{ background:white; padding:26px 34px; border-radius:14px; box-shadow:0 2px 15px #dfe5ed; }}
h1 {{ color:#124a82; }} .meta {{ color:#566171; line-height:1.75; }}
table {{ border-collapse:collapse; width:100%; margin:22px 0; }}
th,td {{ text-align:left; padding:11px; border-bottom:1px solid #dce4ec; }}
th {{ background:#e8f1fa; }} img {{ width:100%; height:auto; }}
a {{ color:#115e9e; }} small {{ color:#5d6674; }}
</style></head><body><main>
<h1>Windows Performance Monitor Report</h1>
<p class="meta"><strong>Source:</strong> {html.escape(source)}<br>
<strong>First sample:</strong> {html.escape(timestamps[0])}<br>
<strong>Last sample:</strong> {html.escape(timestamps[-1])}<br>
<strong>Samples:</strong> {len(timestamps)}<br>
<strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<h2>Counter Summary</h2>
<table><thead><tr><th>Counter</th><th>Average</th><th>Maximum</th>
<th>Latest</th><th>Unit</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table>
<h2>Performance Trends</h2><img src="{html.escape(chart_name, quote=True)}" alt="Counter history charts">
<p><a href="{html.escape(csv_name, quote=True)}">Download clean CSV data</a></p>
<small>Committed memory (%) is based on the Windows commit limit, not physical RAM usage.
Network throughput sums monitored interfaces, including virtual interfaces if present.</small>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report on Windows PerfMon counter data")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--blg", type=Path, help="Existing Performance Monitor .blg log")
    source.add_argument("--csv", type=Path, help="Existing Performance Monitor CSV log")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between samples (default 5)")
    parser.add_argument("--samples", type=int, default=12, help="Samples per report (default 12)")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "reports")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.interval < 1 or args.samples < 2:
        parser.error("--interval must be >= 1 and --samples must be >= 2")

    folder = args.output / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder.mkdir(parents=True, exist_ok=True)
    csv_file = folder / "raw_perfmon.csv"
    if args.blg:
        if not args.blg.is_file():
            parser.error(f"BLG file not found: {args.blg}")
        run_command(["relog", str(args.blg), "/f", "CSV", "/o", str(csv_file), "/y"])
        source_name = f"PerfMon BLG: {args.blg}"
    elif args.csv:
        if not args.csv.is_file():
            parser.error(f"CSV file not found: {args.csv}")
        csv_file.write_bytes(args.csv.read_bytes())
        source_name = f"PerfMon CSV: {args.csv}"
    else:
        run_command(["typeperf", *COUNTERS, "-si", str(args.interval), "-sc",
                     str(args.samples), "-f", "CSV", "-o", str(csv_file), "-y"])
        source_name = "Live Windows performance counters (typeperf)"

    header, rows = load_csv(csv_file)
    times, metrics, units = extract_metrics(header, rows)
    clean_csv = folder / "performance_data.csv"
    chart_png = folder / "performance_charts.png"
    report_html = folder / "report.html"
    save_normalized_csv(clean_csv, times, metrics)
    create_chart(chart_png, times, metrics, units)
    build_html_report(report_html, clean_csv.name, chart_png.name, times, metrics, units, source_name)
    print(f"Created report: {report_html}")
    print(f"Chart:          {chart_png}")
    print(f"Data:           {clean_csv}")


if __name__ == "__main__":
    main()
