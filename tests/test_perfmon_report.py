"""Offline unit tests for PerfMon CSV normalization and reporting."""

import csv
import tempfile
import unittest
from pathlib import Path

import perfmon_report as report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "examples" / "sample_perfmon.csv"


class PerfMonReportTests(unittest.TestCase):
    def test_sample_log_has_readable_rows(self):
        header, rows = report.load_csv(SAMPLE)
        self.assertGreaterEqual(len(header), 7)
        self.assertGreater(len(rows), 2)

    def test_extracts_all_six_metrics(self):
        header, rows = report.load_csv(SAMPLE)
        timestamps, values, units = report.extract_metrics(header, rows)
        self.assertEqual(len(timestamps), len(rows))
        self.assertEqual(len(values), 6)
        self.assertEqual(units["CPU utilization"], "%")
        self.assertEqual(units["Network throughput (sum of interfaces)"], "MiB/s")

    def test_sums_network_interfaces_and_converts_bytes(self):
        header, rows = report.load_csv(SAMPLE)
        _, values, _ = report.extract_metrics(header, rows)
        network = values["Network throughput (sum of interfaces)"]
        self.assertAlmostEqual(network[1], 2.5)
        self.assertAlmostEqual(values["Disk read throughput"][1], 1.0)

    def test_numeric_parsing_of_localized_decimals_and_missing_values(self):
        self.assertAlmostEqual(report.numeric("1,25"), 1.25)
        for value in ("", "NaN", "-1", "not a number", "INF"):
            self.assertIsNone(report.numeric(value))

    def test_supports_utf16_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "utf16.csv"
            file.write_text('time,counter\n2026-11-10,12\n', encoding="utf-16")
            header, rows = report.load_csv(file)
            self.assertEqual(header, ["time", "counter"])
            self.assertEqual(rows[0][1], "12")

    def test_unrecognized_counters_raise_helpful_error(self):
        with self.assertRaisesRegex(ValueError, "no recognized counters"):
            report.extract_metrics(["Timestamp", r"\\PC\\Unknown\\Counter"], [["now", "5"]])

    def test_single_metric_chart_and_html_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            times = ["2026-11-10 10:00:00", "2026-11-10 10:00:05"]
            values = {"CPU utilization": [20, 45]}
            units = {"CPU utilization": "%"}
            report.create_chart(folder / "chart.png", times, values, units)
            report.save_normalized_csv(folder / "data.csv", times, values)
            report.build_html_report(folder / "report.html", "data.csv", "chart.png", times, values, units, "test & demo")
            self.assertGreater((folder / "chart.png").stat().st_size, 100)
            self.assertIn("test &amp; demo", (folder / "report.html").read_text(encoding="utf-8"))
            with (folder / "data.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(next(csv.reader(handle)), ["Timestamp", "CPU utilization"])

    def test_cli_csv_mode_end_to_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            report.main(["--csv", str(SAMPLE), "--output", temporary])
            folders = [p for p in Path(temporary).iterdir() if p.is_dir()]
            self.assertEqual(len(folders), 1)
            for filename in ("report.html", "raw_perfmon.csv", "performance_data.csv", "performance_charts.png"):
                self.assertTrue((folders[0] / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
