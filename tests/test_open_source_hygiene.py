"""Public-source privacy and packaging boundary checks."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TRACKED_SUFFIXES = {
    ".stp",
    ".step",
    ".sab",
    ".sat",
    ".exe",
    ".dll",
    ".pdb",
    ".zip",
    ".log",
    ".csv",
}

FORBIDDEN_TEXT_PATTERNS = (
    ("windows-user-profile", r"(?i)[a-z]:\\users\\[^\\\r\n]+"),
    ("private-workspace-root", r"(?i)[a-z]:\\[^\r\n]*\\codex\\projects\\"),
    ("project-number", r"(?i)project[_-]?\d{5,}"),
    ("model-number", r"(?i)J\d+(?:\.\d+){2,}[_-]"),
    ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    ("github-classic-token", r"ghp_[A-Za-z0-9]{20,}"),
    ("github-fine-grained-token", r"github_pat_[A-Za-z0-9_]{20,}"),
    ("openai-api-key", r"sk-[A-Za-z0-9_-]{20,}"),
    ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def tracked_paths() -> tuple[str, ...]:
    if not (REPOSITORY_ROOT / ".git").exists():
        return tuple(
            sorted(
                path.relative_to(REPOSITORY_ROOT).as_posix()
                for path in REPOSITORY_ROOT.rglob("*")
                if path.is_file()
            )
        )
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    )


def ignored_paths_from_file() -> set[str]:
    return {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and not line.lstrip().startswith("!")
    }


class OpenSourceHygieneTests(unittest.TestCase):
    def test_history_free_export_scans_all_regular_files(self) -> None:
        """A git archive must keep hygiene checks effective without .git metadata."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            export_root = Path(temporary_directory) / "public-source"
            for relative_path in tracked_paths():
                source = REPOSITORY_ROOT / relative_path
                if source.is_file():
                    destination = export_root / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)

            command = [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "unittest",
                "tests.test_open_source_hygiene.OpenSourceHygieneTests.test_machine_bound_configuration_files_are_untracked_and_ignored",
                "tests.test_open_source_hygiene.OpenSourceHygieneTests.test_tracked_files_do_not_include_packaged_or_cad_artifacts",
                "tests.test_open_source_hygiene.OpenSourceHygieneTests.test_utf8_tracked_text_has_no_private_path_or_credential_patterns",
            ]
            clean_result = subprocess.run(
                command,
                cwd=export_root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(clean_result.returncode, 0, clean_result.stderr)

            untracked_text = "\\".join(("C:", "Users", "fixture-user"))
            (export_root / "untracked.txt").write_text(untracked_text, encoding="utf-8")
            contaminated_result = subprocess.run(
                command,
                cwd=export_root,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(contaminated_result.returncode, 0)
            self.assertIn("windows-user-profile", contaminated_result.stderr)

    def test_machine_bound_configuration_files_are_untracked_and_ignored(self) -> None:
        paths = set(tracked_paths())
        for configuration in (
            "converter_config.json",
            "spaceclaim_cli_profile.json",
        ):
            with self.subTest(configuration=configuration):
                self.assertNotIn(configuration, paths)
                if (REPOSITORY_ROOT / ".git").exists():
                    ignored = subprocess.run(
                        ["git", "check-ignore", "--quiet", "--", configuration],
                        cwd=REPOSITORY_ROOT,
                    )
                    self.assertEqual(ignored.returncode, 0)
                else:
                    self.assertIn(configuration, ignored_paths_from_file())

    def test_tracked_files_do_not_include_packaged_or_cad_artifacts(self) -> None:
        violations = [
            path
            for path in tracked_paths()
            if Path(path).suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES
        ]
        self.assertEqual(violations, [], f"forbidden tracked artifacts: {violations}")

    def test_utf8_tracked_text_has_no_private_path_or_credential_patterns(self) -> None:
        violations: list[str] = []
        for relative_path in tracked_paths():
            path = REPOSITORY_ROOT / relative_path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for category, expression in FORBIDDEN_TEXT_PATTERNS:
                if re.search(expression, text):
                    violations.append(f"{relative_path}: {category}")
        self.assertEqual(violations, [], f"private text findings: {violations}")

    def test_utf8_tracked_text_has_no_extra_eof_blank_line(self) -> None:
        violations: list[str] = []
        for relative_path in tracked_paths():
            path = REPOSITORY_ROOT / relative_path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if text.endswith("\n\n"):
                violations.append(relative_path)
        self.assertEqual(violations, [], f"extra EOF blank lines: {violations}")
