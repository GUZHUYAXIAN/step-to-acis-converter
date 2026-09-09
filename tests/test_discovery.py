import hashlib
from pathlib import Path
import tempfile
import unittest

from step_to_acis.discovery import (
    OutputSafetyError,
    assert_safe_output,
    build_plan,
    scan_step_files,
)
from step_to_acis.models import (
    AcisSettings,
    ConverterConfig,
    OutputFormat,
    OverwritePolicy,
    Status,
)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_dir = self.root / "输入 files"
        self.input_dir.mkdir()
        self.output_dir = self.root / "输出 files"
        self.executable = self.root / "SpaceClaim.exe"
        self.executable.write_bytes(b"exe")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def config(self, **updates):
        values = {
            "spaceclaim_exe": self.executable,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "recursive": False,
            "acis": AcisSettings((OutputFormat.SAB,), "current_spaceclaim_default", "Millimeters"),
            "overwrite_policy": OverwritePolicy.SKIP,
            "chunk_size": 20,
            "heartbeat_timeout_seconds": 900.0,
            "retry_count": 0,
            "preserve_relative_directories": True,
            "long_path_warning_threshold": 240,
        }
        values.update(updates)
        return ConverterConfig(**values)

    def create_source(self, relative_path, content=b"STEP"):
        path = self.input_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_scan_recognizes_step_extensions_case_insensitively(self):
        expected = [
            self.create_source("a.stp"),
            self.create_source("b.step"),
            self.create_source("c.STP"),
            self.create_source("d.StEp"),
        ]
        self.create_source("ignored.iges")

        actual = scan_step_files(self.input_dir, recursive=False)

        self.assertEqual(sorted(expected, key=lambda path: path.name.casefold()), actual)

    def test_recursive_scan_is_explicit(self):
        top = self.create_source("top.stp")
        nested = self.create_source("子目录/nested.step")

        self.assertEqual([top], scan_step_files(self.input_dir, recursive=False))
        self.assertEqual(
            [top, nested],
            scan_step_files(self.input_dir, recursive=True),
        )

    def test_plan_preserves_relative_directories_and_names(self):
        source = self.create_source("子目录/连接板 001.STP", b"12345")

        tasks, preflight = build_plan(self.config(recursive=True))

        self.assertEqual([], preflight)
        self.assertEqual(1, len(tasks))
        self.assertEqual(source, tasks[0].source_path)
        self.assertEqual(self.output_dir / "子目录" / "连接板 001.sab", tasks[0].output_path)
        self.assertEqual(5, tasks[0].source_size_bytes)
        self.assertEqual(tasks[0].output_path.parent, tasks[0].staging_output_path.parent)
        self.assertEqual(".sab", tasks[0].staging_output_path.suffix)

    def test_same_directory_stp_and_step_collision_fails_both(self):
        self.create_source("part.stp")
        self.create_source("part.step")

        tasks, preflight = build_plan(self.config())

        self.assertEqual([], tasks)
        self.assertEqual(2, len(preflight))
        self.assertTrue(all(result.status is Status.FAILED for result in preflight))
        self.assertTrue(all("collision" in result.error_message for result in preflight))

    def test_same_name_in_different_subdirectories_is_safe(self):
        self.create_source("A/part.stp")
        self.create_source("B/part.step")

        tasks, preflight = build_plan(self.config(recursive=True))

        self.assertEqual([], preflight)
        self.assertEqual(
            [self.output_dir / "A" / "part.sab", self.output_dir / "B" / "part.sab"],
            [task.output_path for task in tasks],
        )

    def test_existing_output_is_skipped_without_creating_a_task(self):
        source = self.create_source("existing.stp")
        self.output_dir.mkdir()
        output = self.output_dir / "existing.sab"
        output.write_bytes(b"existing-output")

        tasks, preflight = build_plan(self.config())

        self.assertEqual([], tasks)
        self.assertEqual(1, len(preflight))
        result = preflight[0]
        self.assertEqual(Status.SKIPPED, result.status)
        self.assertEqual(len(b"existing-output"), result.output_size_bytes)
        self.assertEqual(str(source), result.source_path)

    def test_overwrite_keeps_existing_output_and_uses_unique_staging_path(self):
        self.create_source("existing.stp")
        self.output_dir.mkdir()
        output = self.output_dir / "existing.sab"
        output.write_bytes(b"keep-me")

        tasks, preflight = build_plan(
            self.config(overwrite_policy=OverwritePolicy.OVERWRITE)
        )

        self.assertEqual([], preflight)
        self.assertEqual(b"keep-me", output.read_bytes())
        self.assertNotEqual(output, tasks[0].staging_output_path)
        self.assertFalse(tasks[0].staging_output_path.exists())

    def test_planning_does_not_modify_source(self):
        source = self.create_source("原始文件.stp", b"unchanged-source")
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        original_mtime = source.stat().st_mtime_ns

        build_plan(self.config())

        self.assertEqual(original_hash, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(original_mtime, source.stat().st_mtime_ns)

    def test_output_safety_rejects_outside_root_wrong_extension_and_source(self):
        source = self.create_source("part.stp")
        source_paths = {source}

        with self.assertRaises(OutputSafetyError):
            assert_safe_output(self.root / "outside.sab", self.output_dir, source_paths)
        with self.assertRaises(OutputSafetyError):
            assert_safe_output(self.output_dir / "part.stp", self.output_dir, source_paths)
        with self.assertRaises(OutputSafetyError):
            assert_safe_output(source, self.input_dir, source_paths)

    def test_long_paths_are_flagged_for_spaceclaim_preflight(self):
        self.create_source("part.stp")

        tasks, _ = build_plan(self.config(long_path_warning_threshold=1))

        self.assertTrue(tasks[0].requires_spaceclaim_path_probe)
