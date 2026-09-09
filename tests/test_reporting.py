import csv
import io
from pathlib import Path
import tempfile
import unittest

from step_to_acis.models import ConversionResult, Status
from step_to_acis.reporting import (
    CSV_COLUMNS,
    append_run_log,
    format_size,
    summarize,
    write_conversion_csv,
)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def result(self, sequence=1, status=Status.SUCCESS, error_message=""):
        return ConversionResult(
            sequence=sequence,
            task_id="task-{}".format(sequence),
            source_name='连接板,"001".stp',
            source_path='E:\\输入,目录\\连接板,"001".stp',
            output_name='连接板,"001".sab',
            output_path='E:\\输出 目录\\连接板,"001".sab',
            output_format="SAB",
            source_size_bytes=1_303_561,
            output_size_bytes=2_584_227 if status is Status.SUCCESS else 0,
            start_time="2026-08-11T10:00:00Z",
            duration_seconds=4.38123456,
            status=status,
            error_message=error_message,
            finish_time="2026-08-11T10:00:04Z",
        )

    def test_csv_has_bom_exact_columns_and_round_trips_chinese(self):
        path = self.root / "conversion_log.csv"
        result = self.result(error_message="第一行\n第二行")

        write_conversion_csv(path, [result])

        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            rows = list(reader)
        self.assertEqual(list(CSV_COLUMNS), reader.fieldnames)
        self.assertEqual(1, len(rows))
        self.assertEqual(result.source_name, rows[0]["SourceName"])
        self.assertEqual("1303561", rows[0]["SourceSizeBytes"])
        self.assertEqual("2584227", rows[0]["OutputSizeBytes"])
        self.assertEqual("4.381235", rows[0]["DurationSeconds"])
        self.assertEqual("第一行\n第二行", rows[0]["ErrorMessage"])

    def test_csv_replaces_an_existing_report_after_complete_write(self):
        path = self.root / "conversion_log.csv"
        path.write_text("old-report", encoding="utf-8")

        write_conversion_csv(path, [self.result()])

        self.assertNotIn("old-report", path.read_text(encoding="utf-8-sig"))
        self.assertFalse((self.root / "conversion_log.csv.tmp").exists())

    def test_summary_counts_statuses_and_rejects_inconsistent_total(self):
        results = [
            self.result(1, Status.SUCCESS),
            self.result(2, Status.FAILED, "failed"),
            self.result(3, Status.SKIPPED, "exists"),
        ]

        summary = summarize(results, elapsed_seconds=125.5)

        self.assertEqual(3, summary.total)
        self.assertEqual(1, summary.success)
        self.assertEqual(1, summary.failed)
        self.assertEqual(1, summary.skipped)
        self.assertEqual(125.5, summary.elapsed_seconds)
        self.assertEqual(summary.total, summary.success + summary.failed + summary.skipped)

    def test_size_formatter_uses_readable_binary_units(self):
        self.assertEqual("0 B", format_size(0))
        self.assertEqual("1.00 KB", format_size(1024))
        self.assertEqual("1.50 MB", format_size(1572864))

    def test_run_log_records_context_in_utf8(self):
        path = self.root / "conversion_run.txt"

        append_run_log(path, "SpaceClaim version: 2022.2.0.0")
        append_run_log(path, "配置：SAB / Skip / V22")

        content = path.read_text(encoding="utf-8")
        self.assertIn("SpaceClaim version: 2022.2.0.0", content)
        self.assertIn("配置：SAB / Skip / V22", content)
        self.assertEqual(2, len(content.splitlines()))
