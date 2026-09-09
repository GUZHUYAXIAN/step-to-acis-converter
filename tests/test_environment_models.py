from pathlib import Path
import unittest

from step_to_acis.environment_models import (
    REQUIRED_CHECK_IDS,
    CheckResult,
    EnvironmentState,
)


def check(check_id, status, *, severity="required"):
    return CheckResult(
        check_id,
        severity,
        status,
        "摘要",
        "原因",
        "修复建议",
    )


def passing_required_checks():
    return tuple(check(check_id, "pass") for check_id in REQUIRED_CHECK_IDS)


class EnvironmentModelTests(unittest.TestCase):
    def test_all_required_pass_with_profile_authorizes_entry(self):
        state = EnvironmentState(
            checks=passing_required_checks()
            + (check("notice", "warning", severity="warning"),),
            profile_path=Path("capability.json"),
        )

        self.assertTrue(state.can_enter_converter)

    def test_pending_failure_busy_missing_profile_or_missing_check_fail_closed(self):
        states = (
            EnvironmentState(
                checks=passing_required_checks()[:-1]
                + (check(REQUIRED_CHECK_IDS[-1], "pending"),),
                profile_path=Path("p"),
            ),
            EnvironmentState(
                checks=passing_required_checks()[:-1]
                + (check(REQUIRED_CHECK_IDS[-1], "failure"),),
                profile_path=Path("p"),
            ),
            EnvironmentState(
                checks=passing_required_checks(), profile_path=Path("p"), busy=True
            ),
            EnvironmentState(checks=passing_required_checks()),
            EnvironmentState(
                checks=passing_required_checks()[:-1], profile_path=Path("p")
            ),
        )

        self.assertTrue(all(not state.can_enter_converter for state in states))

    def test_warning_rows_never_block_when_required_checks_pass(self):
        state = EnvironmentState(
            checks=passing_required_checks()
            + (check("unsupported_candidate", "warning", severity="warning"),),
            profile_path=Path("p"),
        )

        self.assertTrue(state.can_enter_converter)

    def test_failure_requires_chinese_reason_and_remediation(self):
        with self.assertRaises(ValueError):
            CheckResult("broken", "required", "failure", "失败", "", "请修复")
        with self.assertRaises(ValueError):
            CheckResult("broken", "required", "failure", "失败", "原因", "")


if __name__ == "__main__":
    unittest.main()
